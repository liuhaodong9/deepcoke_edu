"""
DeepCoke 教育版 Pipeline — LangGraph StateGraph 实现
Phase 1: LangGraph 替换手写路由
Phase 2: Supervisor LLM 智能路由 + 多 agent 串行
"""
import logging
import asyncio
import operator
import re
import json as _json   # LITQA_DICT_REFS/META 用;node_structured_lookup 无局部导入,提到模块级兜底
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
# ESCARGOT 推理模块已移除 (2026-06-06),agent_loop 已覆盖多步推理
from .term_fix import fix_terms

logger = logging.getLogger("deepcoke.pipeline")


# ══════════════════════════════════════════════════════════════════
# State 定义
# ══════════════════════════════════════════════════════════════════

class PipelineState(TypedDict):
    """LangGraph 流转状态。output 用 operator.add 累加，每个节点追加输出片段。"""
    question: str
    # 多轮对话历史: [{"user_message": "...", "bot_response": "..."}],按时间顺序老的在前
    history: list
    question_type: str
    # Supervisor 多 agent 计划（Phase 2）
    agent_plan: list[str]
    agent_plan_idx: int
    supervisor_reasoning: str
    # RAG 中间结果
    english_queries: list[str]
    key_concepts: list[str]
    constraints: dict         # ⑩ 多轮约束(year_after / exclude_doctypes),跨轮从 history 重扫累积
    mode: str                 # 玻尔-A 回答模式: qa/discovery/review/compare
    chunks: list              # RetrievedChunk 列表
    kg_context: str
    structured_evidence: str  # 结构化字典命中（Markdown 表）；未命中为 ""
    reasoning_trace: str
    # 累计输出（每个节点 append 新的片段）
    output: Annotated[list[str], operator.add]


# ══════════════════════════════════════════════════════════════════
# 进度条辅助（与原版一致）
# ══════════════════════════════════════════════════════════════════

def _progress_html(steps: list[dict]) -> str:
    """将进度步骤拼成 HTML 块。

    UI 约定(前端 MainDia.vue CSS 配套):
    - pending 状态:不发 ⏳ 字符,前端 ::before 渲染旋转 spinner
    - done 状态:发 ✅ 字符
    - 进度条 bar / 百分比文字仍发出但前端 CSS 隐藏(保留 DOM 兼容)
    """
    lines = ['<div class="pipeline-progress">']
    for step in steps:
        if step.get('done'):
            lines.append(f'<div class="progress-step done">✅ {step["text"]}</div>')
        else:
            lines.append(f'<div class="progress-step pending">{step["text"]}</div>')
    total = len(steps)
    done_count = sum(1 for s in steps if s.get('done'))
    pct = steps[-1].get('pct', int(done_count / max(total, 1) * 100)) if steps else 0
    is_complete = pct >= 100
    bar_class = 'progress-bar-complete' if is_complete else ''
    lines.append('<div class="progress-bar-wrap">')
    lines.append(f'<div class="progress-bar-fill {bar_class}" style="width:{pct}%"></div>')
    lines.append('</div>')
    if is_complete:
        lines.append('<div class="progress-pct-done">✅ 完成</div>')
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

    steps = [{'text': '正在分析问题…', 'done': False, 'pct': 5}]
    out = [_progress_html(steps)]

    decision = supervisor_decide(question)
    agent_plan = decision["agents"]
    reasoning = decision["reasoning"]

    # 映射 agent 名 → question_type
    agent_to_type = {
        "optimization": "optimization",
        "knowledge_qa": "factual",  # 触发 RAG 路径
        "literature_qa": "literature_qa",  # 触发两阶段文献检索
        "simple_chat": "general_chat",
    }
    first_agent = agent_plan[0] if agent_plan else "knowledge_qa"
    question_type = agent_to_type.get(first_agent, "factual")
    # knowledge_qa 可能映射到更具体的类型（factual/comparison/causal 等）
    # 但教育版不需要区分，统一走 RAG

    agent_labels = {
        "optimization": "配煤优化", "knowledge_qa": "知识问答",
        "literature_qa": "文献综述",
        "simple_chat": "闲聊", "coal_price": "煤价查询",
        "data_management": "数据管理", "oven_control": "焦炉操作",
    }
    plan_display = " → ".join(agent_labels.get(a, a) for a in agent_plan)
    steps[0]['done'] = True
    steps[0]['text'] = f"已识别：{plan_display}"
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
        "你是高校智慧化工软件平台 DeepResearch，由苏州龙泰氢一能源科技有限公司研发。"
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


