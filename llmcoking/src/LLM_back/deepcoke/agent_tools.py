"""
RAG Agent Tools — 提供给 LLM 自主调用的检索工具集

设计哲学(PaperQA2 / NotebookLM 风格):
1. find_relevant_papers — 论文级检索(不是 chunk 级),投票出 top-N 候选论文
2. read_paper_fulltext — 读论文(几乎)全文(从 chunks 拼回),~13K tokens/篇
3. read_paper_section — 只读某章节(节省 context)
4. finalize_answer — LLM 觉得够了,停止检索

典型工作流:
  问题 → find_relevant_papers(top_n=3) → 看候选标题/abstract
       → read_paper_fulltext(paper_id_1) → 全文塞进 prompt
       → (可选)read_paper_fulltext(paper_id_2) → 第二篇全文
       → finalize_answer → 生成基于全文的回答

32K context 限制:典型 2 篇全文 ≈ 26K tokens + 系统提示 + 问题 + 回答 ~32K 刚好
"""
import json
import logging
from collections import defaultdict
from .vectorstore.retriever import retrieve, RetrievedChunk
from .vectorstore.chromadb_store import get_collection

logger = logging.getLogger("deepcoke.agent_tools")

# Token 预算配置
MAX_FULLTEXT_CHARS = 40000       # 单篇全文最多塞这么多字符 (~10K tokens)
MAX_SECTION_CHARS = 12000        # 单章节最多 (~3K tokens)
PAPER_VOTE_TOP_CHUNKS = 30       # 论文级检索时先取这么多 chunks 来投票
SKIP_SECTIONS_FOR_FULLTEXT = {   # 读全文时默认跳过这些(往往噪声)
    "references", "reference", "bibliography",
    "acknowledgments", "acknowledgements",
    "author contributions", "competing interests",
    "supplementary", "supplementary material",
}


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_paper_summary",
            "description": (
                "读某篇论文的预生成结构化深度摘要(~1000 字),包含 研究问题/方法/主要发现(含定量数据)/参数条件/局限/与主线关系。"
                "**强烈推荐:这是首选信息源**,因为是离线 LLM 精读全文后写的。"
                "大多数问题用 1-2 篇 summary 就够回答。"
                "如果 summary 缺关键细节(具体公式/原始数据表格等),再用 read_paper_fulltext。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "paper_id": {"type": "integer", "description": "论文 id"},
                },
                "required": ["paper_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_relevant_papers",
            "description": (
                "论文级检索:用 English query 从 6017 个 chunk 中投票,选出最相关的 N 篇论文。"
                "返回每篇的 paper_id / title / authors / year / abstract / 相关 chunk 数 / 最高 score。"
                "这是首选工具:先找到候选论文,再决定要读哪几篇。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "English search query",
                    },
                    "top_n": {
                        "type": "integer",
                        "default": 3,
                        "description": "返回前几篇论文,推荐 3-5,最多 8",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_paper_fulltext",
            "description": (
                "读某篇论文的(近似)全文 — 把这篇 paper 在 ChromaDB 的所有 chunks 按章节顺序拼回。"
                "自动跳过 References / Acknowledgments 等噪声章节。单篇上限约 10K tokens。"
                "用于:确认这篇 paper 相关后,深入读全文以回答问题。"
                "⚠️ 一次只读 1-2 篇,否则会超 32K context。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "paper_id": {"type": "integer", "description": "论文 id"},
                },
                "required": ["paper_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_paper_section",
            "description": (
                "只读论文的某个章节(Methods/Results/Discussion 等),省 context。"
                "用于:全文太长但只关心某部分时。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "paper_id": {"type": "integer", "description": "论文 id"},
                    "section": {
                        "type": "string",
                        "description": "章节名,如 'Methods' / 'Results' / 'Discussion' / 'Abstract'",
                    },
                },
                "required": ["paper_id", "section"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finalize_answer",
            "description": (
                "已经读够论文了,可以回答问题。调用此工具会停止检索,把所有已读 paper 全文交给生成节点。"
                "rationale 说明:已经从哪几篇论文获取了什么信息,覆盖了问题的哪些方面。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "rationale": {
                        "type": "string",
                        "description": "为什么现在可以回答了(信息覆盖情况)",
                    },
                },
                "required": ["rationale"],
            },
        },
    },
]


def _vote_papers_from_chunks(chunks: list[RetrievedChunk], top_n: int) -> list[int]:
    """从 chunk 检索结果按 paper_id 投票,返回 top_n 篇论文的 id。
    投票规则:max_score(主) + chunk_count(辅)。"""
    score_table: dict[int, dict] = {}
    for c in chunks:
        if c.paper_id is None or c.paper_id == 0:
            continue
        entry = score_table.setdefault(c.paper_id, {"max": 0.0, "sum": 0.0, "count": 0})
        entry["max"] = max(entry["max"], float(c.score))
        entry["sum"] += float(c.score)
        entry["count"] += 1

    ranked = sorted(
        score_table.items(),
        key=lambda x: (x[1]["max"], x[1]["count"], x[1]["sum"]),
        reverse=True,
    )
    return [pid for pid, _ in ranked[:top_n]]


