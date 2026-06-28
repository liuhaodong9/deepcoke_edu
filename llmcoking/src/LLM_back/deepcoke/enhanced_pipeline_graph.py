"""
DeepCoke Enhanced Pipeline — Fast Summary RAG

跟旧 pipeline_graph.py 的区别:
- 旧版: translate → retrieve (top-5 chunks) → kg_lookup → ... → generate
- 新版: translate → fast_summary_retrieve → structured_lookup → generate

核心思路(2026-06-07 改造):
  既然 deep_summary 已经预生成在 sqlite(218/231 篇 ~1000 字/篇),
  直接对 top-K 高相似度论文读 summary,不再让 LLM 用 ReAct 来回 3-5 轮决定读哪几篇。
  - 确定性强(不依赖 vLLM tool calling parser 稳定性)
  - 快(0 次额外 LLM 调用 + sqlite 查询几乎 0 成本)
  - K 篇 summary 横排刚好对接 Elicit 风格表格输出

通过 USE_ENHANCED_PIPELINE 环境变量切换 (在 test.py 里读)。
旧版保留,出问题立刻切回。

入口签名跟旧 pipeline_graph.process_question 完全一致(FastAPI 端无改动)。
"""
import asyncio
import json
import logging
import operator
from typing import Annotated, AsyncGenerator
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END

from .supervisor import supervisor_decide
from .classifier.question_classifier import is_complex
from .vectorstore.retriever import retrieve, RetrievedChunk
from .agent_tools import (
    _vote_papers_from_chunks,
    _get_paper_meta,
    tool_read_paper_summary,
    bge_rerank,
    pack_fulltext_evidence,
    pack_chunk_evidence,
    hybrid_search,
    BGE_RERANK_THRESHOLD,
    RERANK_CANDIDATE_N,
    FULLTEXT_BUDGET_TOKENS,
)

# 多篇整合:每篇装 top-M chunk 而非全文(让 6-8 篇都进 prompt)
CHUNKS_PER_PAPER = 3
# 选篇保底:rerank 后至少带这么多篇进证据(避免被阈值卡到 1 篇,牺牲多篇整合)
MIN_PAPERS_FLOOR = 5
from .term_fix import fix_terms

# 复用旧 pipeline_graph 里的辅助函数和节点
from . import pipeline_graph as old_pipeline

# ── 配置:summary 当过滤器 + 全文当证据 ─────────────────────────────
# (2026-06-09 新设计,见 plan: summary_filter + fulltext_evidence)
VOTE_POOL_PER_Q = 30  # 每个 english_query 取这么多 chunk 进入投票池

logger = logging.getLogger("deepcoke.enhanced_pipeline")


# ══════════════════════════════════════════════════════════════════
# State 定义 (扩展旧的 PipelineState,加 agent 字段)
# ══════════════════════════════════════════════════════════════════

class EnhancedPipelineState(TypedDict):
    question: str
    # 多轮对话历史: [{"user_message": "...", "bot_response": "..."}],按时间顺序老的在前
    history: list
    question_type: str
    agent_plan: list[str]
    agent_plan_idx: int
    supervisor_reasoning: str
    english_queries: list[str]
    key_concepts: list[str]
    chunks: list                # RetrievedChunk 列表(每条 = 一篇论文的 deep_summary)
    kg_context: str
    structured_evidence: str
    reasoning_trace: str
    # Fast-summary 路径附带的展示字段(沿用 agent_papers_meta 名字以兼容前端)
    agent_papers_meta: list     # 命中的 top-K 论文 metadata
    agent_finalize_rationale: str
    agent_iterations: int
    agent_fallback: bool        # True = 退化到旧 retrieve (例如全部 0 个 paper 投出)
    output: Annotated[list[str], operator.add]


# ══════════════════════════════════════════════════════════════════
# 新节点: summary_filter_fulltext_retrieve (2026-06-09)
# 算法: 检索候选 → BGE rerank → 按 token budget 装全文(带 [#N] 标记) → generate
# ══════════════════════════════════════════════════════════════════

