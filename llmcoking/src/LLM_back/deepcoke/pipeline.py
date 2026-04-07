"""
Main pipeline orchestrator for DeepCoke.
Routes questions through classification → retrieval → reasoning → generation → follow-up.
"""
import logging
import asyncio
from typing import AsyncGenerator

from .classifier.question_classifier import classify_question, is_complex, needs_rag
from .classifier.query_translator import translate_query
from .vectorstore.retriever import retrieve, RetrievedChunk
from .knowledge_graph.neo4j_client import query_kg_with_llm, find_related_papers
from .generation.answer_generator import generate_answer_stream, build_evidence_context
from .followup.followup_generator import generate_followup_questions, format_followup_block
from .reasoning.escargot_runner import run_escargot_reasoning
from .coal_agent.agent_runner import run_agent as run_coal_agent

logger = logging.getLogger("deepcoke.pipeline")


async def process_question(question: str) -> AsyncGenerator[str, None]:
    """
    Main pipeline: process a user question and yield streaming response chunks.

    This is an async generator that yields text pieces for streaming to the frontend,
    preserving the same streaming contract as the original /chat/ endpoint.

    Pipeline:
    1. Classify question type
    2. Translate to English queries (if domain question)
    3. Retrieve from vector DB + knowledge graph
    4. Route to simple RAG or ESCARGOT reasoning
    5. Generate evidence-driven answer with citations
    6. Append follow-up questions
    """
    # ── 进度提示辅助 ─────────────────────────────────────────────
    # 用 HTML 进度条实时展示推理链进度
    _progress_steps: list[dict] = []   # [{text, done, pct}]

    def _progress_html() -> str:
        """将当前进度步骤拼成带进度条的 HTML 块。"""
        lines = ['<div class="pipeline-progress">']
        for i, step in enumerate(_progress_steps):
            icon = '✅' if step.get('done') else '⏳'
            lines.append(f'<div class="progress-step">{icon} {step["text"]}</div>')
        # 计算总进度
        total = len(_progress_steps)
        done_count = sum(1 for s in _progress_steps if s.get('done'))
        pct = _progress_steps[-1].get('pct', int(done_count / max(total, 1) * 100)) if _progress_steps else 0
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

    def _add_progress(text: str, pct: int = 0) -> None:
        _progress_steps.append({'text': text, 'done': False, 'pct': pct})

    def _finish_last(text: str = None, pct: int = None) -> None:
        if _progress_steps:
            _progress_steps[-1]['done'] = True
            if text:
                _progress_steps[-1]['text'] = text
            if pct is not None:
                _progress_steps[-1]['pct'] = pct

    # ── Step 1: Classify ─────────────────────────────────────────
    print(f"[PIPELINE] Step 1: Classifying question: {question[:50]}", flush=True)
    _add_progress("正在分析问题类型…", pct=5)
    yield _progress_html()
    await asyncio.sleep(0)

    try:
        question_type = classify_question(question)
    except Exception as e:
        print(f"[PIPELINE] Step 1 FAILED: {e}", flush=True)
        yield f"Pipeline error at classification: {e}"
        return

    type_labels = {
        "optimization": "配煤优化", "factual": "事实查询", "process": "工艺流程",
        "comparison": "对比分析", "causal": "因果推理",
        "recommendation": "方案推荐",
    }
    _finish_last(f"问题类型：{type_labels.get(question_type, question_type)}", pct=10)
    print(f"[PIPELINE] Step 1 done: type={question_type}, needs_rag={needs_rag(question_type)}", flush=True)

    # ── 教育版：配煤优化降级为普通问答 ─────────────────────────────
    if question_type == "optimization":
        print("[PIPELINE] -> edu mode: optimization downgraded to simple chat", flush=True)
        _finish_last("问题类型：配煤相关（教育版仅支持知识问答）", pct=100)
        yield _progress_html()
        yield "\n> 💡 **教育版暂不支持配煤优化计算，已转为知识问答模式。如需配煤优化功能请使用企业版。**\n\n"
        async for chunk in _simple_chat(question):
            yield chunk
        return

    if False and question_type == "optimization":
        # 以下为配煤优化 Agent 代码（教育版已禁用）
        print("[PIPELINE] -> coal optimization agent", flush=True)
        _finish_last("问题类型：配煤优化/质量预测", pct=10)
        _add_progress("启动配煤优化 Agent…", pct=15)
        yield _progress_html()
        await asyncio.sleep(0)

        # 用队列接收 agent 的进度回调
        progress_q: asyncio.Queue = asyncio.Queue()

        def _on_agent_progress(step, total, desc):
            pct = int(step / total * 100) if total > 0 else 0
            progress_q.put_nowait((pct, desc))

        # 在线程中运行 agent
        agent_task = asyncio.get_event_loop().run_in_executor(
            None, lambda: run_coal_agent(question, on_progress=_on_agent_progress)
        )

        # 轮询进度队列，实时推送给前端
        while not agent_task.done():
            try:
                pct, desc = await asyncio.wait_for(progress_q.get(), timeout=0.3)
                # 映射 agent 内部进度到总进度 15%~95%
                mapped_pct = 15 + int(pct * 0.8)
                _progress_steps[-1]['text'] = desc
                _progress_steps[-1]['pct'] = mapped_pct
                yield _progress_html()
            except asyncio.TimeoutError:
                pass

        # 取剩余的进度消息
        while not progress_q.empty():
            pct, desc = progress_q.get_nowait()
            mapped_pct = 15 + int(pct * 0.8)
            _progress_steps[-1]['text'] = desc
            _progress_steps[-1]['pct'] = mapped_pct

        try:
            answer = agent_task.result()
        except Exception as e:
            logger.error(f"Coal agent failed: {e}")
            answer = f"配煤优化 Agent 出错: {e}"

        _finish_last("配煤优化 Agent 完成", pct=100)
        yield _progress_html()
        yield "\n---\n\n"
        yield answer
        return

    if not needs_rag(question_type):
        # General chat — pass through to simple LLM response
        print("[PIPELINE] -> simple chat (no RAG)", flush=True)
        # 清掉进度块，直接输出回答
        yield "\r\n"
        async for chunk in _simple_chat(question):
            yield chunk
        return

    # ── Step 2: Translate query ──────────────────────────────────
    print("[PIPELINE] Step 2: Translating query...", flush=True)
    _add_progress("正在提取关键词并翻译检索语句…", pct=15)
    yield _progress_html()
    await asyncio.sleep(0)

    try:
        translated = translate_query(question)
        english_queries = translated["english_queries"]
        key_concepts = translated["key_concepts"]
    except Exception as e:
        print(f"[PIPELINE] Step 2 FAILED: {e}", flush=True)
        yield f"Pipeline error at translation: {e}"
        return
    _finish_last(f"关键词：{', '.join(key_concepts[:5])}", pct=25)
    print(f"[PIPELINE] Step 2 done: queries={english_queries}, concepts={key_concepts}", flush=True)

    # ── Step 3: Retrieve evidence ────────────────────────────────
    print("[PIPELINE] Step 3: Retrieving from vector DB...", flush=True)
    _add_progress("正在检索文献数据库…", pct=30)
    yield _progress_html()
    await asyncio.sleep(0)

    all_chunks: list[RetrievedChunk] = []
    try:
        for eq in english_queries:
            chunks = retrieve(eq, top_k=5)
            all_chunks.extend(chunks)
    except Exception as e:
        print(f"[PIPELINE] Step 3 FAILED: {e}", flush=True)
        yield f"Pipeline error at retrieval: {e}"
        return

    # Deduplicate by (paper_id, chunk_index) keeping highest score
    seen = {}
    for c in all_chunks:
        key = (c.paper_id, c.chunk_index)
        if key not in seen or c.score > seen[key].score:
            seen[key] = c
    all_chunks = sorted(seen.values(), key=lambda x: x.score, reverse=True)[:10]
    _finish_last(f"检索到 {len(all_chunks)} 条相关文献片段", pct=45)
    print(f"[PIPELINE] Step 3 done: {len(all_chunks)} unique chunks", flush=True)

    # ── Step 3b: Knowledge graph context ─────────────────────────
    print("[PIPELINE] Step 3b: Querying knowledge graph...", flush=True)
    _add_progress("正在查询知识图谱…", pct=50)
    yield _progress_html()
    await asyncio.sleep(0)

    kg_context = ""
    try:
        kg_results = []
        for concept in key_concepts[:3]:
            papers = find_related_papers(concept, limit=3)
            if papers:
                kg_results.extend(papers)
        if kg_results:
            kg_lines = []
            for r in kg_results[:5]:
                kg_lines.append(f"- {r.get('title', 'Unknown')} ({r.get('year', '?')}): studies {r.get('concept', '')}")
            kg_context = "\n".join(kg_lines)
        _finish_last(f"知识图谱：发现 {len(kg_results)} 条关联", pct=60)
        print(f"[PIPELINE] Step 3b done: {len(kg_results)} KG results", flush=True)
    except Exception as e:
        _finish_last("知识图谱：跳过（连接异常）", pct=60)
        print(f"[PIPELINE] Step 3b warning (non-fatal): {e}", flush=True)

    # ── Step 4: Reasoning (for complex questions) ────────────────
    reasoning_trace = ""
    if is_complex(question_type) and all_chunks:
        print("[PIPELINE] Step 4: Running ESCARGOT reasoning...", flush=True)
        _add_progress("正在进行深度推理（ESCARGOT）…", pct=65)
        yield _progress_html()
        await asyncio.sleep(0)

        try:
            reasoning_trace = await asyncio.to_thread(
                run_escargot_reasoning,
                question,
                answer_type="natural",
                num_strategies=2,
                timeout=60,
            )
            if reasoning_trace and "超时" not in reasoning_trace:
                _finish_last("深度推理完成", pct=85)
                print(f"[PIPELINE] Step 4 done: {len(reasoning_trace)} chars", flush=True)
            else:
                reasoning_trace = ""
                _finish_last("深度推理：超时跳过", pct=85)
                print("[PIPELINE] Step 4: no reasoning result", flush=True)
        except Exception as e:
            _finish_last("深度推理：跳过（异常）", pct=85)
            print(f"[PIPELINE] Step 4 warning (non-fatal): {e}", flush=True)
            reasoning_trace = ""
    else:
        print(f"[PIPELINE] Step 4: skipped (complex={is_complex(question_type)}, chunks={len(all_chunks)})", flush=True)

    # ── Step 4b: Build final thinking block ────────────────────
    _add_progress("正在生成回答…", pct=90)
    yield _progress_html()
    await asyncio.sleep(0)

    print("[PIPELINE] Step 4b: Building thinking block...", flush=True)
    thinking_block = _build_thinking_block(
        question_type, all_chunks, kg_context, reasoning_trace
    )
    if thinking_block:
        print(f"[PIPELINE] Step 4b: yielding {len(thinking_block)} chars", flush=True)
        yield thinking_block
        await asyncio.sleep(0)

    # ── Step 5: Generate answer with citations (streaming) ───────
    print("[PIPELINE] Step 5: Generating answer...", flush=True)
    full_response_parts = []
    try:
        for piece in generate_answer_stream(
            question=question,
            chunks=all_chunks,
            kg_context=kg_context,
            reasoning_trace=reasoning_trace,
        ):
            full_response_parts.append(piece)
            yield piece
            await asyncio.sleep(0)
    except Exception as e:
        print(f"[PIPELINE] Step 5 FAILED: {e}", flush=True)
        yield f"\n\nPipeline error at answer generation: {e}"
        return
    print(f"[PIPELINE] Step 5 done: {len(full_response_parts)} pieces", flush=True)

    # ── Step 6: Generate follow-up questions ─────────────────────
    print("[PIPELINE] Step 6: Generating follow-ups...", flush=True)
    full_response = "".join(full_response_parts)
    try:
        followups = generate_followup_questions(question, full_response[:500])
        followup_text = format_followup_block(followups)
        if followup_text:
            yield followup_text
        print(f"[PIPELINE] Step 6 done", flush=True)
    except Exception as e:
        print(f"[PIPELINE] Step 6 warning (non-fatal): {e}", flush=True)

    print("[PIPELINE] === COMPLETE ===", flush=True)