def _get_paper_meta(paper_id: int) -> dict:
    """从 ChromaDB 拿 paper 的元数据(题目/作者/年份/abstract)。"""
    coll = get_collection()
    raw = coll.get(where={"paper_id": int(paper_id)}, limit=50)
    if not raw or not raw.get("ids"):
        return {"paper_id": paper_id, "error": "not found"}

    title = authors = category = keywords = ""
    year = 0
    abstract_chunks: list[tuple[int, str]] = []

    for i, meta in enumerate(raw["metadatas"]):
        if not title and meta.get("title"):
            title = meta.get("title", "")
        if not authors and meta.get("authors"):
            authors = meta.get("authors", "")
        if not year and meta.get("year"):
            year = meta.get("year", 0)
        if not category and meta.get("category"):
            category = meta.get("category", "")
        if not keywords and meta.get("keywords"):
            keywords = meta.get("keywords", "")
        sec = (meta.get("section") or "").lower()
        if "abstract" in sec or "summary" in sec:
            abstract_chunks.append((meta.get("chunk_index", 0), raw["documents"][i]))

    abstract_chunks.sort()
    abstract = abstract_chunks[0][1][:1200] if abstract_chunks else ""

    return {
        "paper_id": paper_id,
        "title": title,
        "authors": authors,
        "year": year,
        "category": category,
        "keywords": keywords,
        "abstract": abstract,
        "total_chunks": len(raw["ids"]),
    }


def tool_find_relevant_papers(query: str, top_n: int = 3) -> dict:
    """Tool 1: 论文级检索 — 找 top-N 篇候选论文。"""
    top_n = max(1, min(int(top_n), 8))

    chunks = retrieve(query, top_k=PAPER_VOTE_TOP_CHUNKS)
    paper_ids = _vote_papers_from_chunks(chunks, top_n)

    papers = []
    for pid in paper_ids:
        meta = _get_paper_meta(pid)
        if "error" in meta:
            continue
        relevant_chunks = [c for c in chunks if c.paper_id == pid]
        papers.append({
            "paper_id": pid,
            "title": meta["title"][:200],
            "authors": meta["authors"][:200],
            "year": meta["year"],
            "category": meta["category"],
            "abstract": meta["abstract"],
            "total_chunks": meta["total_chunks"],
            "hit_chunks": len(relevant_chunks),
            "max_score": round(max((c.score for c in relevant_chunks), default=0.0), 3),
        })

    logger.info(f"[tool:find_papers] query={query[:40]!r} → {len(papers)} papers")
    return {"query": query, "papers": papers}


def tool_read_paper_fulltext(paper_id: int) -> dict:
    """Tool 2: 读论文(近似)全文 — 拼接所有非噪声章节的 chunks。"""
    coll = get_collection()
    raw = coll.get(where={"paper_id": int(paper_id)}, limit=200)
    if not raw or not raw.get("ids"):
        return {"paper_id": paper_id, "error": "not found", "fulltext": ""}

    title = ""
    section_groups: dict[str, list[tuple[int, str]]] = defaultdict(list)
    section_order: list[str] = []

    for i, meta in enumerate(raw["metadatas"]):
        if not title and meta.get("title"):
            title = meta.get("title", "")
        section = (meta.get("section") or "Body").strip()
        if section.lower() in SKIP_SECTIONS_FOR_FULLTEXT:
            continue
        if section not in section_order:
            section_order.append(section)
        section_groups[section].append((
            meta.get("chunk_index", 0),
            raw["documents"][i],
        ))

    parts = []
    total_chars = 0
    truncated = False
    for section in section_order:
        chunks_sorted = sorted(section_groups[section])
        section_text = "\n\n".join(t for _, t in chunks_sorted)
        if total_chars + len(section_text) > MAX_FULLTEXT_CHARS:
            remaining = MAX_FULLTEXT_CHARS - total_chars
            if remaining > 200:
                section_text = section_text[:remaining] + "\n... [章节截断]"
                parts.append(f"## {section}\n{section_text}")
                total_chars += len(section_text)
            truncated = True
            break
        parts.append(f"## {section}\n{section_text}")
        total_chars += len(section_text)

    fulltext = f"# {title}\n\n" + "\n\n".join(parts)

    logger.info(
        f"[tool:read_fulltext] paper_id={paper_id} sections={len(section_order)} "
        f"chars={len(fulltext)} truncated={truncated}"
    )
    return {
        "paper_id": paper_id,
        "title": title,
        "fulltext": fulltext,
        "sections": section_order,
        "char_count": len(fulltext),
        "truncated": truncated,
    }


# 章节名规范化:用户传 "Methods" 应该匹配 "Method" / "2. Methods" / "Methodology" 等
_SECTION_ALIASES = {
    "method": {"method", "methods", "methodology", "experimental", "materials and methods"},
    "result": {"result", "results", "findings", "results and discussion"},
    "discussion": {"discussion", "results and discussion", "discussions"},
    "introduction": {"introduction", "intro", "background"},
    "conclusion": {"conclusion", "conclusions", "summary", "concluding remarks"},
    "abstract": {"abstract", "summary"},
}