def node_fast_summary_retrieve(state: EnhancedPipelineState) -> dict:
    """Node: summary 当过滤器 + 全文当证据。

    流程(对齐 plan):
      A. 用 english_queries 各自 ChromaDB 检索 → 投票 → 8 篇候选 paper
      B. 读 8 篇 summary(deep_summary > abstract fallback) → BGE rerank
         过 0.7 阈值的进 prompt
      C. 按 token budget 动态装全文(每 chunk 段开头加 [#chunk_index] 标记)
         给 LLM 看 chunk 边界结构,但回答里不输出 [#N]
      D. 输出 RetrievedChunk(每条 = paper 内一个 chunk 原文段) + LITQA_META
    """
    eng_queries = state.get("english_queries", []) or [state["question"]]

    steps = [{
        'text': f'A. 用 {len(eng_queries)} 个 query 检索 {RERANK_CANDIDATE_N} 篇候选论文…',
        'done': False, 'pct': 30,
    }]
    out = [old_pipeline._progress_html(steps)]

    # ── A. 检索 + 投票 ─────────────────────────────────────────
    all_chunks: list = []
    query_recalls: list[dict] = []
    try:
        for q in eng_queries:
            recalled = hybrid_search(q, top_k=VOTE_POOL_PER_Q)   # dense+BM25 混合
            all_chunks.extend(recalled)
            per_paper: dict[int, float] = {}
            for c in recalled:
                if c.paper_id:
                    cur = per_paper.get(c.paper_id, 0.0)
                    if float(c.score) > cur:
                        per_paper[c.paper_id] = float(c.score)
            query_recalls.append({
                "query": q,
                "papers": [
                    {"paper_id": pid, "score": round(s, 3)}
                    for pid, s in sorted(per_paper.items(), key=lambda x: -x[1])
                ],
            })
    except Exception as e:
        logger.warning(f"[summary_filter] retrieve failed: {e}, fallback")
        return _fallback_to_retrieve(state, out, steps, reason=str(e))

    candidate_paper_ids = _vote_papers_from_chunks(all_chunks, RERANK_CANDIDATE_N)
    if not candidate_paper_ids:
        return _fallback_to_retrieve(state, out, steps, reason="no candidates voted")

    # per-paper 检索分(后续作为 fallback score)
    retrieval_score_by_pid: dict[int, float] = {}
    for c in all_chunks:
        if c.paper_id in candidate_paper_ids:
            cur = retrieval_score_by_pid.get(c.paper_id, 0.0)
            if float(c.score) > cur:
                retrieval_score_by_pid[c.paper_id] = float(c.score)

    steps[0]['done'] = True
    steps[0]['text'] = f"A. 选出 {len(candidate_paper_ids)} 篇候选,开始 BGE rerank…"
    steps[0]['pct'] = 40
    out.append(old_pipeline._progress_html(steps))

    # ── B. 读 summary + BGE rerank ─────────────────────────────
    steps_b = [{
        'text': f'B. 读 {len(candidate_paper_ids)} 篇 summary 并用 BGE-reranker 重排…',
        'done': False, 'pct': 45,
    }]
    out.append(old_pipeline._progress_html(steps_b))

    rerank_docs: list[tuple[int, str]] = []
    paper_meta_cache: dict[int, dict] = {}
    summary_type_by_pid: dict[int, str] = {}

    for pid in candidate_paper_ids:
        meta = _get_paper_meta(pid)
        paper_meta_cache[pid] = meta
        summary_result = tool_read_paper_summary(pid)
        summary_text = (summary_result.get("summary") or "").strip()
        summary_type = summary_result.get("summary_type", "")
        summary_type_by_pid[pid] = summary_type
        if not summary_text:
            # 没 summary 也没 abstract: 用 title 兜底(不会通过阈值,但保证 BGE 有输入)
            summary_text = meta.get("title", "") or f"Paper {pid}"
        rerank_docs.append((pid, summary_text[:2000]))  # BGE max_length=512 tokens,~2000 chars

    rerank_query = state.get("question", "") or (eng_queries[0] if eng_queries else "")
    reranked = bge_rerank(rerank_query, rerank_docs)
    # 过阈值
    selected = [(pid, s) for pid, s in reranked if s >= BGE_RERANK_THRESHOLD]
    # 保底:不足 MIN_PAPERS_FLOOR 篇时,从 rerank top 补齐(避免被阈值卡到 1 篇,
    # 牺牲多篇整合)。候选本来就是检索投票出来的,补进来的也是相关的。
    if len(selected) < MIN_PAPERS_FLOOR and reranked:
        have = {pid for pid, _ in selected}
        for pid, s in reranked:
            if pid not in have:
                selected.append((pid, s))
                have.add(pid)
            if len(selected) >= MIN_PAPERS_FLOOR:
                break

    if not selected:
        logger.info(
            f"[summary_filter] no paper passed threshold {BGE_RERANK_THRESHOLD}, "
            f"top rerank scores: {[(pid, round(s, 3)) for pid, s in reranked[:3]]}"
        )
        # 退化:全无相关文献,降级到 generate 直答
        steps_b[0]['done'] = True
        steps_b[0]['text'] = f"B. 候选全部 < {BGE_RERANK_THRESHOLD} 阈值,无强相关文献"
        steps_b[0]['pct'] = 55
        out.append(old_pipeline._progress_html(steps_b))
        return _empty_evidence(state, out, query_recalls, eng_queries)

    steps_b[0]['done'] = True
    steps_b[0]['text'] = (
        f"B. BGE 重排选中 {len(selected)} 篇 (≥{BGE_RERANK_THRESHOLD}), "
        f"top={selected[0][1]:.2f}"
    )
    steps_b[0]['pct'] = 55
    out.append(old_pipeline._progress_html(steps_b))

    # ── C. 按 token budget 装全文 ──────────────────────────────
    steps_c = [{
        'text': f'C. 按 token budget 装入全文(预算 {FULLTEXT_BUDGET_TOKENS // 1000}K)…',
        'done': False, 'pct': 60,
    }]
    out.append(old_pipeline._progress_html(steps_c))

    ranked_papers = []
    for pid, rscore in selected:
        meta = paper_meta_cache[pid]
        authors_raw = meta.get("authors", "") or ""
        authors_str = (
            ", ".join(str(a) for a in authors_raw)
            if isinstance(authors_raw, list) else str(authors_raw)
        )
        ranked_papers.append({
            "paper_id": pid,
            "title": meta.get("title", "") or "",
            "authors": authors_str,
            "year": meta.get("year", 0) or 0,
            "journal": "",
            "category": meta.get("category", "") or "",
            "score": float(rscore),
            "summary_type": summary_type_by_pid.get(pid, ""),
        })

    # 每篇只装 top-M 相关 chunk(不是全文),让多篇都进 prompt 做整合
    chunk_query = (eng_queries[0] if eng_queries else state.get("question", "")) or rerank_query
    evidence_text, packed_papers, packed_chunks = pack_chunk_evidence(
        ranked_papers, query=chunk_query,
        budget_tokens=FULLTEXT_BUDGET_TOKENS, chunks_per_paper=CHUNKS_PER_PAPER,
    )

    if not packed_papers:
        return _fallback_to_retrieve(state, out, steps_c, reason="no chunk evidence available")

    steps_c[0]['done'] = True
    used_tokens = sum(len(p) for p in [evidence_text]) * 0.45 // 1
    steps_c[0]['text'] = (
        f"C. 装入 {len(packed_papers)} 篇 ×{CHUNKS_PER_PAPER} 相关段 "
        f"(~{int(used_tokens) // 1000}K tokens,{len(packed_chunks)} 段)"
    )
    steps_c[0]['pct'] = 70
    out.append(old_pipeline._progress_html(steps_c))

    # ── D. 输出: 把 evidence_text 包成 1 个 "fulltext-evidence" RetrievedChunk
    # generate 节点会用 chunks 列表里的 text 作 evidence,我们把 evidence_text 作为
    # 单条 chunk 塞给它(generate 节点的 prompt 已重写,直接拿 chunks[0].text)
    out_chunks: list[RetrievedChunk] = [RetrievedChunk(
        text=evidence_text,
        paper_id=0,
        title="Fulltext Evidence Pack",
        section="FulltextEvidence",
        category="",
        year=0,
        authors="",
        keywords="",
        score=1.0,
        chunk_index=-4,  # -4 标识 "fulltext evidence pack"
    )]

    # papers_meta: 仅 packed (装入的) papers,移除 summary_chunks 字段
    papers_meta = [
        {
            "paper_id": p["paper_id"],
            "title": p["title"],
            "authors": p["authors"],
            "year": p["year"],
            "category": p["category"],
            "journal": p.get("journal", ""),
            "score": round(p["score"], 3),
            "cited": True,
            "ref_num": p["ref_num"],
            "summary_type": p.get("summary_type", ""),
        }
        for p in packed_papers
    ]

    # LITQA_META.chunks: 装入的所有 chunks, 按 score 降序(供前端 [N] click 取 top-1)
    chunks_meta = [
        {
            "ref": c["ref_num"],
            "chunk_id": f"{c['paper_id']}_{c['chunk_index']}",
            "paper_id": c["paper_id"],
            "chunk_index": c["chunk_index"],
            "section": c["section"],
            "score": c["score"],
            "text": (c["text"] or "")[:1500],
            # 结构化定位:前端 [N] click 优先用 page+bbox 直接跳页高亮(无则退回文本搜索)
            "page": c.get("page_start", 0),
            "page_end": c.get("page_end", 0),
            "section_path": c.get("section_path", ""),
            "block_type": c.get("block_type", "paragraph"),
            "table_no": c.get("table_no", ""),
            "figure_no": c.get("figure_no", ""),
            "bbox": c.get("bbox", []),
        }
        for c in sorted(packed_chunks, key=lambda x: -x["score"])
    ]

    # C⑨': 关键图片(从引用论文的 figure chunk 按 query 选)
    figures_meta = _select_key_figures(packed_papers, chunk_query)

    meta_payload = {
        "question": state["question"],
        "english_queries": eng_queries,
        "key_concepts": state.get("key_concepts", []),
        "papers": papers_meta,
        "chunks": chunks_meta,
        "figures": figures_meta,
        "query_recalls": query_recalls,
        "mode": "summary_filter_fulltext",
        "candidates_count": len(candidate_paper_ids),
        "selected_count": len(selected),
        "packed_count": len(packed_papers),
        "rerank_threshold": BGE_RERANK_THRESHOLD,
    }
    out.append(f"<!--LITQA_META:{json.dumps(meta_payload, ensure_ascii=False)}-->\n")

    rationale = (
        f"summary_filter: {len(candidate_paper_ids)} candidates → "
        f"rerank ≥{BGE_RERANK_THRESHOLD} = {len(selected)} → "
        f"packed {len(packed_papers)} fulltexts"
    )
    logger.info(f"[summary_filter] {rationale}")

    return {
        "chunks": out_chunks,
        "agent_papers_meta": papers_meta,
        "agent_finalize_rationale": rationale,
        "agent_iterations": 0,
        "agent_fallback": False,
        "output": out,
    }


