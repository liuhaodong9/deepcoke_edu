"""
Admin papers API — 管理员上传 PDF / 查看文档列表 / 删除 / 重新抽取摘要

挂载在 /admin/papers/* 路由。
权限:request.state.user_id == 'admin' 才能访问(继承 test.py 的 auth middleware)

新增的 4 个接口:
  POST   /admin/papers/upload         上传 PDF + 异步 ingest
  GET    /admin/papers/list           文档列表(含 deep_summary 状态)
  DELETE /admin/papers/{id}           删除文献(papers.db + ChromaDB chunks)
  POST   /admin/papers/{id}/rebuild   重新生成 deep_summary
  GET    /admin/papers/jobs/{job_id}  查异步任务状态(上传/重抽 进度)
"""
import logging
import os
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

logger = logging.getLogger("deepcoke.admin_papers")
router = APIRouter(prefix="/admin/papers", tags=["admin"])

# 内存中的任务进度表 — 简单 K-V,够单进程 demo 用
# 生产可换 redis/db
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


# ── Path 配置 ──────────────────────────────────────────────────────────
def _data_dir() -> Path:
    from deepcoke import config as _c
    return _c.DATA_DIR


def _uploads_dir() -> Path:
    p = _data_dir() / "uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _papers_db_path() -> str:
    return str(_data_dir() / "papers.db")


