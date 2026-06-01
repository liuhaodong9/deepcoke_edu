"""
从每篇文献的 Preamble chunk 提取 journal/authors/year,补全 papers.db 现有数据,
然后同步到 papers_cards collection 的 metadata(不重新 embedding)。

一次性脚本,跑完即可。后续加新文献单独跑同一脚本(只动 journal 为空的行)。

Usage:
    cd D:\\deepcoke\\deepcoke_edu\\llmcoking\\src\\LLM_back
    python -X utf8 -u -m deepcoke.literature_qa.enrich_metadata
"""
import json
import re
import sqlite3
import sys
import time
from collections import defaultdict

import chromadb

from deepcoke import config, llm_client
from deepcoke.vectorstore.chromadb_store import get_chroma_client

CARDS_COLLECTION = "papers_cards"

PROMPT = """从下列学术论文开头部分提取 metadata,严格输出 JSON 对象(不要 markdown 包裹,不要解释):
{
  "journal": "期刊或会议或报告系列的名称(如 Energy & Fuels / Fuel / Prog Energy Combust Sci / ACARP report 等;若是学位论文写 'PhD Thesis';若无明确出处用空字符串)",
  "authors": ["First Author", "Second Author"],
  "year": 1992
}

只输出 JSON。若某字段无法确认,journal 用空串,authors 用空数组,year 用 null。

文本:
"""


def parse_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    # 容错:截取第一个 { ... 最后一个 }
    s, e = raw.find("{"), raw.rfind("}")
    if s >= 0 and e > s:
        raw = raw[s:e + 1]
    return json.loads(raw)


def collect_preamble_text(col, paper_id: int) -> str:
    """取该 paper 的前 2 个 chunk 文本拼起来,优先 chunk_index 小的。"""
    data = col.get(where={"paper_id": paper_id}, include=["documents", "metadatas"])
    items = list(zip(data["ids"], data["documents"], data["metadatas"]))
    items.sort(key=lambda x: x[2].get("chunk_index", 0))
    text = "\n".join(d for _, d, _ in items[:2])
    return text[:3500]


def authors_to_str(authors) -> str:
    """统一 authors 字段为字符串(LLM 输出可能是 list/string,papers.db 存字符串)。"""
    if not authors:
        return ""
    if isinstance(authors, str):
        s = authors.strip()
        # 已经像 "['A', 'B']" 这种垃圾的话,清洗
        if s in ("[]", "['']", "[\"\"]"):
            return ""
        return s
    if isinstance(authors, list):
        return ", ".join(str(a).strip() for a in authors if str(a).strip())
    return str(authors)


def main():
    db_path = config.DATA_DIR / "papers.db"
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row

    # 1. 加 journal 列(若不存在)
    cols = [r[1] for r in db.execute("PRAGMA table_info(papers)").fetchall()]
    if "journal" not in cols:
        db.execute("ALTER TABLE papers ADD COLUMN journal TEXT DEFAULT ''")
        db.commit()
        print("[ALTER] 加 journal 列")
    else:
        print("[ALTER] journal 列已存在")

    print("[1/3] 加载 ChromaDB ...")
    client = get_chroma_client()
    col = client.get_collection(config.CHROMADB_COLLECTION)
    print(f"  chunks: {col.count()}")

    print("[2/3] LLM 提取 journal/authors/year ...")
    papers = list(db.execute(
        "SELECT id, title, authors, year, journal FROM papers ORDER BY id"
    ))
    n_ok = 0
    n_skip = 0
    n_fail = 0
    t0 = time.time()
    for i, p in enumerate(papers, 1):
        pid = p["id"]
        existing_journal = (p["journal"] or "").strip()
        if existing_journal:
            n_skip += 1
            continue

        text = collect_preamble_text(col, pid)
        if not text:
            n_skip += 1
            print(f"  [{i}/{len(papers)}] id={pid} 无 chunk,跳过")
            continue

        t_start = time.time()
        try:
            raw = llm_client.chat_json(
                [{"role": "user", "content": PROMPT + text}],
                temperature=0.0,
            )
            data = parse_json(raw)
        except Exception as e:
            n_fail += 1
            print(f"  [{i}/{len(papers)}] id={pid} 失败: {e}")
            continue

        journal = (data.get("journal") or "").strip()[:200]
        authors_new = authors_to_str(data.get("authors"))
        year_new = data.get("year")

        # 只在原值缺失时覆盖,避免覆盖已有较好数据
        existing_authors = (p["authors"] or "").strip()
        if existing_authors in ("", "[]", "['']", '[""]'):
            new_authors = authors_new
        else:
            new_authors = existing_authors
        new_year = p["year"] if p["year"] else (year_new if isinstance(year_new, int) else None)

        db.execute(
            "UPDATE papers SET journal=?, authors=?, year=? WHERE id=?",
            (journal, new_authors, new_year, pid),
        )
        db.commit()
        n_ok += 1
        title_short = (p["title"] or "")[:40]
        print(f"  [{i}/{len(papers)}] {time.time()-t_start:.1f}s  id={pid}  journal={journal[:30]!r}  {title_short}")

    print(f"\n  共: ok={n_ok} skip={n_skip} fail={n_fail}  耗时 {time.time()-t0:.0f}s")

    print("[3/3] 同步 metadata 到 papers_cards collection ...")
    cards = client.get_collection(CARDS_COLLECTION)
    cards_data = cards.get(include=["metadatas"])
    print(f"  cards 当前: {len(cards_data['ids'])} 篇")

    # 重新读 papers.db 拿最新完整数据
    by_id = {
        r["id"]: dict(r)
        for r in db.execute("SELECT id, title, authors, year, category, journal FROM papers")
    }
    ids_update = []
    mds_update = []
    for i, m in enumerate(cards_data["metadatas"]):
        pid = m["paper_id"]
        p = by_id.get(pid)
        if not p:
            continue
        nm = dict(m)
        nm["title"] = (p["title"] or "")[:200]
        nm["authors"] = (p["authors"] or "")[:300]
        nm["year"] = int(p["year"]) if p["year"] else 0
        nm["category"] = p["category"] or ""
        nm["journal"] = (p["journal"] or "")[:200]
        for k, v in list(nm.items()):
            if v is None:
                nm[k] = ""
        ids_update.append(cards_data["ids"][i])
        mds_update.append(nm)
    BATCH = 200
    for s in range(0, len(ids_update), BATCH):
        e = min(s + BATCH, len(ids_update))
        cards.update(ids=ids_update[s:e], metadatas=mds_update[s:e])
        print(f"  update {e}/{len(ids_update)}")

    print(f"\nDONE  papers_cards.count() = {cards.count()}")


if __name__ == "__main__":
    main()
