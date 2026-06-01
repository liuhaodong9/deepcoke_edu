"""
修三类"坏掉"的 title,统一 fallback 到 PDF 文件名 stem:

1. 含 ASCII 控制字符(U+0001-U+001F 除 \\t \\n \\r) → 浏览器渲染成方框
2. 含 LLM thinking 泄露(如 '/think', '<think>') → enrich_titles 的副作用
3. 同 category 内 title 重复多次 → 合集书的多个章节抓到了书名

不调 LLM,纯启发式 + 文件名 fallback,秒级完成。

Usage:
    cd D:\\deepcoke\\deepcoke_edu\\llmcoking\\src\\LLM_back
    python -X utf8 -u -m deepcoke.literature_qa.fix_broken_titles
"""
import os
import re
import sqlite3
from collections import Counter

import chromadb

from deepcoke import config
from deepcoke.vectorstore.chromadb_store import get_chroma_client

CARDS_COLLECTION = "papers_cards"

# 控制字符:除 \t (\x09) \n (\x0a) \r (\x0d) 之外的 0x00-0x1F
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# LLM 思考链泄露
_THINK_RE = re.compile(r"</?think>?|/think\b|<\s*/?(?:thought|reasoning)\s*>?", re.IGNORECASE)


def filename_stem_title(file_path: str) -> str:
    """从 file_path 提 stem 作为 title。"""
    if not file_path:
        return ""
    base = os.path.basename(file_path)
    stem = os.path.splitext(base)[0]
    # 清洗一些常见噪音:下划线/连字符变空格
    stem = stem.replace("_", " ").strip()
    return stem


def classify(title: str | None) -> str | None:
    """返回坏的类别名,好 title 返回 None。"""
    if not title:
        return "empty"
    if _CTRL_RE.search(title):
        return "control-char"
    if _THINK_RE.search(title):
        return "think-leak"
    return None


def main():
    db_path = config.DATA_DIR / "papers.db"
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row

    rows = list(db.execute("SELECT id, title, category, file_path FROM papers ORDER BY id"))

    # 1) 找出标题在同 category 内重复多次的(合集书章节)
    by_cat_title = Counter()
    for r in rows:
        by_cat_title[(r["category"], (r["title"] or "").strip().lower())] += 1
    dup_keys = {k for k, v in by_cat_title.items() if v >= 2 and k[1]}

    # 2) 综合判定每篇要不要替换
    fixes = []  # list of (paper_id, old, new, reason)
    for r in rows:
        pid = r["id"]
        old = r["title"]
        reason = classify(old)
        if reason is None:
            key = (r["category"], (old or "").strip().lower())
            if key in dup_keys:
                reason = "dup-in-cat"
            else:
                continue
        new = filename_stem_title(r["file_path"])
        if not new or new.lower() == (old or "").lower():
            continue
        fixes.append((pid, old, new, reason))

    print(f"待修复 title 数: {len(fixes)}\n")
    for pid, old, new, why in fixes:
        old_disp = repr(old)[:60]
        new_disp = new[:70]
        print(f"  id={pid:3d} [{why:13s}]")
        print(f"      OLD: {old_disp}")
        print(f"      NEW: {new_disp}")

    if not fixes:
        print("没有需要修复的 title")
        return

    # 写回 papers.db
    for pid, _, new, _ in fixes:
        db.execute("UPDATE papers SET title = ? WHERE id = ?", (new, pid))
    db.commit()
    print(f"\n写回 papers.db: {len(fixes)} 行")

    # 同步 ChromaDB chunks
    client = get_chroma_client()
    col = client.get_collection(config.CHROMADB_COLLECTION)
    chunks_data = col.get(include=["metadatas"])
    fixed_map = {pid: new for pid, _, new, _ in fixes}
    ids_upd, mds_upd = [], []
    for i, m in enumerate(chunks_data["metadatas"]):
        if m["paper_id"] in fixed_map:
            nm = dict(m)
            nm["title"] = fixed_map[m["paper_id"]][:200]
            for k, v in list(nm.items()):
                if v is None:
                    nm[k] = ""
            ids_upd.append(chunks_data["ids"][i])
            mds_upd.append(nm)
    print(f"coking_papers 待改 chunks: {len(ids_upd)}")
    for s in range(0, len(ids_upd), 1000):
        e = min(s + 1000, len(ids_upd))
        col.update(ids=ids_upd[s:e], metadatas=mds_upd[s:e])

    # 同步 papers_cards
    cards = client.get_collection(CARDS_COLLECTION)
    cdata = cards.get(include=["metadatas", "documents"])
    by_id = {
        r["id"]: dict(r)
        for r in db.execute(
            "SELECT id, title, authors, year, category, journal, abstract FROM papers"
        )
    }
    ids_upd, mds_upd, docs_upd = [], [], []
    for i, m in enumerate(cdata["metadatas"]):
        if m["paper_id"] in fixed_map:
            p = by_id[m["paper_id"]]
            nm = dict(m)
            nm["title"] = (p["title"] or "")[:200]
            for k, v in list(nm.items()):
                if v is None:
                    nm[k] = ""
            new_doc = (
                f"标题: {p['title'] or ''}\n"
                f"主题: {p['category'] or ''}\n"
                f"年份: {p['year'] or 0}\n"
                f"摘要: {p['abstract'] or ''}"
            )
            ids_upd.append(cdata["ids"][i])
            mds_upd.append(nm)
            docs_upd.append(new_doc)
    print(f"papers_cards 待改: {len(ids_upd)}")
    for s in range(0, len(ids_upd), 200):
        e = min(s + 200, len(ids_upd))
        cards.update(ids=ids_upd[s:e], metadatas=mds_upd[s:e], documents=docs_upd[s:e])

    print("\nDONE")


if __name__ == "__main__":
    main()
