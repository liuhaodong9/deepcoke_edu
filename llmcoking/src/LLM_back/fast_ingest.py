"""
快速文献导入 - 跳过 LLM 调用，直接从文本提取基本信息并写入 ChromaDB。
速度比完整版快 50-100 倍。

Usage:
    cd D:\焦化机器人PC端\llmcoking\src\LLM_back
    python fast_ingest.py
"""
import sys
import re
import time
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deepcoke import config
from deepcoke.ingestion.pdf_parser import parse_pdf
from deepcoke.ingestion.metadata_extractor import infer_category
from deepcoke.vectorstore.chunker import chunk_sections
from deepcoke.vectorstore.chromadb_store import get_collection, upsert_chunks

PAPERS_DB_PATH = config.DATA_DIR / "papers.db"


def get_db():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(PAPERS_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def create_papers_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS papers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL UNIQUE,
            title TEXT,
            authors TEXT,
            abstract TEXT,
            keywords TEXT,
            year INTEGER,
            category TEXT,
            auto_topics TEXT,
            language TEXT DEFAULT 'en',
            chunk_count INTEGER DEFAULT 0,
            ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def _normalize_path(file_path) -> str:
    return str(file_path).replace("\\", "/")


def is_already_ingested(conn, file_path) -> bool:
    norm = _normalize_path(file_path)
    row = conn.execute("SELECT id FROM papers WHERE file_path = ?", (norm,)).fetchone()
    return row is not None


def quick_extract_metadata(text, filename):
    """从文本前几行快速提取标题和年份，不调用 LLM。"""
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]

    # 标题：取第一个较长的非空行
    title = filename
    for line in lines[:10]:
        if len(line) > 15 and not re.match(r'^(page|vol|issue|doi|http|www)', line, re.I):
            title = line[:200]
            break

    # 年份：从文本中找四位数年份
    year = None
    year_match = re.search(r'(19|20)\d{2}', text[:3000])
    if year_match:
        y = int(year_match.group())
        if 1950 <= y <= 2030:
            year = y

    return title, year


def run():
    total_t0 = time.time()

    print("=" * 60)
    print("  DeepCoke 快速文献导入（无 LLM 调用）")
    print("=" * 60)
    print()

    print("[初始化] 连接数据库...")
    conn = get_db()
    create_papers_table(conn)
    print("[初始化] SQLite 就绪")

    print("[初始化] 加载 ChromaDB + Embedding 模型...")
    init_t0 = time.time()
    collection = get_collection()
    print(f"[初始化] ChromaDB 就绪 ({time.time() - init_t0:.1f}s)")

    print(f"[扫描] 目录: {config.PAPERS_DIR}")
    pdfs = sorted(config.PAPERS_DIR.rglob("*.pdf"))
    total = len(pdfs)
    print(f"[扫描] 发现 {total} 篇 PDF")
    print()

    if total == 0:
        print("没有找到 PDF 文件！")
        return

    success = 0
    failed = 0
    skipped = 0

    for i, pdf_path in enumerate(pdfs, 1):
        file_key = _normalize_path(pdf_path)

        if is_already_ingested(conn, file_key):
            skipped += 1
            if skipped <= 3 or skipped % 50 == 0:
                print(f"[{i}/{total}] 跳过（已导入）: {pdf_path.name}")
            continue

        t0 = time.time()

        # 解析 PDF
        try:
            parsed = parse_pdf(pdf_path)
        except Exception as e:
            print(f"[{i}/{total}] X 解析失败: {pdf_path.name} ({e})")
            failed += 1
            continue

        if parsed is None:
            print(f"[{i}/{total}] X 无法提取文本: {pdf_path.name}")
            failed += 1
            continue

        # 快速提取元数据（不用 LLM）
        title, year = quick_extract_metadata(parsed.raw_text, pdf_path.stem)
        category = infer_category(pdf_path)

        # 分块
        chunks = chunk_sections(parsed.sections)
        if not chunks:
            print(f"[{i}/{total}] X 无分块: {pdf_path.name}")
            failed += 1
            continue

        # 写入 SQLite
        norm = _normalize_path(pdf_path)
        cursor = conn.execute(
            """INSERT OR REPLACE INTO papers (file_path, title, authors, abstract, keywords,
                                   year, category, auto_topics, chunk_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (norm, title[:500], "[]", "", "[]", year, category, "[]", len(chunks)),
        )
        conn.commit()
        paper_id = cursor.lastrowid

        # 写入 ChromaDB
        upsert_chunks(
            collection=collection,
            paper_id=paper_id,
            chunks=chunks,
            metadata_base={
                "title": title[:200],
                "category": category,
                "year": year or 0,
                "authors": "",
                "keywords": "",
            },
        )

        elapsed = time.time() - t0
        print(f"[{i}/{total}] OK {pdf_path.name} | {parsed.page_count}页 | {len(chunks)}块 | {elapsed:.1f}s")
        success += 1

        # 每 10 篇显示进度
        if success % 10 == 0:
            total_elapsed = time.time() - total_t0
            processed = success + failed + skipped
            avg = total_elapsed / processed if processed else 1
            remaining = avg * (total - i)
            print(f"  >>> 进度 {i}/{total} | 成功 {success} | 失败 {failed} | 跳过 {skipped} | 预计剩余 {remaining:.0f}s")

    conn.close()
    total_elapsed = time.time() - total_t0
    print()
    print("=" * 60)
    print(f"  导入完成!")
    print(f"  成功: {success}  失败: {failed}  跳过: {skipped}  总计: {total}")
    print(f"  总耗时: {total_elapsed:.1f}s ({total_elapsed / 60:.1f} 分钟)")
    print("=" * 60)


if __name__ == "__main__":
    run()