def _section_matches(actual: str, want: str) -> bool:
    """Fuzzy 章节匹配:want='Methods' 匹配 actual='Method'/'2. Methods'/'Materials and Methods'。"""
    a = (actual or "").lower().strip()
    w = (want or "").lower().strip()
    if not a or not w:
        return False
    # 去掉数字前缀(如 "2. Experimental" → "experimental")
    import re as _re
    a_clean = _re.sub(r"^\d+\.\s*", "", a).strip()
    w_clean = _re.sub(r"^\d+\.\s*", "", w).strip()

    if a_clean == w_clean:
        return True
    # 直接包含关系
    if w_clean in a_clean or a_clean in w_clean:
        return True
    # 别名匹配
    for canon, aliases in _SECTION_ALIASES.items():
        if w_clean in aliases or w_clean == canon:
            if a_clean in aliases or a_clean == canon:
                return True
    return False


def tool_read_paper_section(paper_id: int, section: str) -> dict:
    """Tool 3: 只读某章节(节省 context)。用 fuzzy section name 匹配。"""
    coll = get_collection()
    # 先拿整篇的所有 chunks,Python 端 fuzzy 过滤(ChromaDB where 不支持 LIKE)
    raw = coll.get(where={"paper_id": int(paper_id)}, limit=200)
    if not raw or not raw.get("ids"):
        return {
            "paper_id": paper_id,
            "section": section,
            "text": "",
            "error": "paper not found",
        }

    matching = []
    available_sections = set()
    for i, meta in enumerate(raw["metadatas"]):
        sec = meta.get("section") or ""
        available_sections.add(sec)
        if _section_matches(sec, section):
            matching.append((meta.get("chunk_index", 0), sec, raw["documents"][i]))

    if not matching:
        return {
            "paper_id": paper_id,
            "section": section,
            "text": "",
            "available_sections": sorted(available_sections),
            "error": f"section '{section}' not found; try one of: {sorted(available_sections)[:10]}",
        }

    matching.sort()
    matched_section = matching[0][1]  # 第一个匹配到的章节实际名
    text = "\n\n".join(t for _, _, t in matching)
    truncated = False
    if len(text) > MAX_SECTION_CHARS:
        text = text[:MAX_SECTION_CHARS] + "\n... [截断]"
        truncated = True

    logger.info(
        f"[tool:read_section] paper_id={paper_id} want={section!r} matched={matched_section!r} "
        f"chars={len(text)} truncated={truncated}"
    )
    return {
        "paper_id": paper_id,
        "section_requested": section,
        "section_matched": matched_section,
        "text": text,
        "char_count": len(text),
        "truncated": truncated,
    }


def tool_read_paper_summary(paper_id: int) -> dict:
    """Tool 0(首选): 读预生成的结构化深度摘要(~1000字)。比读全文快 30 倍。
    返回:
      - summary: 带 [#N] 引用标记的摘要文本
      - summary_chunks: [{chunk_index, section, text_preview}] 列表
                       前端按 [#N] 反查原文段落用
    自动 fallback: deep_summary 列不存在 → 用 abstract"""
    import sqlite3
    import json as _json
    from . import config as _cfg
    db_path = _cfg.DATA_DIR / "papers.db"

    deep_summary = None
    deep_summary_chunks_json = None
    abstract = None
    title = ""
    try:
        conn = sqlite3.connect(str(db_path))
        cols = [r[1] for r in conn.execute("PRAGMA table_info(papers)").fetchall()]
        has_deep = "deep_summary" in cols
        has_chunks = "deep_summary_chunks" in cols

        if has_deep and has_chunks:
            row = conn.execute(
                "SELECT title, deep_summary, deep_summary_chunks, abstract FROM papers WHERE id = ?",
                (int(paper_id),),
            ).fetchone()
            if row:
                title, deep_summary, deep_summary_chunks_json, abstract = row
        elif has_deep:
            row = conn.execute(
                "SELECT title, deep_summary, abstract FROM papers WHERE id = ?",
                (int(paper_id),),
            ).fetchone()
            if row:
                title, deep_summary, abstract = row
        else:
            row = conn.execute(
                "SELECT title, abstract FROM papers WHERE id = ?",
                (int(paper_id),),
            ).fetchone()
            if row:
                title, abstract = row
        conn.close()
    except Exception as e:
        return {"paper_id": paper_id, "error": f"db error: {e}", "summary": ""}

    if deep_summary:
        summary_chunks: list[dict] = []
        if deep_summary_chunks_json:
            try:
                summary_chunks = _json.loads(deep_summary_chunks_json)
            except Exception:
                summary_chunks = []
        # 只返回 summary 实际引用到的 chunks(LLM 看的 tool result 不需要全 23 个)
        import re as _re
        cited_indices = set(int(m) for m in _re.findall(r"\[#(\d+)\]", deep_summary))
        cited_chunks_for_llm = [c for c in summary_chunks if c.get("chunk_index") in cited_indices]
        return {
            "paper_id": paper_id,
            "title": title or "",
            "summary": deep_summary,
            "summary_type": "deep",
            "char_count": len(deep_summary),
            "cited_chunks": cited_chunks_for_llm,  # 给 LLM 看引用了哪些段
            "_all_chunks": summary_chunks,         # 完整 chunks meta(给前端/generate 用,LLM 不看)
        }
    # Fallback to short abstract
    if abstract:
        return {
            "paper_id": paper_id,
            "title": title or "",
            "summary": abstract,
            "summary_type": "abstract_fallback",
            "char_count": len(abstract),
            "note": "deep_summary not generated yet; returning short abstract (less detailed)",
            "cited_chunks": [],
            "_all_chunks": [],
        }
    return {"paper_id": paper_id, "title": title or "", "error": "no summary available", "summary": ""}


