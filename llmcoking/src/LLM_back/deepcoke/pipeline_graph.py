"""
DeepCoke 教育版 Pipeline — LangGraph StateGraph 实现
Phase 1: LangGraph 替换手写路由
Phase 2: Supervisor LLM 智能路由 + 多 agent 串行
"""
import logging
import asyncio
import operator
from typing import Annotated, AsyncGenerator
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END

from .supervisor import supervisor_decide
from .classifier.question_classifier import is_complex, needs_rag
from .classifier.query_translator import translate_query
from .vectorstore.retriever import retrieve, RetrievedChunk
from .knowledge_graph.neo4j_client import find_related_papers
from .generation.answer_generator import generate_answer_stream
from .followup.followup_generator import generate_followup_questions, format_followup_block
from .reasoning.escargot_runner import run_escargot_reasoning

logger = logging.getLogger("deepcoke.pipeline")


# ══════════════════════════════════════════════════════════════════
# State 定义
# ══════════════════════════════════════════════════════════════════

class PipelineState(TypedDict):
    """LangGraph 流转状态。output 用 operator.add 累加，每个节点追加输出片段。"""
    question: str
    question_type: str
    # Supervisor 多 agent 计划（Phase 2）
    agent_plan: list[str]
    agent_plan_idx: int
    supervisor_reasoning: str
    # RAG 中间结果
    english_queries: list[str]
    key_concepts: list[str]
    chunks: list              # RetrievedChunk 列表
    kg_context: str
    reasoning_trace: str
    # 累计输出（每个节点 append 新的片段）
    output: Annotated[list[str], operator.add]


# ══════════════════════════════════════════════════════════════════
# 进度条辅助（与原版一致）
# ══════════════════════════════════════════════════════════════════

def _progress_html(steps: list[dict]) -> str:
    """将进度步骤拼成带进度条的 HTML 块。"""
    lines = ['<div class="pipeline-progress">']
    for step in steps:
        icon = '✅' if step.get('done') else '⏳'
        lines.append(f'<div class="progress-step">{icon} {step["text"]}</div>')
    total = len(steps)
    done_count = sum(1 for s in steps if s.get('done'))
    pct = steps[-1].get('pct', int(done_count / max(total, 1) * 100)) if steps else 0
    is_complete = pct >= 100
    bar_class = 'progress-bar-complete' if is_complete else ''
    lines.append(f'<div class="progress-bar-wrap">')
    lines.append(f'<div class="progress-bar-fill {bar_class}" style="width:{pct}%"></div>')
    lines.append(f'</div>')
    if is_complete:
        lines.append(f'<div class="progress-pct-done">✅ 完成</div>')
    else:
        lines.append(f'<div class="progress-pct">{pct}%</div>')
    lines.append('</div>\n\n')
    return ''.join(lines)


# ══════════════════════════════════════════════════════════════════
# Node 函数（每个返回 dict，output 字段会被累加）
# ══════════════════════════════════════════════════════════════════

def node_supervisor(state: PipelineState) -> dict:
    """Node: Supervisor LLM 智能路由决策（Phase 2）。"""
    question = state["question"]
    logger.info(f"[supervisor] question={question[:50]}")

    steps = [{'text': 'Supervisor：正在分析问题…', 'done': False, 'pct': 5}]
    out = [_progress_html(steps)]

    decision = supervisor_decide(question)
    agent_plan = decision["agents"]
    reasoning = decision["reasoning"]

    # 映射 agent 名 → question_type
    agent_to_type = {
        "optimization": "optimization",
        "knowledge_qa": "factual",  # 触发 RAG 路径
        "simple_chat": "general_chat",
    }
    first_agent = agent_plan[0] if agent_plan else "knowledge_qa"
    question_type = agent_to_type.get(first_agent, "factual")
    # knowledge_qa 可能映射到更具体的类型（factual/comparison/causal 等）
    # 但教育版不需要区分，统一走 RAG

    agent_labels = {
        "optimization": "配煤优化", "knowledge_qa": "知识问答",
        "simple_chat": "闲聊", "coal_price": "煤价查询",
        "data_management": "数据管理", "oven_control": "焦炉操作",
    }
    plan_display = " → ".join(agent_labels.get(a, a) for a in agent_plan)
    steps[0]['done'] = True
    steps[0]['text'] = f"Supervisor 路由：{plan_display}"
    steps[0]['pct'] = 10
    out.append(_progress_html(steps))

    logger.info(f"[supervisor] plan={agent_plan}, type={question_type}, reasoning={reasoning}")
    return {
        "question_type": question_type,
        "agent_plan": agent_plan,
        "agent_plan_idx": 0,
        "supervisor_reasoning": reasoning,
        "output": out,
    }


