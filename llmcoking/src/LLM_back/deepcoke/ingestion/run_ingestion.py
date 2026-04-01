"""
CLI script to process all papers in the Coal blend paper directory.
Extracts text, metadata, tags, chunks, and stores in ChromaDB + SQLite.

Uses a local SQLite database (independent of MySQL) for paper metadata.

Usage:
    cd D:\焦化机器人PC端\llmcoking\src\LLM_back
    python -m deepcoke.ingestion.run_ingestion
"""
import sys
import json
import time
import sqlite3
from pathlib import Path

# Ensure the LLM_back dir is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from deepcoke import config
from deepcoke.ingestion.pdf_parser import parse_pdf
from deepcoke.ingestion.metadata_extractor import extract_metadata, infer_category
from deepcoke.ingestion.tagging import generate_tags
from deepcoke.vectorstore.chunker import chunk_sections
from deepcoke.vectorstore.chromadb_store import get_collection, upsert_chunks

# SQLite database path (lives alongside ChromaDB data)
PAPERS_DB_PATH = config.DATA_DIR / "papers.db"


def get_db() -> sqlite3.Connection:
    """Get a connection to the local SQLite papers database."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(PAPERS_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def create_papers_table(conn: sqlite3.Connection):
    """Create the papers table if it doesn't exist."""
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
    """Normalize file path to consistent forward-slash format."""
    return str(file_path).replace("\\", "/")


def is_already_ingested(conn: sqlite3.Connection, file_path: str) -> bool:
    """Check if a paper has already been ingested."""
    norm = _normalize_path(file_path)
    row = conn.execute(
        "SELECT id FROM papers WHERE file_path = ?", (norm,)
    ).fetchone()
    return row is not None


def insert_paper_record(conn, metadata, file_path, category, tags, chunk_count) -> int:
    """Insert a paper record into SQLite and return its ID."""
    norm = _normalize_path(file_path)
    cursor = conn.execute(
        """INSERT OR REPLACE INTO papers (file_path, title, authors, abstract, keywords,
                               year, category, auto_topics, chunk_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            norm,
            metadata.title[:500],
            json.dumps(metadata.authors, ensure_ascii=False),
            metadata.abstract[:5000],
            json.dumps(metadata.keywords, ensure_ascii=False),
            metadata.year,
            category,
            json.dumps(tags, ensure_ascii=False),
            chunk_count,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def find_all_pdfs(root: Path) -> list[Path]:
    """Recursively find all PDF files."""
    return sorted(root.rglob("*.pdf"))


def run():
    """Main ingestion pipeline."""
    total_t0 = time.time()

    print("=" * 60)
    print("  DeepCoke 文献导入工具")
    print("=" * 60)
    print()

    # Step 0: Initialize database
    print("[初始化] 连接 SQLite 论文数据库...")
    conn = get_db()
    create_papers_table(conn)
    print("[初始化] SQLite 就绪 ✓")

    # Step 1: Initialize ChromaDB + embedding model (may download ~440MB on first run)
    print("[初始化] 加载 ChromaDB 和 Embedding 模型（首次运行需下载约440MB，请耐心等待）...")
    init_t0 = time.time()
    collection = get_collection()
    print(f"[初始化] ChromaDB 就绪 ✓ （耗时 {time.time() - init_t0:.1f}s）")

    # Step 2: Scan PDFs
    print(f"[扫描] 扫描目录: {config.PAPERS_DIR}")
    pdfs = find_all_pdfs(config.PAPERS_DIR)
    total = len(pdfs)
    print(f"[扫描] 发现 {total} 篇 PDF 文件")
    print(f"[路径] Papers DB: {PAPERS_DB_PATH}")
    print(f"[路径] ChromaDB:  {config.CHROMADB_DIR}")
    print()

    if total == 0:
        print("没有找到 PDF 文件，请检查目录路径是否正确。")
        return

    success = 0
    failed = 0
    skipped = 0

    for i, pdf_path in enumerate(pdfs, 1):
        file_key = _normalize_path(pdf_path)
        progress = f"[{i}/{total}]"

        # Skip already ingested
        if is_already_ingested(conn, file_key):
            print(f"{progress} 跳过（已导入）: {pdf_path.name}")
            skipped += 1
            continue

        print(f"\n{progress} 正在处理: {pdf_path.name}")
        t0 = time.time()

        # Step 1: Parse PDF
        print(f"  ├─ 解析 PDF ...")
        try:
            parsed = parse_pdf(pdf_path)
        except Exception as e:
            print(f"  └─ ✗ 解析失败: {e}")
            failed += 1
            continue

        if parsed is None:
            print(f"  └─ ✗ 无法提取文本，跳过")
            failed += 1
            continue
        print(f"  ├─ 解析完成（{parsed.page_count} 页）")

        # Step 2: Extract metadata from first pages
        print(f"  ├─ 提取元数据 ...")
        first_pages = "\n".join(
            s.text for s in parsed.sections[:3]
        ) if parsed.sections else parsed.raw_text[:4000]

        try:
            meta = extract_metadata(first_pages, str(pdf_path))
        except Exception as e:
            print(f"  ├─ ⚠ 元数据提取失败 ({e})，使用文件名")
            from deepcoke.ingestion.metadata_extractor import PaperMetadata
            meta = PaperMetadata(title=pdf_path.stem)

        print(f"  ├─ 标题: {meta.title[:80]}")

        # Step 3: Infer category from folder structure
        category = infer_category(pdf_path)
        print(f"  ├─ 分类: {category}")

        # Step 4: Generate domain tags
        print(f"  ├─ 生成标签 ...")
        try:
            tags = generate_tags(meta.title, meta.abstract, meta.keywords)
        except Exception as e:
            print(f"  ├─ ⚠ 标签生成失败 ({e})")
            tags = []
        print(f"  ├─ 标签: {tags}")

        # Step 5: Chunk the paper
        chunks = chunk_sections(parsed.sections)
        print(f"  ├─ 分块: {len(chunks)} 个片段")

        # Step 6: Insert paper record into SQLite
        paper_id = insert_paper_record(conn, meta, pdf_path, category, tags, len(chunks))

        # Step 7: Upsert chunks into ChromaDB
        print(f"  ├─ 写入 ChromaDB ...")
        upsert_chunks(
            collection=collection,
            paper_id=paper_id,
            chunks=chunks,
            metadata_base={
                "title": meta.title[:200],
                "category": category,
                "year": meta.year or 0,
                "authors": ", ".join(meta.authors[:5]),
                "keywords": ", ".join(meta.keywords[:10]),
            },
        )

        elapsed = time.time() - t0
        print(f"  └─ ✓ 完成 ({elapsed:.1f}s, paper_id={paper_id})")
        success += 1

        # Show overall progress every 10 papers
        if success % 10 == 0:
            total_elapsed = time.time() - total_t0
            avg = total_elapsed / (success + skipped + failed)
            remaining = avg * (total - i)
            print(f"\n  >>> 进度: {i}/{total} | 成功: {success} | 跳过: {skipped} | 失败: {failed} | 预计剩余: {remaining:.0f}s\n")

    conn.close()
    total_elapsed = time.time() - total_t0
    print(f"\n{'=' * 60}")
    print(f"  导入完成!")
    print(f"  成功: {success}")
    print(f"  跳过: {skipped}")
    print(f"  失败: {failed}")
    print(f"  总计: {total}")
    print(f"  总耗时: {total_elapsed:.1f}s ({total_elapsed/60:.1f} 分钟)")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    run()