# ══════════════════════════════════════════════════════════════════
# Step 3 (2026-06-17): 结构化 PDF 工具 — 基于新 ingestion 的 chunk metadata
# (page_start/page_end/section_path/block_type/table_no/figure_no/bbox)
# 全部 Python 端过滤:只用 where={"paper_id": pid} 等值查询,避开生产 chromadb
# 版本不认 $in/$lte 等操作符的坑。旧库缺这些字段时优雅降级(返回默认值)。
# ══════════════════════════════════════════════════════════════════
def _parse_bbox(s: str) -> list:
    """'x0,y0,x1,y1' 字符串 → [float,...];失败返回 []。"""
    if not s:
        return []
    try:
        return [float(v) for v in s.split(",")]
    except Exception:
        return []


def _get_paper_chunks(paper_id: int) -> list:
    """取一篇论文全部 chunk,按 chunk_index 排序,返回 dict 列表(含 metadata + 文本)。"""
    coll = get_collection()
    raw = coll.get(where={"paper_id": int(paper_id)}, limit=500)
    if not raw or not raw.get("ids"):
        return []
    out = []
    for i, _id in enumerate(raw["ids"]):
        meta = raw["metadatas"][i] or {}
        out.append({
            "chunk_index": meta.get("chunk_index", 0),
            "page_start": meta.get("page_start", 0),
            "page_end": meta.get("page_end", 0),
            "section": meta.get("section", ""),
            "section_path": meta.get("section_path", ""),
            "block_type": meta.get("block_type", "paragraph"),
            "table_no": meta.get("table_no", ""),
            "figure_no": meta.get("figure_no", ""),
            "bbox": meta.get("bbox", ""),
            "title": meta.get("title", ""),
            "text": raw["documents"][i],
        })
    out.sort(key=lambda c: c["chunk_index"])
    return out


def tool_search_pdf(query: str, paper_id: int = None, top_k: int = 8) -> dict:
    """检索相关片段(可限定单篇),返回带页码/章节/bbox 的片段供溯源。"""
    where = {"paper_id": int(paper_id)} if paper_id else None
    chunks = retrieve(query, top_k=int(top_k), where=where)
    hits = [{
        "paper_id": c.paper_id,
        "chunk_index": c.chunk_index,
        "page": c.page_start,
        "page_end": c.page_end,
        "section_path": c.section_path or c.section,
        "block_type": c.block_type,
        "table_no": c.table_no,
        "score": round(float(c.score), 3),
        "bbox": _parse_bbox(c.bbox),
        "snippet": c.text[:400],
    } for c in chunks]
    logger.info(f"[tool:search_pdf] q={query[:40]!r} paper={paper_id} → {len(hits)} hits")
    return {"query": query, "paper_id": paper_id, "hits": hits}


def tool_read_page(paper_id: int, page: int) -> dict:
    """读指定页的全部 block(按阅读顺序)。page 为 0-based 真页码。"""
    page = int(page)
    chunks = _get_paper_chunks(paper_id)
    if not chunks:
        return {"paper_id": paper_id, "page": page, "error": "paper not found", "blocks": []}
    on_page = [c for c in chunks if c["page_start"] <= page <= c["page_end"]]
    blocks = [{
        "chunk_index": c["chunk_index"],
        "block_type": c["block_type"],
        "section_path": c["section_path"] or c["section"],
        "table_no": c["table_no"],
        "figure_no": c["figure_no"],
        "text": c["text"],
    } for c in on_page]
    title = chunks[0]["title"]
    logger.info(f"[tool:read_page] paper={paper_id} page={page} → {len(blocks)} blocks")
    return {"paper_id": paper_id, "title": title, "page": page,
            "block_count": len(blocks), "blocks": blocks}


def tool_extract_table(paper_id: int, table_no: str = None, query: str = None) -> dict:
    """抽取论文的表格(结构化 markdown)。给 table_no 精确取,给 query 关键词排序,都不给返回全部表。"""
    chunks = _get_paper_chunks(paper_id)
    tables = [c for c in chunks if c["block_type"] == "table"]
    if not tables:
        return {"paper_id": paper_id, "tables": [],
                "note": "无结构化表格(可能是无线表/扫描件,或该库尚未用新 ingestion 重抽)"}

    if table_no:
        want = table_no.lower().replace(" ", "")
        tables = [t for t in tables
                  if want in (t["table_no"] or "").lower().replace(" ", "")] or tables
    elif query:
        ql = query.lower()
        tables.sort(key=lambda t: sum(w in t["text"].lower() for w in ql.split()), reverse=True)

    result = [{
        "table_no": t["table_no"],
        "page": t["page_start"],
        "section_path": t["section_path"],
        "bbox": _parse_bbox(t["bbox"]),
        "chunk_index": t["chunk_index"],
        "markdown": t["text"],
    } for t in tables[:5]]
    logger.info(f"[tool:extract_table] paper={paper_id} table_no={table_no} → {len(result)} tables")
    return {"paper_id": paper_id, "table_count": len(result), "tables": result}