def _empty_evidence(state, out, query_recalls, eng_queries):
    """所有候选 < 阈值 → 让 generate 在无文献证据下回答(降级提示)。"""
    meta_payload = {
        "question": state["question"],
        "english_queries": eng_queries,
        "key_concepts": state.get("key_concepts", []),
        "papers": [],
        "chunks": [],
        "query_recalls": query_recalls,
        "mode": "summary_filter_fulltext",
        "selected_count": 0,
        "note": "no_paper_above_threshold",
    }
    out.append(f"<!--LITQA_META:{json.dumps(meta_payload, ensure_ascii=False)}-->\n")
    return {
        "chunks": [],
        "agent_papers_meta": [],
        "agent_finalize_rationale": "no paper above rerank threshold",
        "agent_iterations": 0,
        "agent_fallback": False,
        "output": out,
    }


def _fallback_to_retrieve(state: EnhancedPipelineState, out, steps, reason: str) -> dict:
    """退化路径:fast_summary 失败时跑旧 chunk-based retrieve 节点。"""
    logger.info(f"[fast_summary] falling back to old retrieve: {reason}")
    fake_state = dict(state)
    old_result = old_pipeline.node_retrieve(fake_state)
    steps[0]['done'] = True
    steps[0]['text'] = f"传统检索(退化模式): {len(old_result.get('chunks', []))} 条片段"
    steps[0]['pct'] = 55
    out.append(old_pipeline._progress_html(steps))
    return {
        "chunks": old_result.get("chunks", []),
        "agent_papers_meta": [],
        "agent_finalize_rationale": f"fast_summary fallback: {reason}",
        "agent_iterations": 0,
        "agent_fallback": True,
        "output": out + old_result.get("output", []),
    }


