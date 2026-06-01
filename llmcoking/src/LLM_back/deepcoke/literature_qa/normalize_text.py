"""
NFKC 归一化:把 PDF 抽取留下的连字(ﬁ/ﬂ/ﬀ/ﬃ/ﬄ)和全角字符等
统一展开成标准字符,避免前端显示方框。

清洗范围:
- papers.db.papers 表的 title / authors / abstract / journal
- ChromaDB coking_papers collection 的 chunk metadata.title / authors / documents
- ChromaDB papers_cards collection 的 metadata + documents

跑完即可,新加文献也会经此清洗一次。

Usage:
    cd D:\\deepcoke\\deepcoke_edu\\llmcoking\\src\\LLM_back
    python -X utf8 -u -m deepcoke.literature_qa.normalize_text
"""
import sqlite3
import time
import unicodedata

import chromadb

from deepcoke import config

CARDS_COLLECTION = "papers_cards"


import re as _re
_CTRL_RE = _re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def normalize(s: str | None) -> str:
    if not s:
        return s or ""
    # NFKC: 连字 ﬁ→fi、全角 →半角、上下标→普通等
    out = unicodedata.normalize("NFKC", s)
    # 顺手清几个 PDF 常见垃圾(NFKC 不动的)
    out = out.replace("­", "")          # soft hyphen 不可见连字符
    out = out.replace("​", "")          # zero-width space
    out = out.replace("﻿", "")          # BOM
    # ASCII 控制字符(除 \t \n \r) → 空格,避免渲染成方框 + 相邻 token 粘连
    out = _CTRL_RE.sub(" ", out)
    # 合并多余空格
    out = _re.sub(r" {2,}", " ", out)
    return out


def main():
    db_path = config.DATA_DIR / "papers.db"
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row

    # 1. papers.db
    print("[1/3] 归一化 papers.db ...")
    rows = list(db.execute("SELECT id, title, authors, abstract, journal FROM papers"))
    changed = 0
    for r in rows:
        new_t = normalize(r["title"])
        new_a = normalize(r["authors"])
        new_ab = normalize(r["abstract"])
        new_j = normalize(r["journal"])
        if (new_t, new_a, new_ab, new_j) != (r["title"], r["authors"], r["abstract"], r["journal"]):
            db.execute(
                "UPDATE papers SET title=?, authors=?, abstract=?, journal=? WHERE id=?",
                (new_t, new_a, new_ab, new_j, r["id"]),
            )
            changed += 1
    db.commit()
    print(f"  改了 {changed} / {len(rows)} 行")

    # 2. ChromaDB coking_papers (chunk metadata + documents)
    print("[2/3] 归一化 ChromaDB coking_papers ...")
    client = chromadb.PersistentClient(path=str(config.CHROMADB_DIR))
    col = client.get_collection(config.CHROMADB_COLLECTION)
    data = col.get(include=["documents", "metadatas"])
    ids_upd, mds_upd, docs_upd = [], [], []
    t0 = time.time()
    for i, m in enumerate(data["metadatas"]):
        old_doc = data["documents"][i]
        nm = dict(m)
        nm["title"] = normalize(m.get("title", ""))
        nm["authors"] = normalize(m.get("authors", ""))
        for k, v in list(nm.items()):
            if v is None:
                nm[k] = ""
        new_doc = normalize(old_doc)
        if nm != m or new_doc != old_doc:
            ids_upd.append(data["ids"][i])
            mds_upd.append(nm)
            docs_upd.append(new_doc)
    print(f"  待改 {len(ids_upd)} / {len(data['ids'])} chunks")
    BATCH = 1000
    for s in range(0, len(ids_upd), BATCH):
        e = min(s + BATCH, len(ids_upd))
        col.update(ids=ids_upd[s:e], metadatas=mds_upd[s:e], documents=docs_upd[s:e])
        print(f"  update {e}/{len(ids_upd)}")
    print(f"  耗时 {time.time()-t0:.1f}s")

    # 3. ChromaDB papers_cards
    print("[3/3] 归一化 ChromaDB papers_cards ...")
    cards = client.get_collection(CARDS_COLLECTION)
    cdata = cards.get(include=["documents", "metadatas"])
    ids_upd, mds_upd, docs_upd = [], [], []
    for i, m in enumerate(cdata["metadatas"]):
        old_doc = cdata["documents"][i]
        nm = dict(m)
        nm["title"] = normalize(m.get("title", ""))
        nm["authors"] = normalize(m.get("authors", ""))
        nm["journal"] = normalize(m.get("journal", ""))
        for k, v in list(nm.items()):
            if v is None:
                nm[k] = ""
        new_doc = normalize(old_doc)
        if nm != m or new_doc != old_doc:
            ids_upd.append(cdata["ids"][i])
            mds_upd.append(nm)
            docs_upd.append(new_doc)
    print(f"  待改 {len(ids_upd)} / {len(cdata['ids'])} cards")
    for s in range(0, len(ids_upd), 200):
        e = min(s + 200, len(ids_upd))
        cards.update(ids=ids_upd[s:e], metadatas=mds_upd[s:e], documents=docs_upd[s:e])

    print("\nDONE")


if __name__ == "__main__":
    main()
