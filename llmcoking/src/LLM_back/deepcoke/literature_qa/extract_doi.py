"""DOI 本地抽取(不联网)。从每篇 PDF 首几页文本正则抽 DOI,存 papers.db doi 列 + 回写 chroma。
抽不到留空(前端显示"未识别",不强补)。

DOI 格式: 10.NNNN/xxxxx。优先取 "doi:"/"https://doi.org/" 后的,其次裸 DOI。

用法(服务器容器内):
  cd /opt/deepcoke/code/src/LLM_back
  /opt/conda/envs/deepcoke/bin/python -X utf8 -m deepcoke.literature_qa.extract_doi
  # --force 重跑;  --no-chroma 只写库
"""
import sys
import re
import argparse
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from deepcoke import config   # noqa: E402

# DOI 正则:10. 开头,后接 4+ 数字 / 一段非空白(排除结尾标点)
_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:a-zA-Z0-9]+", re.I)
_DOI_LABELED = re.compile(r"(?:doi:?\s*|doi\.org/)\s*(10\.\d{4,9}/[-._;()/:a-zA-Z0-9]+)", re.I)


def _clean(doi: str) -> str:
    return doi.rstrip(".,;)]}").strip()


def extract_doi_from_pdf(pdf_path: str) -> str:
    try:
        import fitz
    except Exception:
        return ""
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return ""
    try:
        text = ""
        for i in range(min(3, doc.page_count)):   # 首 3 页
            text += doc[i].get_text() + "\n"
        # 优先带标签的
        m = _DOI_LABELED.search(text)
        if m:
            return _clean(m.group(1))
        m = _DOI_RE.search(text)
        return _clean(m.group(0)) if m else ""
    finally:
        doc.close()


def ensure_column(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(papers)").fetchall()]
    if "doi" not in cols:
        conn.execute("ALTER TABLE papers ADD COLUMN doi TEXT")
        conn.commit()
        print("papers.db 加 doi 列")


def run(force: bool, write_chroma: bool):
    db = sqlite3.connect(str(config.DATA_DIR / "papers.db"))
    ensure_column(db)
    where = "" if force else "WHERE (doi IS NULL OR doi = '')"
    rows = db.execute(f"SELECT id, file_path FROM papers {where}").fetchall()
    print(f"待抽 DOI: {len(rows)} 篇")

    assigned, hit = {}, 0
    for i, (pid, fp) in enumerate(rows, 1):
        doi = extract_doi_from_pdf(fp) if fp else ""
        db.execute("UPDATE papers SET doi = ? WHERE id = ?", (doi, pid))
        assigned[pid] = doi
        if doi:
            hit += 1
        if i % 20 == 0:
            db.commit()
            print(f"  [{i}/{len(rows)}] 已抽 {hit} 个 DOI")
    db.commit()
    print(f"完成: {len(rows)} 篇,命中 {hit} 个 DOI ({hit*100//max(1,len(rows))}%)")

    if write_chroma and assigned:
        try:
            from deepcoke.vectorstore.chromadb_store import get_collection
            coll = get_collection()
            n = 0
            for pid, doi in assigned.items():
                if not doi:
                    continue
                raw = coll.get(where={"paper_id": int(pid)}, include=["metadatas"])
                ids, metas = raw.get("ids") or [], raw.get("metadatas") or []
                if not ids:
                    continue
                for m in metas:
                    m["doi"] = doi
                coll.update(ids=ids, metadatas=metas)
                n += len(ids)
            print(f"回写 chroma: {n} chunks 加 doi")
        except Exception as e:
            print(f"回写 chroma 失败(不影响库): {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-chroma", action="store_true")
    args = ap.parse_args()
    run(args.force, not args.no_chroma)
