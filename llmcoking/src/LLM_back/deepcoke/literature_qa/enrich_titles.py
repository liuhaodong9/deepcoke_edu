"""
用 qwen3:8b 重新提取那些"看着不像论文标题"的 title。

fast_ingest.py 当前的 quick_extract_metadata 取 PDF 前 10 行第一个长度 > 15 的
非空行作为 title — 对正常排版的论文 OK,但碰到 ACARP 报告、ScienceDirect 页眉、
中文期刊"文章编号..."、合集名、Research article 之类的元信息就抓垃圾。

策略:
1. 用 regex/长度规则筛出可疑 title (~22%)
2. 给 LLM 看每篇前 2 个 chunk,要求严格 JSON 输出真实 title
3. 写回 papers.db,同步 ChromaDB chunk metadata 和 papers_cards

跑完即可。新加文献也建议 ingest 后跑一遍。

Usage:
    cd D:\\deepcoke\\deepcoke_edu\\llmcoking\\src\\LLM_back
    python -X utf8 -u -m deepcoke.literature_qa.enrich_titles
"""
import json
import re
import sqlite3
import time

import chromadb

from deepcoke import config, llm_client
from deepcoke.vectorstore.chromadb_store import get_chroma_client

CARDS_COLLECTION = "papers_cards"

# 启发式判定 title 可疑
_SUSPECT_RE = re.compile(
    r"^(ACARP|Final Report|Mining Report|Contributing Authors|JOURNAL OF|"
    r"Energy & Fuels\s*\d|Fuel\s+\d|Vol\.|Volume\s|Contents|Editor|Foreword|"
    r"Preface|Chapter|Page|Abstract:|文章编号|作者:|关键词|©|Copyright|"
    r"Coal Research|Australian Coal|Industries.*Program|Improved\s|"
    r"Final\s|Project\s*[Cc]\d|Contents lists|Research article|"
    r"Short Communication|Full Length Article|Petroleum & Coal|"
    r"Energy\s+\d+\s*\()",
    re.IGNORECASE,
)


def is_suspect(title: str | None) -> bool:
    if not title:
        return True
    if len(title) <= 25:
        return True
    if _SUSPECT_RE.match(title.strip()):
        return True
    return False


PROMPT = """下面是某篇煤化工/焦化领域学术论文/技术报告的开头部分。请提取**真正的论文标题**,不是页眉、期刊名、文章编号、出版社、卷期号、栏目类型。

严格输出 JSON,不要 markdown 包裹,不要其他文字:
{
  "title": "真正的论文标题(英文或中文,保持原始大小写)",
  "confidence": "high|medium|low"
}

判断要点:
- 如果文本以 ACARP/Final Report/Mining Report 起头,真正标题往往在第二、三行
- "Contents lists available at ScienceDirect" 之后才是标题
- 中文期刊先有"文章编号: xxx",再是标题
- "Research article"/"Short Communication"/"Full Length Article" 是栏目,后面才是标题
- 期刊名+卷期号(如 "Energy 27 (2002) 405-414")之后才是标题
- 若文本太碎实在判断不出,confidence 用 low,title 给最像的那行

文本:
"""


def fetch_preamble(col, paper_id: int) -> str:
    data = col.get(where={"paper_id": paper_id}, include=["documents", "metadatas"])
    items = list(zip(data["documents"], data["metadatas"]))
    items.sort(key=lambda x: x[1].get("chunk_index", 0))
    text = "\n".join(d for d, _ in items[:2])
    return text[:2500]


def parse_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    s, e = raw.find("{"), raw.rfind("}")
    if s >= 0 and e > s:
        raw = raw[s:e + 1]
    return json.loads(raw)


def main():
    db_path = config.DATA_DIR / "papers.db"
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row

    print("[1/4] 加载 ChromaDB ...")
    client = get_chroma_client()
    col = client.get_collection(config.CHROMADB_COLLECTION)

    print("[2/4] 筛可疑 title ...")
    rows = list(db.execute("SELECT id, title FROM papers ORDER BY id"))
    targets = [(r["id"], r["title"]) for r in rows if is_suspect(r["title"])]
    print(f"  papers 总数: {len(rows)}  可疑: {len(targets)}")

    print("[3/4] LLM 重提取 ...")
    fixed = {}  # paper_id → new title
    t0 = time.time()
    for i, (pid, old) in enumerate(targets, 1):
        text = fetch_preamble(col, pid)
        if not text:
            continue
        try:
            ts = time.time()
            raw = llm_client.chat_json(
                [{"role": "user", "content": PROMPT + text}],
                temperature=0.0,
            )
            data = parse_json(raw)
            new_title = (data.get("title") or "").strip()[:300]
            conf = data.get("confidence", "")
            if new_title and new_title.lower() != (old or "").lower():
                fixed[pid] = new_title
            print(f"  [{i}/{len(targets)}] {time.time()-ts:.1f}s conf={conf:6s} id={pid}")
            print(f"      OLD: {(old or '')[:80]}")
            print(f"      NEW: {new_title[:80]}")
        except Exception as e:
            print(f"  [{i}/{len(targets)}] id={pid} 失败: {e}")
    print(f"\n  实际更新: {len(fixed)} 篇,耗时 {time.time()-t0:.0f}s")

    # 写回 papers.db
    for pid, t in fixed.items():
        db.execute("UPDATE papers SET title = ? WHERE id = ?", (t, pid))
    db.commit()

    # 同步 ChromaDB coking_papers chunks
    print("[4/4] 同步 ChromaDB ...")
    data = col.get(include=["metadatas"])
    ids_upd, mds_upd = [], []
    for i, m in enumerate(data["metadatas"]):
        if m["paper_id"] in fixed:
            nm = dict(m)
            nm["title"] = fixed[m["paper_id"]][:200]
            for k, v in list(nm.items()):
                if v is None:
                    nm[k] = ""
            ids_upd.append(data["ids"][i])
            mds_upd.append(nm)
    print(f"  coking_papers 待改 chunks: {len(ids_upd)}")
    for s in range(0, len(ids_upd), 1000):
        e = min(s + 1000, len(ids_upd))
        col.update(ids=ids_upd[s:e], metadatas=mds_upd[s:e])

    # 同步 papers_cards
    cards = client.get_collection(CARDS_COLLECTION)
    cdata = cards.get(include=["metadatas", "documents"])
    ids_upd, mds_upd, docs_upd = [], [], []
    by_id = {r["id"]: dict(r) for r in db.execute("SELECT id, title, authors, year, category, journal, abstract FROM papers")}
    for i, m in enumerate(cdata["metadatas"]):
        if m["paper_id"] in fixed:
            p = by_id[m["paper_id"]]
            nm = dict(m)
            nm["title"] = (p["title"] or "")[:200]
            for k, v in list(nm.items()):
                if v is None:
                    nm[k] = ""
            new_doc = f"标题: {p['title'] or ''}\n主题: {p['category'] or ''}\n年份: {p['year'] or 0}\n摘要: {p['abstract'] or ''}"
            ids_upd.append(cdata["ids"][i])
            mds_upd.append(nm)
            docs_upd.append(new_doc)
    print(f"  papers_cards 待改: {len(ids_upd)}")
    for s in range(0, len(ids_upd), 200):
        e = min(s + 200, len(ids_upd))
        cards.update(ids=ids_upd[s:e], metadatas=mds_upd[s:e], documents=docs_upd[s:e])

    print("\nDONE")


if __name__ == "__main__":
    main()
