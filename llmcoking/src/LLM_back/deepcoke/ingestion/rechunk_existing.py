"""重切块 — 用新结构化 ingestion 重建已有论文的 ChromaDB chunks,**不动** papers.db
(title/abstract/deep_summary)和定量表。

为什么单独写:papers 已导入过,metadata/deep_summary/quant 都在且抽取昂贵。
升级到结构化 chunk(带 page/section/table/bbox)只需重解析 PDF + 重切块 + 换 chroma chunks,
不需要重跑 LLM metadata 抽取,也不该碰 deep_summary/定量表。生产上同样适用(省掉 ~11h 重抽)。

流程(每篇):parse_pdf(file_path) → chunk_blocks → 删该 paper 旧 chunks → upsert 新 chunks。

用法:
  cd src/LLM_back
  # 先试 10 篇
  python -X utf8 -m deepcoke.ingestion.rechunk_existing --limit 10
  # 全量
  python -X utf8 -m deepcoke.ingestion.rechunk_existing
"""
import sys
import time
import argparse
import sqlite3
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from deepcoke import config
from deepcoke.ingestion.pdf_parser import parse_pdf
from deepcoke.vectorstore.chunker import chunk_blocks
from deepcoke.vectorstore.chromadb_store import get_collection, upsert_chunks


def _authors_str(raw) -> str:
    """papers.authors 存的是 JSON 数组字符串,还原成逗号串。"""
    if not raw:
        return ""
    try:
        arr = json.loads(raw)
        return ", ".join(arr[:5]) if isinstance(arr, list) else str(raw)
    except Exception:
        return str(raw)


def _keywords_str(raw) -> str:
    if not raw:
        return ""
    try:
        arr = json.loads(raw)
        return ", ".join(arr[:10]) if isinstance(arr, list) else str(raw)
    except Exception:
        return str(raw)


def run(limit: int = None, only_missing: bool = False):
    t0 = time.time()
    conn = sqlite3.connect(str(config.DATA_DIR / "papers.db"))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, file_path, title, category, authors, year, keywords FROM papers ORDER BY id"
    ).fetchall()
    conn.close()
    if limit:
        rows = rows[:limit]

    collection = get_collection()
    total = len(rows)
    print(f"重切块: {total} 篇 → collection '{config.CHROMADB_COLLECTION}'\n")

    ok = skip = fail = 0
    n_table = n_fig = 0
    for i, r in enumerate(rows, 1):
        pid = r["id"]
        fp = r["file_path"]
        if not Path(fp).exists():
            print(f"[{i}/{total}] id={pid} 跳过(PDF 不存在): {Path(fp).name}")
            skip += 1
            continue
        try:
            parsed = parse_pdf(fp)
        except Exception as e:
            print(f"[{i}/{total}] id={pid} 解析异常: {e}")
            fail += 1
            continue
        if not parsed or not getattr(parsed, "blocks", None):
            print(f"[{i}/{total}] id={pid} 解析空/无 blocks(扫描件?): {Path(fp).name}")
            fail += 1
            continue

        chunks = chunk_blocks(parsed.blocks)
        if not chunks:
            print(f"[{i}/{total}] id={pid} 0 chunk,跳过")
            fail += 1
            continue

        # 删旧 chunks(等值 where,兼容生产 chromadb)再 upsert 新
        try:
            collection.delete(where={"paper_id": int(pid)})
        except Exception as e:
            print(f"  warn: 删旧 chunk 失败 id={pid}: {e}")

        upsert_chunks(
            collection=collection,
            paper_id=pid,
            chunks=chunks,
            metadata_base={
                "title": (r["title"] or "")[:200],
                "category": r["category"] or "",
                "year": r["year"] or 0,
                "authors": _authors_str(r["authors"]),
                "keywords": _keywords_str(r["keywords"]),
            },
        )
        nt = sum(1 for c in chunks if c.block_type == "table")
        nf = sum(1 for c in chunks if c.block_type == "figure")
        n_table += nt
        n_fig += nf
        ok += 1
        if i % 20 == 0 or i == total:
            el = time.time() - t0
            print(f"[{i}/{total}] ok={ok} skip={skip} fail={fail} | 累计表 {n_table} 图 {n_fig} | {el:.0f}s")

    print(f"\n完成: ok={ok} skip={skip} fail={fail} | 表 chunk {n_table} 图 chunk {n_fig} | {time.time()-t0:.0f}s")
    print(f"collection 现有 chunks: {collection.count()}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="只处理前 N 篇(试跑)")
    args = ap.parse_args()
    run(limit=args.limit)


if __name__ == "__main__":
    main()