# ── C⑨': 关键图片选取(无 VLM,图文 caption 关联) ──────────────────────
FIGURE_RERANK_MIN = 0.30   # 图 caption 与 query 的相关阈值,低于不展示
FIGURE_TOP_N = 3


def _select_key_figures(packed_papers: list, query: str) -> list:
    """从引用论文的 figure chunk 里按 query(BGE rerank caption)选 top-N 关键图。
    只从回答引用的论文里选 → 相关性有保证;纯图文关联,不调 VLM。"""
    ref_by_pid = {p["paper_id"]: p.get("ref_num") for p in packed_papers}
    cands = []
    try:
        from .vectorstore.chromadb_store import get_collection
        coll = get_collection()
        for pid in ref_by_pid:
            raw = coll.get(where={"paper_id": pid}, include=["documents", "metadatas"])
            for doc, m in zip(raw.get("documents") or [], raw.get("metadatas") or []):
                if m.get("block_type") != "figure":
                    continue
                cap = (doc or "").split("[图像描述]")[0].strip()
                if cap:
                    cands.append({
                        "paper_id": pid, "ref": ref_by_pid[pid], "caption": cap[:300],
                        "page": m.get("page_start", 0), "bbox": m.get("bbox", ""),
                        "figure_no": m.get("figure_no", ""),
                    })
    except Exception as e:
        logger.warning(f"[fast_summary] 取 figure chunk 失败: {e}")
        return []
    if not cands:
        return []
    try:
        ranked = bge_rerank(query, [(i, c["caption"]) for i, c in enumerate(cands)])
    except Exception as e:
        logger.warning(f"[fast_summary] figure rerank 失败: {e}")
        return []
    out = []
    for i, s in ranked[:FIGURE_TOP_N]:
        if float(s) >= FIGURE_RERANK_MIN:
            c = dict(cands[i]); c["score"] = round(float(s), 3)
            out.append(c)
    return out


