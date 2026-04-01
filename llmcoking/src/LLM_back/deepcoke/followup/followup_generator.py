"""
Generate 2-3 follow-up questions (延伸问题) based on the Q&A pair.
"""
import json
import re

from ..llm_client import chat_json

_FOLLOWUP_PROMPT = """你是焦化领域智能问答系统DeepCoke的延伸问题生成模块。

基于以下问答对，生成2-3个延伸问题，帮助用户深入了解该话题。

要求：
- 问题应该与焦化、配煤、煤化工等相关领域有关
- 问题应该自然延伸当前话题，由浅入深
- 每个问题应该是独立的、有价值的
- 用中文提问
- 返回JSON数组格式：["问题1", "问题2", "问题3"]
- 只返回JSON数组，不要其他内容"""


def generate_followup_questions(
    question: str,
    answer_summary: str,
) -> list[str]:
    """
    Generate 2-3 follow-up questions based on the Q&A pair.

    Args:
        question: The original user question.
        answer_summary: A summary of the answer (first ~500 chars).

    Returns:
        List of 2-3 follow-up question strings.
    """
    user_msg = (
        f"用户问题：{question}\n\n"
        f"回答摘要：{answer_summary[:500]}"
    )

    try:
        raw = chat_json(
            [{"role": "system", "content": _FOLLOWUP_PROMPT},
             {"role": "user", "content": user_msg}],
            temperature=0.7,
            max_tokens=300,
        )
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        questions = json.loads(raw)
        if isinstance(questions, list):
            return [str(q) for q in questions[:3]]
        return []
    except Exception:
        return []


def format_followup_block(questions: list[str]) -> str:
    """Format follow-up questions as a markdown block."""
    if not questions:
        return ""

    lines = ["\n\n---\n\n**您可能还想了解：**"]
    for i, q in enumerate(questions, 1):
        lines.append(f"{i}. {q}")

    return "\n".join(lines)