def node_literature_qa(state: PipelineState) -> dict:
    """Node: 两阶段文献检索(papers_cards → coking_papers) + 流式回答 + 引用追加。"""
    from .literature_qa import service as litqa
    from .llm_client import chat as llm_chat

    question = state["question"]
    out = []

    # 阶段 0: 中→英查询翻译(向量库 BGE 是英文模型,中文 query 直接查会语义飘移)
    # translate_query 返回 1-3 个英文候选:[0] 是术语词典预替换的精确版本,
    # [1][2] 是 LLM paraphrase 的多角度版本。下面 stage1/2 对每个候选都召回再合并。
    pre = [{'text': '阶段 0/3：翻译检索语句…', 'done': False, 'pct': 10}]
    out.append(_progress_html(pre))
    try:
        translated = translate_query(question)
        en_queries = translated.get("english_queries") or [question]
        key_concepts = translated.get("key_concepts") or []
    except Exception as e:
        logger.warning(f"[literature_qa] 翻译失败,回落到原文 query: {e}")
        en_queries = [question]
        key_concepts = []
    en_query_head = en_queries[0]
    pre[0]['done'] = True
    pre[0]['text'] = (
        f"翻译完成 → {len(en_queries)} 个候选,首选 {en_query_head[:40]}"
        f"{'…' if len(en_query_head) > 40 else ''}"
    )
    pre[0]['pct'] = 18
    out.append(_progress_html(pre))

    # 阶段 1: 卡片库定位 — 对每个 en_query 召回再合并(paper_id 去重,score 取 max)
    # 同时记录 per-query 召回轨迹,给前端知识图谱"EnglishQuery → Paper"边用
    steps = [{'text': f'阶段 1/3:用 {len(en_queries)} 个查询定位相关 paper…', 'done': False, 'pct': 25}]
    out.append(_progress_html(steps))
    papers_by_pid = {}
    query_recalls: list[dict] = []
    try:
        for q in en_queries:
            recalled = litqa._retrieve_papers(q, n=litqa.DEFAULT_N_PAPERS)
            query_recalls.append({
                "query": q,
                "papers": [
                    {"paper_id": p.paper_id, "score": round(float(p.score), 3)}
                    for p in recalled
                ],
            })
            for p in recalled:
                cur = papers_by_pid.get(p.paper_id)
                if cur is None or p.score > cur.score:
                    papers_by_pid[p.paper_id] = p
    except Exception as e:
        logger.error(f"[literature_qa] 卡片库检索失败: {e}")
        out.append(
            f"\n> ⚠️ 文献卡片库尚未就绪（{e}）。请先在后端目录运行：\n"
            f"> `python -X utf8 -m deepcoke.literature_qa.build_cards`\n"
        )
        return {"output": out}

    if not papers_by_pid:
        out.append("\n> 文献卡片库未命中相关 paper。\n")
        return {"output": out}

    papers = sorted(papers_by_pid.values(), key=lambda p: -p.score)[:litqa.DEFAULT_N_PAPERS]
    steps[0]['done'] = True
    steps[0]['text'] = f"定位到 {len(papers)} 篇相关文献(多 query 合并)"
    steps[0]['pct'] = 40
    out.append(_progress_html(steps))

    # 阶段 2: 限定 paper_id 在 chunk 库取证(对每个 en_query 召回再合并)
    steps2 = [{'text': '阶段 2/3:在命中文献内检索证据片段…', 'done': False, 'pct': 50}]
    out.append(_progress_html(steps2))
    paper_ids = [p.paper_id for p in papers]
    papers_by_id = {p.paper_id: p for p in papers}
    # dense + reranker 用英文 query,BM25 用中文原句(jieba 分词,与英文 dense 互补)
    # 对每个 en_query 跑一次,按 chunk_id 去重、score 取 max,丰富多角度证据
    chunks_by_id = {}
    for q in en_queries:
        for c in litqa._retrieve_chunks_hybrid(
            q, paper_ids, k=litqa.DEFAULT_K_CHUNKS, bm25_query=question
        ):
            cur = chunks_by_id.get(c.chunk_id)
            if cur is None or c.score > cur.score:
                chunks_by_id[c.chunk_id] = c
    # 多 query 合并后再做一次 per-paper 多样化(单 query 内 _retrieve_chunks_hybrid
    # 已限 PER_PAPER,但多 query 合并去重时不同 chunk_id 同 paper_id 不去重,
    # 需要在 pipeline 层再压一次,确保 LLM 看到的 chunks 跨多篇 paper 分布)
    sorted_chunks = sorted(chunks_by_id.values(), key=lambda c: -c.score)
    chunks = litqa._topk_per_paper(sorted_chunks, litqa.DEFAULT_K_CHUNKS, litqa.PER_PAPER_CHUNKS)
    for c in chunks:
        c.paper = papers_by_id.get(c.paper_id)

    if not chunks:
        out.append("\n> 文献已定位但相应 chunk 不在向量库中。\n")
        return {"output": out}

    steps2[0]['done'] = True
    steps2[0]['text'] = f"取到 {len(chunks)} 段证据(来自 {len({c.paper_id for c in chunks})} 篇)"
    steps2[0]['pct'] = 60
    out.append(_progress_html(steps2))

    # ── 嵌入结构化 metadata 给前端(用 HTML 注释藏起来,前端解析) ──
    import json as _json
    cited_paper_ids = {c.paper_id for c in chunks}
    meta_payload = {
        "question": question,
        "english_queries": en_queries,
        "key_concepts": key_concepts,
        "papers": [
            {
                "paper_id": p.paper_id,
                "title": p.title,
                "authors": p.authors,
                "year": p.year,
                "category": p.category,
                "journal": p.journal,
                "score": round(p.score, 3),
                "cited": p.paper_id in cited_paper_ids,
            }
            for p in papers
        ],
        "chunks": [
            {
                "ref": idx,
                "chunk_id": c.chunk_id,
                "paper_id": c.paper_id,
                "section": c.section,
                "score": round(c.score, 3),
                "text": (c.text or "")[:1500],
            }
            for idx, c in enumerate(chunks, 1)
        ],
        "query_recalls": query_recalls,
    }
    out.append(f"<!--LITQA_META:{_json.dumps(meta_payload, ensure_ascii=False)}-->\n")

    # 阶段 2.5: 结构化字典查询（NL→SQL 命中 coal_samples / coke_experiments / carbon_microstructure）
    structured_md = ""
    structured_rows = 0
    try:
        from .literature_qa.quant_query import lookup_structured
        sl = lookup_structured(question)
        if sl.get("hit"):
            structured_md = sl.get("markdown") or ""
            structured_rows = len(sl.get("rows") or [])
        logger.info(
            f"[litqa] structured_lookup hit={sl.get('hit')} rows={structured_rows} "
            f"sql={(sl.get('sql') or '')[:120]} err={sl.get('error', '')}"
        )
    except Exception as e:
        logger.warning(f"[litqa] structured_lookup non-fatal: {e}")

    if structured_md:
        out.append(
            "<details class=\"structured-evidence\" open><summary>📊 结构化字典命中（"
            f"{structured_rows} 条记录）</summary>\n\n"
            + structured_md
            + "\n\n</details>\n\n"
        )

    # 阶段 3: LLM 流式生成回答(自动判定 list/compare/normal mode)
    prompt, mode = litqa.build_prompt(question, chunks, papers_by_id)
    # 字典命中时，把表前置到 prompt 顶部（最高优先级证据）
    if structured_md:
        prompt = (
            "【结构化字典 — 最高优先级证据】\n"
            "下面是从文献抽取的精确数值表。请优先引用这些数值；表中没有覆盖的方面再用下方文献片段补充。\n\n"
            f"{structured_md}\n\n"
            + "─" * 40 + "\n\n"
            + prompt
        )
    mode_label = {
        'list': '文献清单模式',
        'compare': '综述/对比模式',
        'normal': '基于文献片段',
    }.get(mode, '基于文献片段')
    if structured_md:
        mode_label += " + 结构化字典"
    steps3 = [{'text': f'阶段 3/3：{mode_label}生成回答…', 'done': False, 'pct': 70}]
    out.append(_progress_html(steps3))

    answer_parts = []
    stream = llm_chat([{"role": "user", "content": prompt}], stream=True)
    # 维护 tail buffer(保留末 20 字)防止术语跨 piece 边界被切碎,
    # 然后对 yield 出去的部分做术语兜底替换(fix_terms)
    _fix_buf = ""
    _BUF_TAIL = 20
    for ch in stream:
        if not getattr(ch, "choices", None):
            continue
        piece = getattr(ch.choices[0].delta, "content", None)
        if piece:
            answer_parts.append(piece)
            _fix_buf += piece
            if len(_fix_buf) > _BUF_TAIL:
                to_yield = fix_terms(_fix_buf[:-_BUF_TAIL])
                _fix_buf = _fix_buf[-_BUF_TAIL:]
                if to_yield:
                    out.append(to_yield)
    # 流结束:剩余 buffer 也 fix 后 yield
    if _fix_buf:
        out.append(fix_terms(_fix_buf))

    # 追加文献引用清单
    full_answer = fix_terms("".join(answer_parts))
    cited = litqa._collect_cited_indices(full_answer, len(chunks))
    appendix = litqa._build_appendix(chunks, cited)
    if appendix:
        out.append("\n\n" + appendix)

    return {"output": out}