# ══════════════════════════════════════════════════════════════════
# 路由函数(简化版,跳过 kg_lookup 和 reason)
# ══════════════════════════════════════════════════════════════════

def route_after_supervisor(state: EnhancedPipelineState) -> str:
    plan = state.get("agent_plan", [])
    idx = state.get("agent_plan_idx", 0)
    if idx >= len(plan):
        return "simple_chat"
    agent = plan[idx]
    if agent == "optimization":
        return "edu_optimization"
    if agent == "simple_chat":
        return "simple_chat"
    if agent == "literature_qa":
        return "literature_qa"
    return "translate"


def route_after_structured(state: EnhancedPipelineState) -> str:
    """新版直接 generate(ESCARGOT 已移除,agent_loop 已覆盖多步推理)。"""
    return "generate"


# ══════════════════════════════════════════════════════════════════
# Graph 构建
# ══════════════════════════════════════════════════════════════════

def build_enhanced_graph() -> StateGraph:
    g = StateGraph(EnhancedPipelineState)

    # 复用旧节点
    g.add_node("supervisor", old_pipeline.node_supervisor)
    g.add_node("edu_optimization", old_pipeline.node_edu_optimization)
    g.add_node("simple_chat", old_pipeline.node_simple_chat)
    g.add_node("literature_qa", old_pipeline.node_literature_qa)
    g.add_node("translate", old_pipeline.node_translate)
    g.add_node("structured_lookup", old_pipeline.node_structured_lookup)
    g.add_node("generate", old_pipeline.node_generate)
    g.add_node("followup", old_pipeline.node_followup)
    # 新节点
    g.add_node("fast_summary_retrieve", node_fast_summary_retrieve)

    # 边
    g.add_edge(START, "supervisor")
    g.add_conditional_edges("supervisor", route_after_supervisor, {
        "edu_optimization": "edu_optimization",
        "simple_chat": "simple_chat",
        "literature_qa": "literature_qa",
        "translate": "translate",
    })
    g.add_edge("edu_optimization", END)
    g.add_edge("simple_chat", END)
    g.add_edge("literature_qa", END)
    # RAG 新链: translate → fast_summary_retrieve → structured_lookup → generate → followup → END
    g.add_edge("translate", "fast_summary_retrieve")
    g.add_edge("fast_summary_retrieve", "structured_lookup")
    g.add_conditional_edges("structured_lookup", route_after_structured, {
        "generate": "generate",
    })
    g.add_edge("generate", "followup")
    g.add_edge("followup", END)

    return g.compile()


_enhanced_graph = build_enhanced_graph()


# ══════════════════════════════════════════════════════════════════
# 对外接口
# ══════════════════════════════════════════════════════════════════

async def process_question(question: str, history: list | None = None) -> AsyncGenerator[str, None]:
    """跟 pipeline_graph.process_question 签名一致,加可选 history 参数(用于 query 跨轮补全)。"""
    initial_state: EnhancedPipelineState = {
        "question": question,
        "history": history or [],
        "question_type": "",
        "agent_plan": [],
        "agent_plan_idx": 0,
        "supervisor_reasoning": "",
        "english_queries": [],
        "key_concepts": [],
        "chunks": [],
        "kg_context": "",
        "structured_evidence": "",
        "reasoning_trace": "",
        "agent_papers_meta": [],
        "agent_finalize_rationale": "",
        "agent_iterations": 0,
        "agent_fallback": False,
        "output": [],
    }

    async for event in _enhanced_graph.astream(initial_state, stream_mode="updates"):
        for node_name, updates in event.items():
            new_output = updates.get("output", [])
            for piece in new_output:
                yield piece
                await asyncio.sleep(0)

    logger.info("[enhanced_pipeline] === COMPLETE ===")
