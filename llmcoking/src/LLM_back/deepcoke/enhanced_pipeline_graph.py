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
)
from .term_fix import fix_terms

# 复用旧 pipeline_graph 里的辅助函数和节点
from . import pipeline_graph as old_pipeline

# ── 配置:直接读 top-K 篇 summary ───────────────────────────────────
TOP_K_PAPERS = 5      # 投票后取前 K 篇,K 篇 summary 横排正好做 Elicit 表格
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
# 新节点: fast_summary_retrieve
# ══════════════════════════════════════════════════════════════════

def node_fast_summary_retrieve(state: EnhancedPipelineState) -> dict:
    """Node: 投票选 top-K 论文 → 直接读 K 篇 deep_summary,不调 LLM。

    流程:
      1. 用 english_queries 各自 retrieve VOTE_POOL_PER_Q 个 chunk
      2. _vote_papers_from_chunks 选出 top-K paper_id
      3. 每个 paper 直接 sqlite 取 deep_summary(没有就 fallback abstract)
      4. K 篇 summary 包成 RetrievedChunk 列表给 generate
    """
    steps = [{'text': f'正在用 {len(state.get("english_queries", []) or [1])} 个 query '
                      f'选 top-{TOP_K_PAPERS} 篇论文…',
              'done': False, 'pct': 35}]
    out = [old_pipeline._progress_html(steps)]

    eng_queries = state.get("english_queries", []) or [state["question"]]

    # 1. 多 query 投票 + 记录每个 query 的召回轨迹(给前端知识图谱用)
    all_chunks: list = []
    query_recalls: list[dict] = []
    try:
        for q in eng_queries:
            recalled = retrieve(q, top_k=VOTE_POOL_PER_Q)
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
        logger.warning(f"[fast_summary] retrieve failed: {e}, fallback to old node_retrieve")
        return _fallback_to_retrieve(state, out, steps, reason=str(e))

    paper_ids = _vote_papers_from_chunks(all_chunks, TOP_K_PAPERS)
    if not paper_ids:
        return _fallback_to_retrieve(state, out, steps, reason="no papers voted")

    # per-paper 最高分(给 papers_meta 排序展示用)
    score_by_pid: dict[int, float] = {}
    for c in all_chunks:
        if c.paper_id in paper_ids:
            cur = score_by_pid.get(c.paper_id, 0.0)
            if float(c.score) > cur:
                score_by_pid[c.paper_id] = float(c.score)

    steps[0]['done'] = True
    steps[0]['text'] = f"定位到 top-{len(paper_ids)} 篇论文,开始读 summary…"
    steps[0]['pct'] = 45
    out.append(old_pipeline._progress_html(steps))

    # 2. 每篇 paper 读 summary(deep_summary 或 abstract fallback)
    chunks: list[RetrievedChunk] = []
    papers_meta: list[dict] = []
    deep_hits = 0
    abstract_fallbacks = 0
    skipped = 0

    for pid in paper_ids:
        meta = _get_paper_meta(pid)
        summary_result = tool_read_paper_summary(pid)
        summary_text = summary_result.get("summary", "") or ""
        summary_type = summary_result.get("summary_type", "")
        all_summary_chunks = summary_result.get("_all_chunks", []) or []

        if not summary_text:
            skipped += 1
            logger.info(f"[fast_summary] paper_id={pid} no summary, skip")
            continue

        if summary_type == "deep":
            deep_hits += 1
            base_score = 0.92
        else:
            abstract_fallbacks += 1
            base_score = 0.80

        # 用召回时的相关度作 final score(deep summary 加一个轻微 boost)
        retrieval_score = score_by_pid.get(pid, 0.5)
        final_score = max(base_score, retrieval_score)

        title = meta.get("title", "") or summary_result.get("title", "")
        authors_raw = meta.get("authors", "") or ""
        authors_str = (
            ", ".join(str(a) for a in authors_raw)
            if isinstance(authors_raw, list) else str(authors_raw)
        )

        chunks.append(RetrievedChunk(
            text=summary_text,
            paper_id=pid,
            title=title,
            section=f"Summary({summary_type or 'unknown'})",
            category=meta.get("category", "") or "",
            year=meta.get("year", 0) or 0,
            authors=authors_str,
            keywords=meta.get("keywords", "") or "",
            score=final_score,
            chunk_index=-3,  # -3 标识 "deep summary"(与旧 agent_tools 约定一致)
        ))
        papers_meta.append({
            "paper_id": pid,
            "title": title,
            "authors": authors_str,
            "year": meta.get("year", 0) or 0,
            "category": meta.get("category", "") or "",
            "journal": "",
            "score": round(final_score, 3),
            "cited": True,
            "summary_chunks": all_summary_chunks,
            "summary_text": summary_text,
            "summary_type": summary_type,
        })

    if not chunks:
        return _fallback_to_retrieve(state, out, steps, reason="no summaries available")

    steps2 = [{
        'text': (f"读完 {len(chunks)} 篇 summary "
                 f"(深度 {deep_hits} + 摘要兜底 {abstract_fallbacks}"
                 + (f" + 跳过 {skipped}" if skipped else "")
                 + ")"),
        'done': True, 'pct': 60,
    }]
    out.append(old_pipeline._progress_html(steps2))

    # 3. LITQA_META payload(对齐 literature_qa / 旧 retrieve 字段)
    chunks_meta = [
        {
            "ref": i + 1,
            "chunk_id": f"{c.paper_id}_summary",
            "paper_id": c.paper_id,
            "section": c.section or "",
            "score": round(float(c.score), 3),
            "text": (c.text or "")[:1500],
        }
        for i, c in enumerate(chunks)
    ]
    meta_payload = {
        "question": state["question"],
        "english_queries": eng_queries,
        "key_concepts": state.get("key_concepts", []),
        "papers": papers_meta,
        "chunks": chunks_meta,
        "query_recalls": query_recalls,
        "mode": "fast_summary",
        "deep_hits": deep_hits,
        "abstract_fallbacks": abstract_fallbacks,
    }
    out.append(f"<!--LITQA_META:{json.dumps(meta_payload, ensure_ascii=False)}-->\n")

    rationale = (
        f"fast_summary: top-{len(paper_ids)} papers voted, "
        f"{deep_hits} deep + {abstract_fallbacks} abstract"
    )
    logger.info(
        f"[fast_summary] papers={len(paper_ids)} deep={deep_hits} "
        f"abs_fb={abstract_fallbacks} skipped={skipped}"
    )

    return {
        "chunks": chunks,
        "agent_papers_meta": papers_meta,
        "agent_finalize_rationale": rationale,
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