def node_edu_optimization(state: PipelineState) -> dict:
    """Node: 教育版配煤优化（降级为简单聊天提示 + 直接对话）。"""
    from .llm_client import chat

    out = [
        "\n> 💡 **教育版暂不支持配煤优化计算，已转为知识问答模式。"
        "如需配煤优化功能请使用企业版。**\n\n"
    ]

    system_prompt = (
        "你是焦化大语言智能问答与分析系统DeepCoke，由苏州龙泰氢一能源科技有限公司研发。"
        "以下是对你输出的强制格式要求："
        "1. 任何数学公式一定要使用 $$ 公式 $$ 包裹\n"
        "2. 多行代码一定使用三重反引号 ``` 语言 来包裹\n"
        "3. 务必使用标准 Markdown 语法。\n"
        "4. 不要提供mermaid图"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": state["question"]},
    ]
    stream = chat(messages, stream=True)
    for chunk in stream:
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None)
        if piece:
            out.append(piece)

    return {"output": out}


def node_simple_chat(state: PipelineState) -> dict:
    """Node: 闲聊（不走 RAG）。"""
    from .llm_client import chat

    system_prompt = (
        "你是焦化大语言智能问答与分析系统DeepCoke，由苏州龙泰氢一能源科技有限公司研发。"
        "以下是对你输出的强制格式要求："
        "1. 任何数学公式一定要使用 $$ 公式 $$ 包裹\n"
        "2. 多行代码一定使用三重反引号 ``` 语言 来包裹\n"
        "3. 务必使用标准 Markdown 语法。\n"
        "4. 不要提供mermaid图"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": state["question"]},
    ]
    out = ["\r\n"]
    stream = chat(messages, stream=True)
    for chunk in stream:
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None)
        if piece:
            out.append(piece)

    return {"output": out}


def node_translate(state: PipelineState) -> dict:
    """Node: 关键词提取 + 翻译检索语句。"""
    steps = [{'text': '正在提取关键词并翻译检索语句…', 'done': False, 'pct': 15}]
    out = [_progress_html(steps)]

    translated = translate_query(state["question"])
    english_queries = translated["english_queries"]
    key_concepts = translated["key_concepts"]

    steps[0]['done'] = True
    steps[0]['text'] = f"关键词：{', '.join(key_concepts[:5])}"
    steps[0]['pct'] = 25
    out.append(_progress_html(steps))

    logger.info(f"[translate] queries={english_queries}, concepts={key_concepts}")
    return {
        "english_queries": english_queries,
        "key_concepts": key_concepts,
        "output": out,
    }


def node_retrieve(state: PipelineState) -> dict:
    """Node: 向量数据库检索。"""
    steps = [{'text': '正在检索文献数据库…', 'done': False, 'pct': 30}]
    out = [_progress_html(steps)]

    all_chunks: list[RetrievedChunk] = []
    for eq in state["english_queries"]:
        chunks = retrieve(eq, top_k=5)
        all_chunks.extend(chunks)

    # 去重：按 (paper_id, chunk_index) 保留最高分
    seen = {}
    for c in all_chunks:
        key = (c.paper_id, c.chunk_index)
        if key not in seen or c.score > seen[key].score:
            seen[key] = c
    all_chunks = sorted(seen.values(), key=lambda x: x.score, reverse=True)[:10]

    steps[0]['done'] = True
    steps[0]['text'] = f"检索到 {len(all_chunks)} 条相关文献片段"
    steps[0]['pct'] = 45
    out.append(_progress_html(steps))

    logger.info(f"[retrieve] {len(all_chunks)} unique chunks")
    return {"chunks": all_chunks, "output": out}


