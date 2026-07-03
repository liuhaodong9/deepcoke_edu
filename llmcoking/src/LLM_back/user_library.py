"""玻尔-C 用户知识库 — 用户上传自己的 PDF,进独立 user_papers collection(按 owner 隔离),
可只对自己的文献库提问。共享语料链路一行不动,泄漏结构上不可能。

挂载在 /mylib/* 路由。

接口:
  POST   /mylib/upload?user_id=        上传 PDF + 异步 ingest 到 user_papers(owner=user_id)
  GET    /mylib/jobs/{job_id}          查上传任务进度
  GET    /mylib/papers?user_id=        我的文献列表
  DELETE /mylib/papers/{paper_id}?user_id=   删我的某篇(只能删自己的)
  POST   /mylib/chat?user_id=&q=       只对我的文献库提问(独立 lean 路径,不走主图)

隔离要点:
  - chunk 进 user_papers collection,metadata.owner_user_id = user_id
  - 检索一律加 where={"owner_user_id": user_id} → 只看自己的、看不到别人的、也混不进语料
"""
import logging
import os
import shutil
import threading
import uuid
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile, Request, Depends
from fastapi.responses import StreamingResponse


def _current_uid(request: Request) -> str:
    """从 token(中间件设的 state.user_id)取真实用户,忽略 query 传的 user_id,防越权。"""
    uid = getattr(request.state, "user_id", None)
    if not uid:
        raise HTTPException(status_code=401, detail="未登录")
    return uid

logger = logging.getLogger("deepcoke.user_library")
router = APIRouter(prefix="/mylib", tags=["mylib"])

USER_COLLECTION = "user_papers"

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _data_dir() -> Path:
    from deepcoke import config as _c
    return _c.DATA_DIR


def _user_dir(user_id: str) -> Path:
    # 每用户独立上传目录,ingestion 子进程只扫这里(零语料污染)
    safe = "".join(c for c in (user_id or "anon") if c.isalnum() or c in "_-")[:40] or "anon"
    p = _data_dir() / "user_uploads" / safe
    p.mkdir(parents=True, exist_ok=True)
    return p


def _set_job(job_id: str, **fields):
    with _jobs_lock:
        cur = _jobs.get(job_id, {})
        cur.update(fields)
        cur["updated_at"] = datetime.utcnow().isoformat()
        _jobs[job_id] = cur


def _get_job(job_id: str) -> Optional[dict]:
    with _jobs_lock:
        return _jobs.get(job_id)


def _user_collection():
    from deepcoke.vectorstore.chromadb_store import get_collection
    return get_collection(USER_COLLECTION)


# ── 后台 ingest ──────────────────────────────────────────────────────────
def _bg_ingest(job_id: str, user_id: str, user_dir: str):
    """子进程跑 run_ingestion,只扫 user_dir、写入 user_papers、chunk 标 owner=user_id。"""
    import subprocess
    try:
        _set_job(job_id, status="ingesting", message="正在解析 PDF + 分块 + 向量化")
        env = {
            **os.environ,
            "PAPERS_DIR": user_dir,             # 只扫该用户目录
            "INGEST_COLLECTION": USER_COLLECTION,  # 进独立用户库
            "INGEST_OWNER": user_id,            # chunk 标 owner
        }
        proc = subprocess.Popen(
            ["python", "-X", "utf8", "-m", "deepcoke.ingestion.run_ingestion"],
            cwd="/opt/deepcoke/code/src/LLM_back",
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        out, err = proc.communicate(timeout=600)
        if proc.returncode != 0:
            raise RuntimeError(f"ingest failed (rc={proc.returncode}): {err.decode()[-400:]}")
        _set_job(job_id, status="done", message="已加入你的文献库,可以提问了")
        logger.info(f"[mylib upload] job={job_id} user={user_id} done")
    except subprocess.TimeoutExpired:
        _set_job(job_id, status="error", message="处理超时")
    except Exception as e:
        _set_job(job_id, status="error", message=str(e))
        logger.exception(f"[mylib upload] job={job_id} failed")


# ── API ──────────────────────────────────────────────────────────────────
@router.post("/upload")
async def mylib_upload(uid: str = Depends(_current_uid), file: UploadFile = File(...)):
    """上传 PDF 到当前登录用户的文献库(异步 ingest)。返回 job_id 轮询进度。"""
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="只支持 PDF 文件")
    udir = _user_dir(uid)
    dest = udir / file.filename
    if dest.exists():
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        dest = dest.with_name(f"{dest.stem}_{ts}.pdf")
    with open(dest, "wb") as out:
        shutil.copyfileobj(file.file, out)
    file.file.close()
    job_id = uuid.uuid4().hex[:12]
    _set_job(job_id, status="queued", message="已上传,排队处理", filename=file.filename)
    threading.Thread(target=_bg_ingest, args=(job_id, uid, str(udir)), daemon=True).start()
    return {"job_id": job_id, "filename": file.filename}