# ── Auth helper ──────────────────────────────────────────────────────────
def require_admin(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if not user_id or user_id != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user_id


# ── Job 状态管理 ─────────────────────────────────────────────────────────
def _set_job(job_id: str, **fields):
    with _jobs_lock:
        cur = _jobs.get(job_id, {})
        cur.update(fields)
        cur["updated_at"] = datetime.utcnow().isoformat()
        _jobs[job_id] = cur


def _get_job(job_id: str) -> Optional[dict]:
    with _jobs_lock:
        return _jobs.get(job_id)


# ── 后台:ingest + deep_summary ────────────────────────────────────────
def _bg_ingest_then_summary(job_id: str, pdf_path: str):
    """后台线程:跑 ingest + (异步) deep_summary。"""
    try:
        _set_job(job_id, status="ingesting", message="正在解析 PDF + 分块 + 向量化")

        # 1) 跑 ingestion(同步)
        from deepcoke.ingestion import run_ingestion
        # run_ingestion 用 scan_dir 风格,这里指定单文件方式
        # 简单办法:把 PDF 移到扫描目录,跑 main(),然后查 papers.db 拿到 paper_id
        scan_dir = Path("/opt/deepcoke/code/Coal blend paper")
        scan_dir.mkdir(parents=True, exist_ok=True)
        target = scan_dir / Path(pdf_path).name
        if Path(pdf_path) != target:
            shutil.copy(pdf_path, target)

        # 跑 ingestion main
        # run_ingestion 没有 main(),我们调底层
        from deepcoke.ingestion.run_ingestion import (
            get_db,
            create_papers_table,
            is_already_ingested,
        )
        # 简单做法:启子进程跑 run_ingestion 模块,确保不阻塞 + 不污染 import state
        import subprocess
        proc = subprocess.Popen(
            ["python", "-X", "utf8", "-m", "deepcoke.ingestion.run_ingestion"],
            cwd="/opt/deepcoke/code/src/LLM_back",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        out, err = proc.communicate(timeout=600)
        if proc.returncode != 0:
            raise RuntimeError(f"ingest failed (rc={proc.returncode}): {err.decode()[-500:]}")

        # 查 papers.db 拿到新 paper_id
        conn = sqlite3.connect(_papers_db_path())
        row = conn.execute(
            "SELECT id, title FROM papers WHERE file_path LIKE ? ORDER BY id DESC LIMIT 1",
            (f"%{Path(pdf_path).name}",),
        ).fetchone()
        conn.close()
        if not row:
            raise RuntimeError("ingest 完成但 papers.db 找不到新 row")
        paper_id, title = row[0], row[1]
        _set_job(job_id, paper_id=paper_id, title=title,
                 status="summarizing",
                 message=f"已 ingest paper_id={paper_id},正在生成 deep_summary(~2 分钟)")

        # 2) 跑 deep_summary(同步,5 分钟以内)
        proc2 = subprocess.Popen(
            [
                "python", "-X", "utf8", "-m",
                "deepcoke.literature_qa.build_deep_summaries",
                "--paper-ids", str(paper_id),
            ],
            cwd="/opt/deepcoke/code/src/LLM_back",
            env={**os.environ,
                 "LLM_MODE": "openai",
                 "DEEPSEEK_BASE_URL": "http://127.0.0.1:11434/v1",
                 "DEEPSEEK_MODEL": "qwen3:8b",
                 "DEEPSEEK_API_KEY": "vllm-local",
                 "LLM_TIMEOUT": "600"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        out2, err2 = proc2.communicate(timeout=900)
        if proc2.returncode != 0:
            # 即便 summary 失败,ingest 成功也算 OK
            _set_job(job_id, status="done_no_summary",
                     message=f"ingest 完成但 deep_summary 失败: {err2.decode()[-300:]}")
            return

        _set_job(job_id, status="done",
                 message=f"已完成: paper_id={paper_id},含 deep_summary")
        logger.info(f"[admin upload] job={job_id} done pid={paper_id}")
    except subprocess.TimeoutExpired:
        _set_job(job_id, status="error", message="超时")
    except Exception as e:
        _set_job(job_id, status="error", message=str(e))
        logger.exception(f"[admin upload] job={job_id} failed")


def _bg_rebuild_summary(job_id: str, paper_id: int):
    """后台线程:对指定 paper 重新生成 deep_summary。"""
    import subprocess
    try:
        _set_job(job_id, status="summarizing",
                 message=f"重新生成 paper_id={paper_id} 的 deep_summary",
                 paper_id=paper_id)
        proc = subprocess.Popen(
            ["python", "-X", "utf8", "-m",
             "deepcoke.literature_qa.build_deep_summaries",
             "--paper-ids", str(paper_id), "--force"],
            cwd="/opt/deepcoke/code/src/LLM_back",
            env={**os.environ,
                 "LLM_MODE": "openai",
                 "DEEPSEEK_BASE_URL": "http://127.0.0.1:11434/v1",
                 "DEEPSEEK_MODEL": "qwen3:8b",
                 "DEEPSEEK_API_KEY": "vllm-local",
                 "LLM_TIMEOUT": "600"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        out, err = proc.communicate(timeout=900)
        if proc.returncode != 0:
            _set_job(job_id, status="error",
                     message=f"重抽失败: {err.decode()[-300:]}")
            return
        _set_job(job_id, status="done",
                 message=f"paper_id={paper_id} 的 deep_summary 已重新生成")
    except subprocess.TimeoutExpired:
        _set_job(job_id, status="error", message="超时")
    except Exception as e:
        _set_job(job_id, status="error", message=str(e))


# ── API endpoints ────────────────────────────────────────────────────────
@router.post("/upload")
async def admin_upload_pdf(
    request: Request,
    file: UploadFile = File(...),
):
    """上传 PDF -> 保存 -> 异步 ingest + deep_summary。返回 job_id 给前端轮询状态。"""
    require_admin(request)
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="只支持 PDF 文件")

    job_id = uuid.uuid4().hex[:12]
    upload_path = _uploads_dir() / file.filename
    # 防重名: 加 timestamp
    if upload_path.exists():
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        stem = upload_path.stem
        upload_path = upload_path.with_name(f"{stem}_{ts}.pdf")

    with open(upload_path, "wb") as out:
        shutil.copyfileobj(file.file, out)
    file.file.close()
    size_mb = upload_path.stat().st_size / 1024 / 1024
    logger.info(f"[admin upload] saved {upload_path} ({size_mb:.1f} MB) job={job_id}")

    _set_job(job_id, status="queued", message="已上传,等待处理",
             filename=file.filename, size_mb=round(size_mb, 1))

    threading.Thread(
        target=_bg_ingest_then_summary,
        args=(job_id, str(upload_path)),
        daemon=True,
    ).start()

    return {"job_id": job_id, "filename": file.filename, "size_mb": round(size_mb, 1)}


@router.get("/jobs/{job_id}")
async def admin_job_status(request: Request, job_id: str):
    """轮询任务进度。"""
    require_admin(request)
    job = _get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job 不存在")
    return {"job_id": job_id, **job}


@router.get("/list")
async def admin_list_papers(request: Request, offset: int = 0, limit: int = 1000):
    """所有文献清单(含 deep_summary 状态、chunk 数、ingest 时间)。"""
    require_admin(request)
    conn = sqlite3.connect(_papers_db_path())
    conn.row_factory = sqlite3.Row
    cols = [r[1] for r in conn.execute("PRAGMA table_info(papers)").fetchall()]
    has_deep = "deep_summary" in cols
    sel = (
        "id, title, authors, year, category, chunk_count, ingested_at, file_path"
        + (", LENGTH(deep_summary) AS deep_summary_len" if has_deep else "")
    )
    rows = conn.execute(
        f"SELECT {sel} FROM papers ORDER BY id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    total_with_summary = (
        conn.execute(
            "SELECT COUNT(*) FROM papers WHERE deep_summary IS NOT NULL AND deep_summary != ''"
        ).fetchone()[0]
        if has_deep
        else 0
    )
    conn.close()

    items = []
    for r in rows:
        d = dict(r)
        d["has_deep_summary"] = bool(d.pop("deep_summary_len", 0))
        items.append(d)
    return {
        "items": items,
        "total": total,
        "total_with_summary": total_with_summary,
        "offset": offset,
        "limit": limit,
    }


@router.delete("/{paper_id}")
async def admin_delete_paper(request: Request, paper_id: int):
    """删除一篇文献: papers.db row + ChromaDB chunks。文件不删(防误)。"""
    require_admin(request)
    conn = sqlite3.connect(_papers_db_path())
    row = conn.execute("SELECT id, title FROM papers WHERE id = ?", (paper_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"paper_id={paper_id} 不存在")

    # 删 ChromaDB chunks
    try:
        from deepcoke.vectorstore.chromadb_store import get_collection
        coll = get_collection()
        raw = coll.get(where={"paper_id": int(paper_id)}, limit=1000)
        ids = raw.get("ids") or []
        if ids:
            coll.delete(ids=ids)
        chunk_deleted = len(ids)
    except Exception as e:
        chunk_deleted = -1
        logger.warning(f"chromadb delete failed: {e}")

    # 删 papers.db
    conn.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
    conn.commit()
    conn.close()

    logger.info(f"[admin delete] paper_id={paper_id} chunks={chunk_deleted}")
    return {"paper_id": paper_id, "chunks_deleted": chunk_deleted, "title": row[1]}


@router.post("/{paper_id}/rebuild")
async def admin_rebuild_summary(request: Request, paper_id: int):
    """重新生成 deep_summary(异步)。"""
    require_admin(request)
    conn = sqlite3.connect(_papers_db_path())
    exists = conn.execute("SELECT 1 FROM papers WHERE id = ?", (paper_id,)).fetchone()
    conn.close()
    if not exists:
        raise HTTPException(status_code=404, detail=f"paper_id={paper_id} 不存在")

    job_id = uuid.uuid4().hex[:12]
    _set_job(job_id, status="queued",
             message="任务排队中,等待处理",
             paper_id=paper_id, op="rebuild_summary")
    threading.Thread(
        target=_bg_rebuild_summary, args=(job_id, paper_id), daemon=True
    ).start()
    return {"job_id": job_id, "paper_id": paper_id}