def node_kg_lookup(state: PipelineState) -> dict:
    """Node: 知识图谱查询。"""
    steps = [{'text': '正在查询知识图谱…', 'done': False, 'pct': 50}]
    out = [_progress_html(steps)]

    kg_context = ""
    try:
        kg_results = []
        for concept in state["key_concepts"][:3]:
            papers = find_related_papers(concept, limit=3)
            if papers:
                kg_results.extend(papers)
        if kg_results:
            kg_lines = []
            for r in kg_results[:5]:
                kg_lines.append(
                    f"- {r.get('title', 'Unknown')} ({r.get('year', '?')}): "
                    f"studies {r.get('concept', '')}"
                )
            kg_context = "\n".join(kg_lines)
        steps[0]['done'] = True
        steps[0]['text'] = f"知识图谱：发现 {len(kg_results)} 条关联"
        steps[0]['pct'] = 60
    except Exception as e:
        steps[0]['done'] = True
        steps[0]['text'] = "知识图谱：跳过（连接异常）"
        steps[0]['pct'] = 60
        logger.warning(f"[kg_lookup] non-fatal: {e}")

    out.append(_progress_html(steps))
    return {"kg_context": kg_context, "output": out}


def node_reason(state: PipelineState) -> dict:
    """Node: ESCARGOT 深度推理（仅复杂问题）。"""
    steps = [{'text': '正在进行深度推理（ESCARGOT）…', 'done': False, 'pct': 65}]
    out = [_progress_html(steps)]

    reasoning_trace = ""
    try:
        reasoning_trace = run_escargot_reasoning(
            state["question"],
            answer_type="natural",
            num_strategies=2,
            timeout=60,
        )
        if reasoning_trace and "超时" not in reasoning_trace:
            steps[0]['done'] = True
            steps[0]['text'] = "深度推理完成"
            steps[0]['pct'] = 85
        else:
            reasoning_trace = ""
            steps[0]['done'] = True
            steps[0]['text'] = "深度推理：超时跳过"
            steps[0]['pct'] = 85
    except Exception as e:
        steps[0]['done'] = True
        steps[0]['text'] = "深度推理：跳过（异常）"
        steps[0]['pct'] = 85
        logger.warning(f"[reason] non-fatal: {e}")

    out.append(_progress_html(steps))
    return {"reasoning_trace": reasoning_trace, "output": out}


def node_generate(state: PipelineState) -> dict:
    """Node: 生成带引用的回答（流式收集）。"""
    steps = [{'text': '正在生成回答…', 'done': False, 'pct': 90}]
    out = [_progress_html(steps)]

    # 推理过程展示块
    thinking = _build_thinking_block(
        state["question_type"],
        state.get("chunks", []),
        state.get("kg_context", ""),
        state.get("reasoning_trace", ""),
    )
    if thinking:
        out.append(thinking)

    # 流式生成回答
    for piece in generate_answer_stream(
        question=state["question"],
        chunks=state.get("chunks", []),
        kg_context=state.get("kg_context", ""),
        reasoning_trace=state.get("reasoning_trace", ""),
    ):
        out.append(piece)

    return {"output": out}


def node_followup(state: PipelineState) -> dict:
    """Node: 生成后续推荐问题。"""
    # 从已有 output 中拼出回答摘要
    full_response = "".join(state.get("output", []))[-500:]
    out = []
    try:
        followups = generate_followup_questions(state["question"], full_response)
        followup_text = format_followup_block(followups)
        if followup_text:
            out.append(followup_text)
    except Exception as e:
        logger.warning(f"[followup] non-fatal: {e}")
    return {"output": out}


# ══════════════════════════════════════════════════════════════════
# 路由函数（Conditional Edge）
# ══════════════════════════════════════════════════════════════════

def route_after_supervisor(state: PipelineState) -> str:
    """根据 supervisor 决策结果路由。"""
    plan = state.get("agent_plan", [])
    idx = state.get("agent_plan_idx", 0)
    if idx >= len(plan):
        return "simple_chat"
    agent = plan[idx]
    if agent == "optimization":
        return "edu_optimization"
    if agent == "simple_chat":
        return "simple_chat"
    # knowledge_qa 和其他所有类型都走 RAG 路径
    return "translate"


def route_after_kg(state: PipelineState) -> str:
    """知识图谱之后：复杂问题走推理，否则直接生成。"""
    if is_complex(state["question_type"]) and state.get("chunks"):
        return "reason"
    return "generate"


# ══════════════════════════════════════════════════════════════════
# 构建 Graph
# ══════════════════════════════════════════════════════════════════

