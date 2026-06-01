"""
为每篇文献生成 abstract（优先用 PDF 自带的 Abstract 段;否则 LLM 总结前几段）,
然后把 (title + authors + year + category + abstract) 写到新的 papers_cards collection。

一次性脚本,跑完即可。后续加文献只对增量重跑。

Usage:
    cd D:\\deepcoke\\deepcoke_edu\\llmcoking\\src\\LLM_back
    python -X utf8 -m deepcoke.literature_qa.build_cards
"""
import sqlite3
import sys
import time
from collections import defaultdict

import chromadb

from deepcoke import config, llm_client
from deepcoke.vectorstore.chromadb_store import get_chroma_client, _get_embedding_function

CARDS_COLLECTION = "papers_cards"
ABSTRACT_MAX_CHARS = 1200  # 写入 papers.db 的上限
SUMMARY_PROMPT = (
    "下面是一篇焦化/煤炭领域学术论文的开头段落。请用中文写 80-150 字的总结,"
    "覆盖:研究对象、关键方法、主要结论。不要写'本文'/'本研究'之类的套话,直接陈述。"
    "只输出总结正文,不要前缀。\n\n论文片段:\n{text}\n\n总结:"
)


def collect_chunks_by_paper(col) -> dict[int, list[dict]]:
    """读全部 chunk,按 paper_id 分组。"""
    data = col.get(include=["documents", "metadatas"])
    by_paper = defaultdict(list)
    for i in range(len(data["ids"])):
        m = data["metadatas"][i]
        by_paper[m["paper_id"]].append({
            "id": data["ids"][i],
            "doc": data["documents"][i],
            "section": m.get("section", ""),
            "chunk_index": m.get("chunk_index", 0),
        })
    for pid in by_paper:
        by_paper[pid].sort(key=lambda x: x["chunk_index"])
    return by_paper


def extract_native_abstract(chunks: list[dict]) -> str | None:
    """从 chunk 列表里找标记为 abstract 的段(忽略大小写)。"""
    parts = []
    for c in chunks:
        if "abstract" in c["section"].lower():
            parts.append(c["doc"].strip())
    if not parts:
        return None
    abs_text = "\n".join(parts).strip()
    return abs_text[:ABSTRACT_MAX_CHARS]


def llm_summarize(chunks: list[dict]) -> str:
    """qwen3:8b 总结前几段。跳过 preamble/acknowledgements/references。"""
    skip_kw = ("preamble", "acknowledg", "references", "reference")
    body = [c for c in chunks if not any(k in c["section"].lower() for k in skip_kw)]
    body = body or chunks
    # 取前 3 个块,合并到 ~3000 字
    buf = []
    used = 0
    for c in body[:6]:
        t = c["doc"].strip()
        if used + len(t) > 3000:
            buf.append(t[: 3000 - used])
            break
        buf.append(t)
        used += len(t)
    text = "\n".join(buf)
    if not text:
        return ""
    msgs = [{"role": "user", "content": SUMMARY_PROMPT.format(text=text)}]
    try:
        return llm_client.chat_json(msgs).strip()[:ABSTRACT_MAX_CHARS]
    except Exception as e:
        print(f"  [LLM 失败,跳过] {e}")
        return ""


def main():
    db_path = config.DATA_DIR / "papers.db"
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row

    print("[1/4] 加载 ChromaDB ...")
    client = get_chroma_client()
    src_col = client.get_collection(config.CHROMADB_COLLECTION)
    print(f"  source collection: {src_col.count()} chunks")

    print("[2/4] 收集每篇文献的 chunk ...")
    by_paper = collect_chunks_by_paper(src_col)
    print(f"  papers with chunks: {len(by_paper)}")

    print("[3/4] 生成 abstract 并写回 papers.db ...")
    papers = list(db.execute(
        "SELECT id, title, authors, year, category, abstract FROM papers ORDER BY id"
    ))
    n_native = 0
    n_llm = 0
    n_skip = 0
    t_total = time.time()
    for i, row in enumerate(papers, 1):
        pid = row["id"]
        existing_abs = row["abstract"] or ""
        if existing_abs and len(existing_abs) > 60:
            n_skip += 1
            continue
        chunks = by_paper.get(pid, [])
        if not chunks:
            print(f"  [{i}/{len(papers)}] (id={pid}) 无 chunk,跳过")
            continue

        native = extract_native_abstract(chunks)
        if native and len(native) > 100:
            abs_text = native
            n_native += 1
            tag = "Abstract段"
        else:
            t0 = time.time()
            abs_text = llm_summarize(chunks)
            if not abs_text:
                n_skip += 1
                continue
            n_llm += 1
            tag = f"LLM {time.time()-t0:.1f}s"

        db.execute("UPDATE papers SET abstract=? WHERE id=?", (abs_text, pid))
        db.commit()
        title = (row["title"] or "")[:50]
        print(f"  [{i}/{len(papers)}] {tag}  id={pid}  {title}")

    print(f"\n  共: native={n_native} llm={n_llm} skip={n_skip}  耗时 {time.time()-t_total:.0f}s")

    print("[4/4] 建/重建 papers_cards collection ...")
    existing_names = [c.name for c in client.list_collections()]
    if CARDS_COLLECTION in existing_names:
        client.delete_collection(CARDS_COLLECTION)
        print(f"  drop 旧 {CARDS_COLLECTION}")

    ef = _get_embedding_function()
    kwargs = {"name": CARDS_COLLECTION, "metadata": {"hnsw:space": "cosine"}}
    if ef is not None:
        kwargs["embedding_function"] = ef
    cards = client.create_collection(**kwargs)

    ids, docs, mds = [], [], []
    papers = list(db.execute(
        "SELECT id, title, authors, year, category, abstract FROM papers ORDER BY id"
    ))
    for row in papers:
        abs_text = (row["abstract"] or "").strip()
        if not abs_text:
            continue
        title = row["title"] or ""
        authors = row["authors"] or ""
        year = row["year"] or 0
        category = row["category"] or ""
        # 检索时用的文档:标题+主题+摘要拼起来,让 BGE 一并 embed
        doc = f"标题: {title}\n主题: {category}\n年份: {year}\n摘要: {abs_text}"
        ids.append(f"paper_{row['id']}")
        docs.append(doc)
        mds.append({
            "paper_id": row["id"],
            "title": title[:200],
            "authors": authors[:300],
            "year": int(year) if year else 0,
            "category": category,
        })

    print(f"  入卡片库: {len(ids)} 篇")
    BATCH = 200
    for s in range(0, len(ids), BATCH):
        e = min(s + BATCH, len(ids))
        cards.upsert(ids=ids[s:e], documents=docs[s:e], metadatas=mds[s:e])
        print(f"    upsert {e}/{len(ids)}")

    print(f"\nDONE  papers_cards.count() = {cards.count()}")


if __name__ == "__main__":
    main()