def tool_quote_source(paper_id: int, chunk_index: int) -> dict:
    """返回精确原文 + 页码 + bbox,供引用溯源/PDF 高亮。"""
    chunks = _get_paper_chunks(paper_id)
    match = [c for c in chunks if c["chunk_index"] == int(chunk_index)]
    if not match:
        return {"paper_id": paper_id, "chunk_index": chunk_index, "error": "chunk not found"}
    c = match[0]
    return {
        "paper_id": paper_id,
        "title": c["title"],
        "chunk_index": c["chunk_index"],
        "page": c["page_start"],
        "page_end": c["page_end"],
        "section_path": c["section_path"] or c["section"],
        "block_type": c["block_type"],
        "table_no": c["table_no"],
        "figure_no": c["figure_no"],
        "bbox": _parse_bbox(c["bbox"]),
        "quote": c["text"],
    }


def tool_analyze_chart(paper_id: int, figure_no: str = None) -> dict:
    """图表理解 — Phase 2 桩。当前只返回图注(VLM 图像摘要待接 Qwen2.5-VL)。"""
    chunks = _get_paper_chunks(paper_id)
    figs = [c for c in chunks if c["block_type"] == "figure"]
    if figure_no:
        want = figure_no.lower().replace(" ", "")
        figs = [f for f in figs
                if want in (f["figure_no"] or "").lower().replace(" ", "")] or figs
    result = [{
        "figure_no": f["figure_no"],
        "page": f["page_start"],
        "section_path": f["section_path"],
        "caption": f["text"],
        "summary": None,  # Phase 2: VLM 生成
    } for f in figs[:8]]
    return {"paper_id": paper_id, "figure_count": len(result), "figures": result,
            "note": "图像摘要(VLM)为 Phase 2 功能,当前仅返回图注"}


TOOL_DISPATCH = {
    "read_paper_summary": tool_read_paper_summary,
    "find_relevant_papers": tool_find_relevant_papers,
    "read_paper_fulltext": tool_read_paper_fulltext,
    "read_paper_section": tool_read_paper_section,
    # Step 3 结构化 PDF 工具
    "search_pdf": tool_search_pdf,
    "read_page": tool_read_page,
    "extract_table": tool_extract_table,
    "quote_source": tool_quote_source,
    "analyze_chart": tool_analyze_chart,
}


# Step 3 工具的 LLM 调用 schema(供 agent 按需调用)
TOOL_DEFINITIONS += [
    {"type": "function", "function": {
        "name": "search_pdf",
        "description": (
            "检索相关片段(语义检索),返回每段的 paper_id/chunk_index/页码/章节路径/类型/bbox/原文摘要。"
            "可传 paper_id 限定单篇内检索。用于:定位某说法在哪几段、哪一页。"),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "检索 query(英文最佳)"},
            "paper_id": {"type": "integer", "description": "可选,限定在该论文内检索"},
            "top_k": {"type": "integer", "default": 8, "description": "返回片段数"},
        }, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "read_page",
        "description": "读论文指定页(0-based 真页码)的全部 block,按阅读顺序返回。用于:核对某页上下文。",
        "parameters": {"type": "object", "properties": {
            "paper_id": {"type": "integer", "description": "论文 id"},
            "page": {"type": "integer", "description": "0-based 页码"},
        }, "required": ["paper_id", "page"]}}},
    {"type": "function", "function": {
        "name": "extract_table",
        "description": (
            "抽取论文中的表格(结构化 markdown)。传 table_no 精确取某表,传 query 按关键词排序,"
            "都不传返回全部表。用于:取定量数据表核对数值。"),
        "parameters": {"type": "object", "properties": {
            "paper_id": {"type": "integer", "description": "论文 id"},
            "table_no": {"type": "string", "description": "可选,如 'Table 3'"},
            "query": {"type": "string", "description": "可选,按关键词排序表格"},
        }, "required": ["paper_id"]}}},
    {"type": "function", "function": {
        "name": "quote_source",
        "description": (
            "返回某个 chunk 的精确原文 + 页码 + bbox,供引用溯源 / PDF 高亮。"
            "用于:确认要引用的原句出处。chunk_index 来自 search_pdf 的返回。"),
        "parameters": {"type": "object", "properties": {
            "paper_id": {"type": "integer", "description": "论文 id"},
            "chunk_index": {"type": "integer", "description": "片段索引(search_pdf 返回)"},
        }, "required": ["paper_id", "chunk_index"]}}},
    {"type": "function", "function": {
        "name": "analyze_chart",
        "description": "理解论文中的图表(Phase 2:当前仅返回图注,VLM 图像摘要待接入)。",
        "parameters": {"type": "object", "properties": {
            "paper_id": {"type": "integer", "description": "论文 id"},
            "figure_no": {"type": "string", "description": "可选,如 'Figure 2'"},
        }, "required": ["paper_id"]}}},
]


