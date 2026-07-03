"""references 结构化:从每篇 References chunk 切分出单条参考文献(编号/年份/粗标题)。

不联网、不 LLM。产出 papers.db 新表 paper_references(paper_id, ref_no, raw, year)。
用途:文献卡"引用了 N 篇"、未来引用网络/研究脉络。抽不到留空,不强补。

用法(服务器容器内):
  cd /opt/deepcoke/code/src/LLM_back
  /opt/conda/envs/deepcoke/bin/python -X utf8 -m deepcoke.literature_qa.extract_references
  # --force 重跑
"""
import sys
import re
import argparse
import sqlite3
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from deepcoke import config   # noqa: E402

_YEAR_RE = re.compile(r"(19|20)\d{2}")
# 单条参考文献起始:行首编号 [1] / 1. / 1)
_ITEM_SPLIT = re.compile(r"(?:^|\n)\s*(?:\[\d{1,3}\]|\(\d{1,3}\)|\d{1,3}[.)])\s+")


def _split_refs(text: str) -> list[str]:
    """把 references 段文本切成单条。优先按编号切;无编号退回按行(过滤太短)。"""
    parts = _ITEM_SPLIT.split(text)
    parts = [p.strip() for p in parts if p and len(p.strip()) > 25]
    if len(parts) >= 3:
        return parts
    # 无编号:按换行,合并过短行
    lines = [ln.strip() for ln in text.split("\n") if len(ln.strip()) > 25]
    return lines


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_references (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER NOT NULL,
            ref_no INTEGER,
            raw TEXT,
            year INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ref_paper ON paper_references(paper_id)")
    conn.commit()


def run(force: bool):
    from deepcoke.vectorstore.chromadb_store import get_collection
    coll = get_collection()
    got = coll.get(include=["documents", "metadatas"])
    # 收集每篇的 references 文本
    ref_text = defaultdict(list)
    for doc, m in zip(got.get("documents") or [], got.get("metadatas") or []):
        sec = str(m.get("section") or "").lower()
        if "refer" in sec or "biblio" in sec:
            pid = m.get("paper_id")
            if pid is not None and doc:
                ref_text[pid].append((m.get("chunk_index", 0), doc))
    print(f"有 references 段的论文: {len(ref_text)}")

    db = sqlite3.connect(str(config.DATA_DIR / "papers.db"))
    ensure_table(db)
    if force:
        db.execute("DELETE FROM paper_references")
        db.commit()
    done = {r[0] for r in db.execute("SELECT DISTINCT paper_id FROM paper_references")}

    total_refs = 0
    for pid, chunks in ref_text.items():
        if pid in done and not force:
            continue
        chunks.sort()
        blob = "\n".join(c[1] for c in chunks)
        items = _split_refs(blob)
        for no, raw in enumerate(items, 1):
            ym = _YEAR_RE.search(raw)
            year = int(ym.group(0)) if ym else None
            db.execute(
                "INSERT INTO paper_references (paper_id, ref_no, raw, year) VALUES (?,?,?,?)",
                (pid, no, raw[:500], year))
            total_refs += 1
        print(f"  pid={pid}: {len(items)} 条参考文献")
    db.commit()

    # 每篇 ref 计数写回 papers.db(方便文献卡显示"引用 N 篇")
    cols = [r[1] for r in db.execute("PRAGMA table_info(papers)").fetchall()]
    if "ref_count" not in cols:
        db.execute("ALTER TABLE papers ADD COLUMN ref_count INTEGER")
    db.execute("""
        UPDATE papers SET ref_count = (
            SELECT COUNT(*) FROM paper_references WHERE paper_references.paper_id = papers.id)
    """)
    db.commit()

    # 回写 chroma:每 chunk 加 ref_count(供文献卡显示"引用 N 篇")
    counts = {r[0]: r[1] for r in db.execute(
        "SELECT paper_id, COUNT(*) FROM paper_references GROUP BY paper_id")}
    try:
        n = 0
        for pid, cnt in counts.items():
            raw = coll.get(where={"paper_id": int(pid)}, include=["metadatas"])
            ids, metas = raw.get("ids") or [], raw.get("metadatas") or []
            if not ids:
                continue
            for m in metas:
                m["ref_count"] = cnt
            coll.update(ids=ids, metadatas=metas)
            n += len(ids)
        print(f"回写 chroma: {n} chunks 加 ref_count")
    except Exception as e:
        print(f"回写 chroma 失败(不影响库): {e}")

    print(f"完成: 共抽 {total_refs} 条参考文献,{len(ref_text)} 篇")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    run(ap.parse_args().force)
