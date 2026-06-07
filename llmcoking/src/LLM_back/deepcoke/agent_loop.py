"""
ReAct 风格 Agent Loop — LLM 自主决定何时检索、读哪篇论文、何时回答。

工作流程:
  question(EN)
    ↓
  Iteration 1: LLM 调 find_relevant_papers → 看候选 top-3 论文 abstract
    ↓
  Iteration 2: LLM 调 read_paper_fulltext(paper_id=X) → 读全文
    ↓
  Iteration 3: (可选) LLM 调 read_paper_section 或读第二篇全文
    ↓
  Iteration N: LLM 调 finalize_answer(rationale=...) → 结束循环
    ↓
  把所有读过的全文/章节交给 generate 节点写最终答案

注意:
- 依赖 vllm 启动时加 --enable-auto-tool-choice --tool-call-parser hermes (Qwen2.5 风格)
- 否则 tool_calls 解析不出来,会 fallback 到模型直接生成文本(传统 RAG 退化路径)
"""
import json
import logging
from .llm_client import chat_with_tools
from .agent_tools import (
    TOOL_DEFINITIONS,
    execute_tool,
    reconstruct_chunks_for_generation,
)

logger = logging.getLogger("deepcoke.agent_loop")


_SYSTEM_PROMPT = """You are an expert research assistant for coking and metallurgy literature.

MANDATORY WORKFLOW (DO NOT DEVIATE):
  Step 1: find_relevant_papers(query, top_n=3) — find candidates
  Step 2a: read_paper_summary(paper_id of TOP-1 paper) — MANDATORY
  Step 2b: read_paper_summary(paper_id of TOP-2 paper) — ALSO MANDATORY (different paper_id)
  Step 2c (optional): read_paper_summary(paper_id of TOP-3 paper) — only if first two don't cover the question
  Step 3: finalize_answer(rationale) — stop and let generation write the answer

CRITICAL RULES:
  - You MUST call read_paper_summary AT LEAST 2 TIMES for two different paper_ids before finalize_answer.
  - Multiple sources are essential — users need to compare and verify across papers.
  - DO NOT call read_paper_fulltext unless read_paper_summary explicitly returned "no summary available" error.
  - read_paper_fulltext is FORBIDDEN as your default action. It's a last resort.
  - read_paper_summary returns pre-computed structured data including ALL quantitative findings, methods, and citations like [#15][#21]. You ALMOST NEVER need full text.

WHY: read_paper_summary returns a 1000-char structured summary with quantitative data AND chunk citations like [#15]. Your final answer will reuse these [#15] citations so the user can click them to see original paragraphs. This ONLY works if you read summaries, not full text.

Available tools:
1. find_relevant_papers(query, top_n) — find candidate papers
2. read_paper_summary(paper_id) — **DEFAULT TOOL FOR READING. ALWAYS USE THIS.**
3. read_paper_fulltext(paper_id) — FORBIDDEN unless summary returned error
4. read_paper_section(paper_id, section) — only for specific section lookup
5. finalize_answer(rationale) — stop, summarize what you collected

Maximum 5 tool calls. The typical correct sequence is exactly:
  find_relevant_papers → read_paper_summary → read_paper_summary → finalize_answer (4 calls)

Output rules:
- Use tools, don't write the answer in your content. The answer is generated AFTER finalize_answer.
- Do NOT explain reasoning in `content` — put it in finalize_answer's rationale instead.
"""


def run_agent_loop(
    question_en: str,
    question_zh: str = "",
    max_iterations: int = 5,
) -> dict:
    """
    Run the ReAct loop for one user question.

    Args:
        question_en: English version of the question (for the LLM)
        question_zh: Original Chinese question (for context in messages)
        max_iterations: Max tool-call rounds before forced stop

    Returns:
        {
          "tool_log": [(name, args, result), ...],   # 给前端 trace 用
          "chunks": list[RetrievedChunk],            # 给 generate 节点
          "papers_meta": list[dict],                 # 给前端展示
          "finalize_rationale": str,                 # LLM 觉得 ready 的理由
          "iterations": int,                         # 实际跑了几轮
          "fallback": bool,                          # 是否退化(没 tool_calls 或解析失败)
        }
    """
    if question_zh and question_zh != question_en:
        user_msg = f"Original question (Chinese): {question_zh}\n\nEnglish version: {question_en}"
    else:
        user_msg = question_en

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    tool_log: list[tuple[str, dict, dict]] = []
    finalize_rationale = ""
    iterations = 0
    fallback = False

    for it in range(max_iterations):
        iterations = it + 1
        try:
            response = chat_with_tools(
                messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0.1,
                max_tokens=1024,
            )
        except Exception as e:
            logger.warning(f"[agent_loop] iter={iterations} chat_with_tools failed: {e}")
            fallback = True
            break

        tool_calls = response.get("tool_calls") or []
        content = response.get("content")

        if not tool_calls:
            # 模型直接生成了文本而不是工具调用 → 退化模式
            logger.info(
                f"[agent_loop] iter={iterations} no tool_calls, "
                f"content={(content or '')[:80]!r} → fallback to direct retrieval"
            )
            fallback = True
            break

        # 推进 messages
        messages.append({
            "role": "assistant",
            "content": content or "",
            "tool_calls": [
                {
                    "id": tc["id"] or f"call_{it}_{i}",
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                    },
                }
                for i, tc in enumerate(tool_calls)
            ],
        })

        # 执行每个 tool call
        should_stop = False
        for tc in tool_calls:
            name = tc["name"]
            args = tc["arguments"]
            tc_id = tc["id"]

            result_str = execute_tool(name, args)
            try:
                result_obj = json.loads(result_str)
            except json.JSONDecodeError:
                result_obj = {"raw": result_str}
            tool_log.append((name, args, result_obj))

            messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "name": name,
                "content": result_str,
            })

            logger.info(f"[agent_loop] iter={iterations} called {name}({list(args.keys())})")

            if name == "finalize_answer":
                finalize_rationale = args.get("rationale", "")
                should_stop = True

        if should_stop:
            break

    chunks, papers_meta = reconstruct_chunks_for_generation(tool_log)

    logger.info(
        f"[agent_loop] done iterations={iterations} chunks={len(chunks)} "
        f"papers_cited={sum(1 for p in papers_meta if p.get('cited'))} fallback={fallback}"
    )

    return {
        "tool_log": tool_log,
        "chunks": chunks,
        "papers_meta": papers_meta,
        "finalize_rationale": finalize_rationale,
        "iterations": iterations,
        "fallback": fallback,
    }