def execute_tool(name: str, arguments: dict) -> str:
    """统一执行入口,返回 JSON 字符串。"""
    if name == "finalize_answer":
        return json.dumps({"status": "finalize", **arguments}, ensure_ascii=False)

    func = TOOL_DISPATCH.get(name)
    if not func:
        return json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False)

    try:
        result = func(**arguments)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        logger.warning(f"[tool:{name}] error: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def reconstruct_chunks_for_generation(
    tool_call_log: list,
) -> tuple[list[RetrievedChunk], list[dict]]:
    """
    把 agent 调用过的所有 tool 结果转成 generation 节点能用的:
    - chunks: list[RetrievedChunk] — 用于生成回答时作为证据
    - papers_meta: list[dict] — 用于前端展示「读了哪几篇论文」

    返回 (chunks, papers_meta)
    """
    chunks: list[RetrievedChunk] = []
    papers_meta: dict[int, dict] = {}
    seen_keys = set()

    for name, args, result in tool_call_log:
        if name == "find_relevant_papers":
            for p in result.get("papers", []):
                pid = p["paper_id"]
                if pid not in papers_meta:
                    papers_meta[pid] = {
                        "paper_id": pid,
                        "title": p.get("title", ""),
                        "authors": p.get("authors", ""),
                        "year": p.get("year", 0),
                        "category": p.get("category", ""),
                        "score": p.get("max_score", 0.5),
                        "cited": False,  # 只是被找到,还没读全文
                    }
        elif name == "read_paper_summary":
            pid = args.get("paper_id", 0)
            summary = result.get("summary", "")
            title = result.get("title", "")
            summary_type = result.get("summary_type", "")
            all_chunks = result.get("_all_chunks", []) or []
            if summary:
                key = (pid, -3)  # -3 表示 "deep summary"
                if key not in seen_keys:
                    seen_keys.add(key)
                    chunks.append(RetrievedChunk(
                        text=summary,
                        paper_id=pid,
                        title=title,
                        section=f"Summary({summary_type})",
                        category="",
                        year=0,
                        authors="",
                        keywords="",
                        score=0.92,  # 比全文略低,因为是压缩信息
                        chunk_index=-3,
                    ))
                if pid in papers_meta:
                    papers_meta[pid]["cited"] = True
                    # 把 summary_chunks 也存到 papers_meta,前端 [#N] chip 渲染用
                    papers_meta[pid]["summary_chunks"] = all_chunks
                    papers_meta[pid]["summary_text"] = summary
        elif name == "read_paper_fulltext":
            pid = args.get("paper_id", 0)
            full = result.get("fulltext", "")
            title = result.get("title", "")
            if full:
                # 把全文当成一个大 chunk 塞回去
                key = (pid, -1)  # chunk_index=-1 表示"全文"
                if key not in seen_keys:
                    seen_keys.add(key)
                    chunks.append(RetrievedChunk(
                        text=full,
                        paper_id=pid,
                        title=title,
                        section="FullText",
                        category="",
                        year=0,
                        authors="",
                        keywords="",
                        score=0.95,  # 全文比 chunk 重要
                        chunk_index=-1,
                    ))
                if pid in papers_meta:
                    papers_meta[pid]["cited"] = True  # 真读了全文 = 引用
        elif name == "read_paper_section":
            pid = args.get("paper_id", 0)
            section = args.get("section", "")
            text = result.get("text", "")
            if text:
                key = (pid, f"section:{section}")
                if key not in seen_keys:
                    seen_keys.add(key)
                    chunks.append(RetrievedChunk(
                        text=text,
                        paper_id=pid,
                        title="",
                        section=section,
                        category="",
                        year=0,
                        authors="",
                        keywords="",
                        score=0.85,
                        chunk_index=-2,  # -2 表示"完整章节"
                    ))
                if pid in papers_meta:
                    papers_meta[pid]["cited"] = True

    return chunks, list(papers_meta.values())


# ══════════════════════════════════════════════════════════════════
# 2026-06-09 新增: summary_filter + fulltext_evidence 工作流
# 设计参考 plan: summary 只做 reranker, 全文按 token budget 装给 LLM
# ══════════════════════════════════════════════════════════════════

# vLLM context 上限,部署时按实际启动 --max-model-len 调
VLLM_MAX_TOKENS = 32768
# 留给 LLM 输出 + 安全余量
RESERVED_OUTPUT_TOKENS = 2048
# 留给 system prompt + question + structured_evidence
RESERVED_OVERHEAD_TOKENS = 3000
# 全文证据可用预算
FULLTEXT_BUDGET_TOKENS = VLLM_MAX_TOKENS - RESERVED_OUTPUT_TOKENS - RESERVED_OVERHEAD_TOKENS

# BGE reranker 阈值(高于该值的 paper 才进 prompt)
BGE_RERANK_THRESHOLD = 0.7
# 候选 paper 数(进 BGE rerank 的上限)
RERANK_CANDIDATE_N = 8


def estimate_tokens(text: str) -> int:
    """粗略估 token 数: 中英混排约 0.4 token/char, 加 10% 缓冲。
    准确算可改 tiktoken,但加载成本高,在线流程不建议。"""
    if not text:
        return 0
    return int(len(text) * 0.45)


# BGE reranker 全局单例(懒加载,首次调用时载入)
_BGE_RERANKER = None
_BGE_RERANKER_KIND = None  # "cross_encoder" / "flag_reranker" / "disabled"