def _build_thinking_block(
    question_type: str,
    chunks: list,
    kg_context: str,
    reasoning_trace: str,
) -> str:
    """Build a visible thinking/reasoning block for the user."""
    lines = []
    lines.append("> **推理过程**")
    lines.append(">")

    # Question classification
    type_labels = {
        "factual": "事实查询",
        "process": "工艺流程",
        "comparison": "对比分析",
        "causal": "因果推理",
        "recommendation": "方案推荐",
    }
    label = type_labels.get(question_type, question_type)
    lines.append(f"> **问题类型：** {label}")
    lines.append(">")

    # Retrieved evidence summary
    if chunks:
        lines.append(f"> **检索到 {len(chunks)} 条相关文献片段：**")
        for i, c in enumerate(chunks[:5], 1):
            score_pct = f"{c.score:.0%}" if c.score <= 1 else f"{c.score:.2f}"
            lines.append(f"> - [{i}] {c.title[:60]} ({c.year or '?'}) -- 相关度 {score_pct}")
        if len(chunks) > 5:
            lines.append(f"> - ... 及其他 {len(chunks) - 5} 条")
        lines.append(">")

    # Knowledge graph info
    if kg_context:
        lines.append("> **知识图谱关联：**")
        for kg_line in kg_context.split("\n"):
            lines.append(f"> {kg_line}")
        lines.append(">")

    # ESCARGOT reasoning
    if reasoning_trace:
        lines.append("> **深度推理 (ESCARGOT)：**")
        for rt_line in reasoning_trace.split("\n"):
            lines.append(f"> {rt_line}")
        lines.append(">")

    lines.append("\n---\n\n")
    return "\n".join(lines)


async def _simple_chat(question: str) -> AsyncGenerator[str, None]:
    """Simple pass-through chat for general/non-domain questions."""
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
        {"role": "user", "content": question},
    ]

    stream = chat(messages, stream=True)
    for chunk in stream:
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None)
        if not piece:
            continue
        yield piece
        await asyncio.sleep(0)


def get_pipeline_metadata(question_type: str, chunks: list, reasoning_used: bool) -> dict:
    """Build metadata dict for storing in the messages table."""
    return {
        "question_type": question_type,
        "num_chunks_retrieved": len(chunks),
        "reasoning_used": "escargot" if reasoning_used else "simple_rag",
    }