def build_graph() -> StateGraph:
    """构建教育版 LangGraph Pipeline（Phase 2: Supervisor 路由）。"""
    g = StateGraph(PipelineState)

    # 添加节点
    g.add_node("supervisor", node_supervisor)
    g.add_node("edu_optimization", node_edu_optimization)
    g.add_node("simple_chat", node_simple_chat)
    g.add_node("translate", node_translate)
    g.add_node("retrieve", node_retrieve)
    g.add_node("kg_lookup", node_kg_lookup)
    g.add_node("reason", node_reason)
    g.add_node("generate", node_generate)
    g.add_node("followup", node_followup)

    # 边：START → supervisor
    g.add_edge(START, "supervisor")

    # 条件边：supervisor 之后路由
    g.add_conditional_edges("supervisor", route_after_supervisor, {
        "edu_optimization": "edu_optimization",
        "simple_chat": "simple_chat",
        "translate": "translate",
    })

    # 终止边
    g.add_edge("edu_optimization", END)
    g.add_edge("simple_chat", END)

    # RAG 链：translate → retrieve → kg_lookup → (reason | generate) → followup → END
    g.add_edge("translate", "retrieve")
    g.add_edge("retrieve", "kg_lookup")
    g.add_conditional_edges("kg_lookup", route_after_kg, {
        "reason": "reason",
        "generate": "generate",
    })
    g.add_edge("reason", "generate")
    g.add_edge("generate", "followup")
    g.add_edge("followup", END)

    return g.compile()


# 全局编译一次
_graph = build_graph()


# ══════════════════════════════════════════════════════════════════
# 对外接口（保持与旧 pipeline.py 完全相同的签名）
# ══════════════════════════════════════════════════════════════════

async def process_question(question: str) -> AsyncGenerator[str, None]:
    """
    LangGraph 版 pipeline 入口。
    签名与旧版 pipeline.process_question 完全一致，
    FastAPI 端无需改动。
    """
    initial_state: PipelineState = {
        "question": question,
        "question_type": "",
        "agent_plan": [],
        "agent_plan_idx": 0,
        "supervisor_reasoning": "",
        "english_queries": [],
        "key_concepts": [],
        "chunks": [],
        "kg_context": "",
        "reasoning_trace": "",
        "output": [],
    }

    # 已经 yield 过的 output 数量（用于增量输出）
    yielded = 0

    # astream(mode="updates") 逐节点返回状态增量
    async for event in _graph.astream(initial_state, stream_mode="updates"):
        # event 是 dict: {node_name: {field: value, ...}}
        for node_name, updates in event.items():
            new_output = updates.get("output", [])
            for piece in new_output:
                yield piece
                await asyncio.sleep(0)

    logger.info("[pipeline] === COMPLETE ===")


# ══════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════

def _build_thinking_block(question_type, chunks, kg_context, reasoning_trace):
    """构建推理过程展示块（与旧版一致）。"""
    lines = ["> **推理过程**", ">"]
    type_labels = {
        "factual": "事实查询", "process": "工艺流程",
        "comparison": "对比分析", "causal": "因果推理",
        "recommendation": "方案推荐",
    }
    lines.append(f"> **问题类型：** {type_labels.get(question_type, question_type)}")
    lines.append(">")
    if chunks:
        lines.append(f"> **检索到 {len(chunks)} 条相关文献片段：**")
        for i, c in enumerate(chunks[:5], 1):
            score_pct = f"{c.score:.0%}" if c.score <= 1 else f"{c.score:.2f}"
            lines.append(f"> - [{i}] {c.title[:60]} ({c.year or '?'}) -- 相关度 {score_pct}")
        if len(chunks) > 5:
            lines.append(f"> - ... 及其他 {len(chunks) - 5} 条")
        lines.append(">")
    if kg_context:
        lines.append("> **知识图谱关联：**")
        for kg_line in kg_context.split("\n"):
            lines.append(f"> {kg_line}")
        lines.append(">")
    if reasoning_trace:
        lines.append("> **深度推理 (ESCARGOT)：**")
        for rt_line in reasoning_trace.split("\n"):
            lines.append(f"> {rt_line}")
        lines.append(">")
    lines.append("\n---\n\n")
    return "\n".join(lines)