def _load_bge_reranker():
    """懒加载 BGE reranker。优先 sentence-transformers CrossEncoder,
    退到 FlagEmbedding FlagReranker,都没有就 disabled(降级用检索分排序)。"""
    global _BGE_RERANKER, _BGE_RERANKER_KIND
    if _BGE_RERANKER_KIND is not None:
        return _BGE_RERANKER

    from . import config as _cfg
    model_path = str(_cfg.BASE_DIR / "data" / "bge-reranker-base")

    # 尝试 sentence-transformers
    try:
        from sentence_transformers import CrossEncoder
        _BGE_RERANKER = CrossEncoder(model_path, max_length=512)
        _BGE_RERANKER_KIND = "cross_encoder"
        logger.info(f"[bge_rerank] loaded via sentence-transformers from {model_path}")
        return _BGE_RERANKER
    except Exception as e:
        logger.warning(f"[bge_rerank] sentence-transformers load failed: {e}")

    # 尝试 FlagEmbedding
    try:
        from FlagEmbedding import FlagReranker
        _BGE_RERANKER = FlagReranker(model_path, use_fp16=True)
        _BGE_RERANKER_KIND = "flag_reranker"
        logger.info(f"[bge_rerank] loaded via FlagEmbedding from {model_path}")
        return _BGE_RERANKER
    except Exception as e:
        logger.warning(f"[bge_rerank] FlagEmbedding load failed: {e}")

    _BGE_RERANKER_KIND = "disabled"
    logger.warning("[bge_rerank] no reranker available, will fallback to retrieval scores")
    return None


def bge_rerank(query: str, candidates: list[tuple[int, str]]) -> list[tuple[int, float]]:
    """对 (paper_id, doc) 列表跑 BGE reranker,返回 [(paper_id, score), ...] 按 score 降序。

    Args:
        query: 用户问题(中文或英文都行)
        candidates: [(paper_id, doc_text), ...] 比如 (paper_id, summary)

    Returns:
        按 score 降序的 (paper_id, score) 列表。降级时用 1.0 全过。
    """
    if not candidates:
        return []

    model = _load_bge_reranker()
    if model is None or _BGE_RERANKER_KIND == "disabled":
        # 降级: 所有 candidate 都给 1.0,等于 BGE 不工作时按检索分顺序保留全部
        logger.info(f"[bge_rerank] disabled mode, passing {len(candidates)} candidates through")
        return [(pid, 1.0) for pid, _ in candidates]

    try:
        pairs = [(query, doc) for _, doc in candidates]
        if _BGE_RERANKER_KIND == "cross_encoder":
            raw_scores = model.predict(pairs)
        else:  # flag_reranker
            raw_scores = model.compute_score(pairs, normalize=True)
            # FlagReranker 单条返回 float,多条返回 list
            if isinstance(raw_scores, float):
                raw_scores = [raw_scores]

        results = [
            (candidates[i][0], float(s))
            for i, s in enumerate(raw_scores)
        ]
        results.sort(key=lambda x: -x[1])
        logger.info(
            f"[bge_rerank] {len(results)} scored, "
            f"top={results[0][1]:.3f}, bottom={results[-1][1]:.3f}"
        )
        return results
    except Exception as e:
        logger.warning(f"[bge_rerank] inference failed: {e}, fallback all-pass")
        return [(pid, 1.0) for pid, _ in candidates]


def reconstruct_fulltext_with_index(paper_id: int, max_chars: int = MAX_FULLTEXT_CHARS) -> dict:
    """从 ChromaDB 拼回 paper 全文,每个 chunk 段开头加 [#chunk_index] 标记。

    给 LLM 提供 chunk 边界结构,LLM 看到 [#N] 但 prompt 要求不要输出 [#N]。

    Returns:
      {
        paper_id, title,
        fulltext: 带 [#N] 标记的全文字符串,
        chunks: [{chunk_index, section, text, char_offset}] 给前端高光用,
        char_count, truncated
      }
    """
    coll = get_collection()
    raw = coll.get(where={"paper_id": int(paper_id)}, limit=200)
    if not raw or not raw.get("ids"):
        return {"paper_id": paper_id, "error": "not found", "fulltext": "", "chunks": []}

    title = ""
    section_groups: dict[str, list[tuple[int, str]]] = defaultdict(list)
    section_order: list[str] = []
    meta_by_ci: dict[int, dict] = {}   # chunk_index → 结构化定位字段(page/bbox/...)

    for i, meta in enumerate(raw["metadatas"]):
        if not title and meta.get("title"):
            title = meta.get("title", "")
        section = (meta.get("section") or "Body").strip()
        if section.lower() in SKIP_SECTIONS_FOR_FULLTEXT:
            continue
        if section not in section_order:
            section_order.append(section)
        ci = meta.get("chunk_index", 0)
        section_groups[section].append((ci, raw["documents"][i]))
        meta_by_ci[ci] = {
            "page_start": meta.get("page_start", 0),
            "page_end": meta.get("page_end", 0),
            "section_path": meta.get("section_path", ""),
            "block_type": meta.get("block_type", "paragraph"),
            "table_no": meta.get("table_no", ""),
            "figure_no": meta.get("figure_no", ""),
            "bbox": _parse_bbox(meta.get("bbox", "")),
        }

    parts = []
    chunks_meta = []
    total_chars = 0
    truncated = False

    for section in section_order:
        parts.append(f"\n## {section}\n")
        total_chars += len(parts[-1])
        for chunk_index, chunk_text in sorted(section_groups[section]):
            marker = f"[#{chunk_index}] "
            piece = marker + chunk_text + "\n\n"
            if total_chars + len(piece) > max_chars:
                truncated = True
                break
            parts.append(piece)
            loc = meta_by_ci.get(chunk_index, {})
            chunks_meta.append({
                "chunk_index": chunk_index,
                "section": section,
                "text": chunk_text,
                "char_offset": total_chars + len(marker),
                # 结构化定位(新 ingestion 才有):前端可直接跳页+bbox 高亮
                "page_start": loc.get("page_start", 0),
                "page_end": loc.get("page_end", 0),
                "section_path": loc.get("section_path", ""),
                "block_type": loc.get("block_type", "paragraph"),
                "table_no": loc.get("table_no", ""),
                "figure_no": loc.get("figure_no", ""),
                "bbox": loc.get("bbox", []),
            })
            total_chars += len(piece)
        if truncated:
            break

    fulltext = f"# {title}\n" + "".join(parts)

    logger.info(
        f"[fulltext_with_index] paper_id={paper_id} sections={len(section_order)} "
        f"chunks={len(chunks_meta)} chars={total_chars} truncated={truncated}"
    )
    return {
        "paper_id": paper_id,
        "title": title,
        "fulltext": fulltext,
        "chunks": chunks_meta,
        "char_count": total_chars,
        "truncated": truncated,
    }