@router.get("/jobs/{job_id}")
async def mylib_job(job_id: str):
    job = _get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job 不存在")
    return {"job_id": job_id, **job}


@router.get("/papers")
async def mylib_list(uid: str = Depends(_current_uid)):
    """当前登录用户的文献列表(从 user_papers 按 owner 去重)。"""
    try:
        coll = _user_collection()
        raw = coll.get(where={"owner_user_id": uid}, include=["metadatas"], limit=20000)
    except Exception as e:
        logger.warning(f"[mylib list] {e}")
        return []
    seen, items = set(), []
    for m in (raw.get("metadatas") or []):
        pid = m.get("paper_id")
        if pid in seen:
            continue
        seen.add(pid)
        items.append({"paper_id": pid, "title": m.get("title", "") or f"Paper {pid}",
                      "year": m.get("year", 0), "category": m.get("category", "")})
    return items


@router.delete("/papers/{paper_id}")
async def mylib_delete(paper_id: int, uid: str = Depends(_current_uid)):
    """删当前登录用户某篇(强制 owner 匹配,删不了别人的)。"""
    coll = _user_collection()
    raw = coll.get(where={"$and": [{"paper_id": int(paper_id)}, {"owner_user_id": uid}]}, limit=20000)
    ids = raw.get("ids") or []
    if not ids:
        raise HTTPException(status_code=404, detail="这篇不在你的文献库里")
    coll.delete(ids=ids)
    return {"paper_id": paper_id, "chunks_deleted": len(ids)}


@router.post("/chat")
async def mylib_chat(q: str, uid: str = Depends(_current_uid)):
    """只对当前登录用户的文献库提问:retrieve(user_papers, owner=uid) → 生成回答,带 [N] 引用。"""
    from deepcoke.vectorstore.retriever import retrieve
    from deepcoke.generation.answer_generator import generate_answer_stream

    def stream():
        try:
            chunks = retrieve(q, top_k=8, where={"owner_user_id": uid},
                              collection_name=USER_COLLECTION)
        except Exception as e:
            yield f"检索你的文献库失败: {e}"
            return
        if not chunks:
            yield "你的文献库里没有找到相关内容。先上传几篇 PDF,或换个问法。"
            return
        # 命中文献元数据,前端可渲染来源
        papers = []
        seen = set()
        for c in chunks:
            if c.paper_id not in seen:
                seen.add(c.paper_id)
                papers.append({"paper_id": c.paper_id, "title": getattr(c, "title", "") or "",
                               "year": getattr(c, "year", 0), "ref_num": len(papers) + 1, "cited": True})
        yield f"<!--LITQA_META:{json.dumps({'papers': papers, 'chunks': [], 'mode': 'mylib'}, ensure_ascii=False)}-->\n"
        for piece in generate_answer_stream(question=q, chunks=chunks, mode="qa"):
            yield piece

    return StreamingResponse(stream(), media_type="text/plain")