def node_simple_chat(state: PipelineState) -> dict:
    """Node: 闲聊（不走 RAG）。"""
    from .llm_client import chat

    system_prompt = (
        "你是高校智慧化工软件平台 DeepResearch，由苏州龙泰氢一能源科技有限公司研发。"
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


def _extract_constraints(history: list, question: str) -> dict:
    """⑩ 从多轮历史+当前问题里抽硬约束(year_after / 排除综述)。
    无状态:每轮重扫所有用户消息累积,故"两轮前说的排除综述"这轮仍生效。
    保守正则,只在明确表述时触发,避免误伤召回。"""
    texts = [question or ""]
    for h in history or []:
        u = h.get("user_message") or h.get("content") or h.get("text") or ""
        if u:
            texts.append(u)
    blob = " ".join(texts)
    cons: dict = {}

    # year_after: "2020年以后/之后/后" / "after 2020" / "since 2020"(取最大下限)
    years = [int(m.group(1)) for m in re.finditer(r"(20\d{2})\s*年?\s*(?:以|之)?后", blob)]
    years += [int(m.group(1)) for m in re.finditer(r"(?:after|since)\s*(20\d{2})", blob, re.I)]
    if years:
        cons["year_after"] = max(years)

    # 排除综述 / 只要实验论文
    if (re.search(r"排除综述|不要综述|不看综述|去掉综述|exclude\s+review|no\s+reviews?", blob, re.I)
            or re.search(r"只(?:要|看|保留)\s*(?:原始|实验|原创)\s*(?:论文|文献|研究)"
                         r"|(?:experimental|original)\s+(?:papers?|studies)\s+only"
                         r"|only\s+experimental", blob, re.I)):
        cons["exclude_doctypes"] = ["review"]

    return cons


def node_translate(state: PipelineState) -> dict:
    """Node: 关键词提取 + 翻译检索语句。"""
    steps = [{'text': '正在提取关键词并翻译检索语句…', 'done': False, 'pct': 15}]
    out = [_progress_html(steps)]

    history = state.get("history") or []
    translated = translate_query(state["question"], history=history)
    english_queries = translated["english_queries"]
    key_concepts = translated["key_concepts"]
    resolved = translated.get("resolved_question") or state["question"]

    steps[0]['done'] = True
    steps[0]['text'] = f"关键词：{', '.join(key_concepts[:5])}"
    steps[0]['pct'] = 25
    out.append(_progress_html(steps))

    if resolved != state["question"]:
        logger.info(
            f"[translate] resolved={resolved!r} queries={english_queries}, concepts={key_concepts}"
        )
    else:
        logger.info(f"[translate] queries={english_queries}, concepts={key_concepts}")
    constraints = _extract_constraints(history, state["question"])
    if constraints:
        logger.info(f"[constraints] 多轮约束: {constraints}")
    out_state = {
        "english_queries": english_queries,
        "key_concepts": key_concepts,
        "constraints": constraints,
        "output": out,
    }
    # 跨轮补全:把 state["question"] 替换成 resolved_question,
    # 下游 generate 节点用补全后的版本(LLM 才能理解 "它/他" 指什么)
    if resolved and resolved != state["question"]:
        out_state["question"] = resolved
    return out_state


def node_retrieve(state: PipelineState) -> dict:
    """Node: 向量数据库检索。"""
    steps = [{'text': '正在检索文献数据库…', 'done': False, 'pct': 30}]
    out = [_progress_html(steps)]

    all_chunks: list[RetrievedChunk] = []
    # per-query 召回轨迹:记录每个 english_query 召回的 papers + scores,
    # 给前端知识图谱可视化"检索链路"用(EnglishQuery → Paper 边)
    query_recalls: list[dict] = []
    for eq in state["english_queries"]:
        chunks = retrieve(eq, top_k=5)
        all_chunks.extend(chunks)
        per_paper_score: dict[int, float] = {}
        for c in chunks:
            if c.paper_id is None:
                continue
            cur = per_paper_score.get(c.paper_id)
            if cur is None or c.score > cur:
                per_paper_score[c.paper_id] = float(c.score)
        query_recalls.append({
            "query": eq,
            "papers": [
                {"paper_id": pid, "score": round(s, 3)}
                for pid, s in sorted(per_paper_score.items(), key=lambda x: -x[1])
            ],
        })

    # 去重：按 (paper_id, chunk_index) 保留最高分
    seen = {}
    for c in all_chunks:
        key = (c.paper_id, c.chunk_index)
        if key not in seen or c.score > seen[key].score:
            seen[key] = c
    # Section 权重 reweighting:让 Methods/Results 优于 Abstract/Preamble/References
    # (复用 literature_qa.service 里的 _section_weight,统一权重表)
    from .literature_qa.service import _section_weight
    for c in seen.values():
        c.score = c.score * _section_weight(getattr(c, "section", "") or "")
    sorted_chunks = sorted(seen.values(), key=lambda x: x.score, reverse=True)
    # Per-paper 多样化:每篇 paper 最多 2 chunks,保证跨文献覆盖
    # (类 NotebookLM/PaperQA2 思路)
    PER_PAPER = 2
    K_TOTAL = 10
    count_per_pid: dict = {}
    all_chunks = []
    for c in sorted_chunks:
        if count_per_pid.get(c.paper_id, 0) >= PER_PAPER:
            continue
        all_chunks.append(c)
        count_per_pid[c.paper_id] = count_per_pid.get(c.paper_id, 0) + 1
        if len(all_chunks) >= K_TOTAL:
            break

    steps[0]['done'] = True
    steps[0]['text'] = f"检索到 {len(all_chunks)} 条相关文献片段"
    steps[0]['pct'] = 45
    out.append(_progress_html(steps))

    # 输出结构化 metadata 给前端,触发知识图谱渲染
    # (knowledge_qa 路径也产 LITQA_META,字段与 literature_qa 对齐)
    import json as _json
    papers_by_id: dict[int, dict] = {}
    for c in all_chunks:
        pid = c.paper_id
        if pid is None:
            continue
        cur = papers_by_id.get(pid)
        if cur is None or c.score > cur["score"]:
            authors_val = c.authors
            if isinstance(authors_val, list):
                authors_str = ", ".join(str(a) for a in authors_val)
            else:
                authors_str = str(authors_val or "")
            papers_by_id[pid] = {
                "paper_id": pid,
                "title": c.title or "",
                "authors": authors_str,
                "year": int(c.year) if c.year else 0,
                "category": c.category or "",
                "journal": "",
                "score": round(float(c.score), 3),
                "cited": True,
            }
    papers_list = sorted(papers_by_id.values(), key=lambda p: -p["score"])
    chunks_meta = [
        {
            "ref": i + 1,
            "chunk_id": f"{c.paper_id}_{c.chunk_index}",
            "paper_id": c.paper_id,
            "section": c.section or "",
            "score": round(float(c.score), 3),
            "text": (getattr(c, "text", "") or "")[:1500],
        }
        for i, c in enumerate(all_chunks)
    ]
    meta_payload = {
        "question": state["question"],
        "english_queries": state["english_queries"],
        "key_concepts": state.get("key_concepts", []),
        "papers": papers_list,
        "chunks": chunks_meta,
        "query_recalls": query_recalls,
    }
    out.append(f"<!--LITQA_META:{_json.dumps(meta_payload, ensure_ascii=False)}-->\n")

    logger.info(f"[retrieve] {len(all_chunks)} unique chunks, {len(papers_list)} papers, "
                f"{len(query_recalls)} query recalls in meta")
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


def node_structured_lookup(state: PipelineState) -> dict:
    """Node: 结构化字典查询（NL→SQL 命中 coal_samples / coke_experiments / carbon_microstructure）。

    命中时把 Markdown 表注入 structured_evidence，下游 generate 优先引用。
    未命中或异常时静默跳过，pipeline 照常走 RAG 路径。
    """
    from .literature_qa.quant_query import lookup_structured

    steps = [{'text': '正在查询结构化字典…', 'done': False, 'pct': 62}]
    out = [_progress_html(steps)]

    structured_evidence = ""
    hit_rows = 0
    dict_refs = []   # [{ref, paper_id, title, quote}] 字典论文登记为正式引用,续 RAG 编号
    try:
        result = lookup_structured(state["question"])
        if result.get("hit"):
            structured_evidence = result.get("markdown", "") or ""
            hit_rows = len(result.get("rows") or [])
            # 字典命中的不重复论文 → 接着 RAG 的 [1..N] 续号 [N+1..],供正文 [N] 点击溯源
            rag_n = len(state.get("agent_papers_meta") or [])
            for i, dp in enumerate(result.get("dict_papers") or []):
                if dp.get("paper_id") and dp.get("quote"):
                    dict_refs.append({
                        "ref": rag_n + 1 + i, "paper_id": dp["paper_id"],
                        "title": dp.get("title") or "", "quote": dp["quote"],
                    })
        logger.info(
            f"[structured_lookup] hit={result.get('hit')} rows={hit_rows} "
            f"dict_refs={len(dict_refs)} sql={(result.get('sql') or '')[:100]} err={result.get('error', '')}"
        )
    except Exception as e:
        logger.warning(f"[structured_lookup] non-fatal: {e}")

    # 给 LLM 一份编号的字典来源,引导它引用字典数值时用这些 [N](而非乱编)
    if structured_evidence and dict_refs:
        src = " · ".join(f"[{d['ref']}] {d['title']}" for d in dict_refs)
        structured_evidence = structured_evidence + f"\n\n字典数据来源(引用字典数值时用对应编号): {src}"

    if structured_evidence:
        steps[0]['text'] = f"结构化字典：命中 {hit_rows} 条记录"
    else:
        steps[0]['text'] = "结构化字典：未命中（走 RAG 文献证据）"
    steps[0]['done'] = True
    steps[0]['pct'] = 65
    out.append(_progress_html(steps))

    # 字典引用映射给前端:正文 [N](N≥RAG数+1)渲染成 quant-cite,用 quote 在 PDF 高亮
    if dict_refs:
        refs_map = {d["ref"]: {"paper_id": d["paper_id"], "quote": d["quote"], "title": d["title"]}
                    for d in dict_refs}
        out.append(f"<!--LITQA_DICT_REFS:{_json.dumps(refs_map, ensure_ascii=False)}-->\n")

    return {"structured_evidence": structured_evidence, "output": out}


def node_reason(state: PipelineState) -> dict:
    """Node: 已废弃 — ESCARGOT 推理移除后变成 no-op pass-through。
    保留节点接口避免破坏 LangGraph edges。enhanced_pipeline 路径根本不会到这里。"""
    return {"reasoning_trace": "", "output": []}


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

    # 结构化字典命中时，前置一个可见的"字典证据"展开块
    structured_evidence = state.get("structured_evidence", "") or ""
    if structured_evidence:
        out.append(
            "<details class=\"structured-evidence\"><summary>📊 结构化字典命中</summary>\n\n"
            + structured_evidence
            + "\n\n</details>\n\n"
        )

    # 流式生成回答(用 tail buffer 防术语跨 piece 切碎,piece-level 兜底替换)
    _fix_buf = ""
    _BUF_TAIL = 20
    for piece in generate_answer_stream(
        question=state["question"],
        chunks=state.get("chunks", []),
        kg_context=state.get("kg_context", ""),
        reasoning_trace=state.get("reasoning_trace", ""),
        structured_evidence=structured_evidence,
        mode=state.get("mode", "qa"),
    ):
        _fix_buf += piece
        if len(_fix_buf) > _BUF_TAIL:
            to_yield = fix_terms(_fix_buf[:-_BUF_TAIL])
            _fix_buf = _fix_buf[-_BUF_TAIL:]
            if to_yield:
                out.append(to_yield)
    if _fix_buf:
        out.append(fix_terms(_fix_buf))

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
    if agent == "literature_qa":
        return "literature_qa"
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
    g.add_node("literature_qa", node_literature_qa)
    g.add_node("translate", node_translate)
    g.add_node("retrieve", node_retrieve)
    g.add_node("kg_lookup", node_kg_lookup)
    g.add_node("structured_lookup", node_structured_lookup)
    g.add_node("reason", node_reason)
    g.add_node("generate", node_generate)
    g.add_node("followup", node_followup)

    # 边：START → supervisor
    g.add_edge(START, "supervisor")

    # 条件边：supervisor 之后路由
    g.add_conditional_edges("supervisor", route_after_supervisor, {
        "edu_optimization": "edu_optimization",
        "simple_chat": "simple_chat",
        "literature_qa": "literature_qa",
        "translate": "translate",
    })

    # 终止边
    g.add_edge("edu_optimization", END)
    g.add_edge("simple_chat", END)
    g.add_edge("literature_qa", END)

    # RAG 链：translate → retrieve → kg_lookup → structured_lookup → (reason | generate) → followup → END
    g.add_edge("translate", "retrieve")
    g.add_edge("retrieve", "kg_lookup")
    g.add_edge("kg_lookup", "structured_lookup")
    g.add_conditional_edges("structured_lookup", route_after_kg, {
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

async def process_question(question: str, history: list | None = None, mode: str = "qa") -> AsyncGenerator[str, None]:
    """
    LangGraph 版 pipeline 入口。
    Args:
        question: 用户当前问题
        history: 多轮对话历史(可选,用于 query 跨轮补全)
        mode: 玻尔-A 回答模式(qa/discovery/review/compare)
    """
    initial_state: PipelineState = {
        "question": question,
        "history": history or [],
        "mode": mode or "qa",
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
    """构建推理过程展示块:可折叠 <details>(纯 HTML,渲染干净,不再用 markdown 引用避免裸 >)。"""
    import html as _html
    type_labels = {
        "factual": "事实查询", "process": "工艺流程",
        "comparison": "对比分析", "causal": "因果推理",
        "recommendation": "方案推荐",
    }
    parts = [f"<b>问题类型:</b> {type_labels.get(question_type, question_type)}"]

    # 跳过合成的 Fulltext Evidence Pack 占位(section=FulltextEvidence / chunk_index=-4),
    # 它不是真 chunk,否则会显示 "[1] Fulltext Evidence Pack (?)" 这种没意义的行
    real = [c for c in (chunks or [])
            if getattr(c, "section", "") != "FulltextEvidence" and getattr(c, "chunk_index", 0) != -4]
    if real:
        lis = []
        for i, c in enumerate(real[:5], 1):
            score_pct = f"{c.score:.0%}" if c.score <= 1 else f"{c.score:.2f}"
            title = _html.escape((c.title or "")[:60])
            lis.append(f"<li>[{i}] {title} ({c.year or '?'}) — 相关度 {score_pct}</li>")
        if len(real) > 5:
            lis.append(f"<li>… 及其他 {len(real) - 5} 条</li>")
        parts.append(f"<b>检索到 {len(real)} 条相关文献片段:</b><ul>{''.join(lis)}</ul>")
    if kg_context:
        parts.append("<b>知识图谱关联:</b><br>" + _html.escape(kg_context).replace("\n", "<br>"))
    if reasoning_trace:
        parts.append("<b>深度推理 (ESCARGOT):</b><br>" + _html.escape(reasoning_trace).replace("\n", "<br>"))

    body = "<br>".join(parts)
    return (
        '<details class="deep-think">\n'
        '<summary>💭 推理过程</summary>\n'
        f'<div class="deep-think-body">{body}</div>\n'
        '</details>\n\n'
    )