def pack_fulltext_evidence(
    ranked_papers: list[dict],
    budget_tokens: int = FULLTEXT_BUDGET_TOKENS,
) -> tuple[str, list[dict], list[dict]]:
    """按 token budget 把 top-K 篇 paper 全文拼成 evidence text 给 LLM。

    Args:
        ranked_papers: [{paper_id, title, year, journal, score, ...}, ...] 按 score 降序
        budget_tokens: token 预算上限

    Returns:
      (evidence_text, packed_papers, packed_chunks)
        evidence_text: 给 LLM prompt 的字符串,格式见 plan
        packed_papers: 实际装入的 paper list, 加了 ref_num 字段(LLM 用的 [N])
        packed_chunks: 全部 chunks 的 LITQA_META 用数据,
                       字段 {paper_id, ref_num, chunk_index, section, text, score}
                       text 按 paper 综合分排过序(top-1 用于高光)
    """
    packed_papers = []
    packed_chunks = []
    parts = []
    used_tokens = 0

    for paper in ranked_papers:
        pid = paper["paper_id"]
        ft = reconstruct_fulltext_with_index(pid)
        if ft.get("error"):
            logger.warning(f"[pack_fulltext] paper {pid} unavailable, skip")
            continue

        # 该 paper 完整加入需要多少 token
        ref_num = len(packed_papers) + 1
        header = f"\n## Paper [{ref_num}] {ft['title']} ({paper.get('year', '?')}, {paper.get('journal', '')})\n"
        body = ft["fulltext"][ft["fulltext"].find("\n") + 1:]  # 去掉 ft 自己的 "# title" 行
        full_block = header + body
        block_tokens = estimate_tokens(full_block)

        if used_tokens + block_tokens > budget_tokens:
            if not packed_papers:
                # 一篇都没装且第一篇就超 budget: 截断装一半
                logger.warning(
                    f"[pack_fulltext] paper {pid} alone exceeds budget "
                    f"({block_tokens} > {budget_tokens}), truncating"
                )
                ratio = budget_tokens / block_tokens
                truncated_len = int(len(full_block) * ratio * 0.95)
                full_block = full_block[:truncated_len] + "\n... [truncated]\n"
            else:
                logger.info(
                    f"[pack_fulltext] paper {pid} would exceed budget "
                    f"({used_tokens + block_tokens} > {budget_tokens}), stopping"
                )
                break

        parts.append(full_block)
        used_tokens += estimate_tokens(full_block)

        packed_papers.append({
            **paper,
            "ref_num": ref_num,
            "cited": True,
        })

        # 该 paper 的 chunks 按相关度排(沿用 paper score 作 chunk score 基础值,
        # 后续可加 BM25 / chunk-level rerank 精排)
        paper_score = paper.get("score", 0.5)
        for c in ft["chunks"]:
            packed_chunks.append({
                "paper_id": pid,
                "ref_num": ref_num,
                "chunk_index": c["chunk_index"],
                "section": c["section"],
                "text": c["text"],
                "score": round(paper_score, 3),
                # 结构化定位透传(供前端跳页+bbox 高亮)
                "page_start": c.get("page_start", 0),
                "page_end": c.get("page_end", 0),
                "section_path": c.get("section_path", ""),
                "block_type": c.get("block_type", "paragraph"),
                "table_no": c.get("table_no", ""),
                "figure_no": c.get("figure_no", ""),
                "bbox": c.get("bbox", []),
            })

    evidence_text = "".join(parts)
    logger.info(
        f"[pack_fulltext] packed {len(packed_papers)} papers, "
        f"{len(packed_chunks)} chunks, {used_tokens} tokens (budget {budget_tokens})"
    )
    return evidence_text, packed_papers, packed_chunks
