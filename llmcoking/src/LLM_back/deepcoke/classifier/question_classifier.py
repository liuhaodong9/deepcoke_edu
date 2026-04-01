"""
Question type classifier for routing to appropriate processing pipeline.
"""
import re
from ..llm_client import chat_json

# Question types and their descriptions
QUESTION_TYPES = {
    "optimization": "asking to optimize coal blending ratios, predict coke quality (CRI/CSR), or find best blend",
    "factual": "asking for a specific fact, definition, or value",
    "comparison": "comparing two or more things (methods, materials, properties)",
    "causal": "asking why something happens, cause-effect relationships",
    "process": "asking how something works step-by-step",
    "recommendation": "asking for advice, best practices, or optimal parameters",
    "general_chat": "greeting, off-topic, meta-questions, or simple conversation",
}

# Types that require ESCARGOT reasoning (complex)
COMPLEX_TYPES = {"comparison", "causal", "recommendation"}
# Types that use simple RAG
SIMPLE_RAG_TYPES = {"factual", "process"}

# ── 关键词优先匹配（不依赖 LLM，速度快且稳定）──────────────────
_OPTIMIZATION_KEYWORDS = re.compile(
    r"配煤|配比|优化配|煤种|煤样"
    r"|预测.*(?:CRI|CSR|质量)|(?:CRI|CSR|M10|M25).*(?:大于|小于|范围|要求|限制|预测)"
    r"|成本最低|最优方案|混合比例|配方|料斗|blend|opti"
    r"|哪些煤|可用.*煤|查.*煤|列.*煤|煤.*列表|煤.*查"
    r"|多模型|模型.*对比|对比.*预测"
    r"|优化.*方案|方案.*优化",
    re.IGNORECASE,
)

_CLASSIFY_PROMPT = """You are a question classifier for a coal coking domain Q&A system.

Classify the user's question into EXACTLY ONE of these types:
- optimization: asking to optimize coal blending ratios, predict coke quality (CRI/CSR/M10/M25), find best blend, query available coals, or calculate blending costs
- factual: asking for a specific fact, definition, or value
- comparison: comparing two or more things (methods, materials, properties)
- causal: asking why something happens, cause-effect relationships
- process: asking how something works step-by-step
- recommendation: asking for advice, best practices, or optimal parameters
- general_chat: greeting, off-topic, meta-questions, or simple conversation

Return ONLY the type name, nothing else."""


def classify_question(question: str) -> str:
    """
    Classify a question into one of the predefined types.
    Uses keyword matching first (fast & reliable), falls back to LLM.
    """
    # 1) 关键词快速匹配 — 配煤/优化类问题直接路由
    if _OPTIMIZATION_KEYWORDS.search(question):
        return "optimization"

    # 2) LLM 分类 fallback
    try:
        result = chat_json(
            [{"role": "system", "content": _CLASSIFY_PROMPT},
             {"role": "user", "content": question}],
            temperature=0.0,
            max_tokens=20,
        )
        q_type = result.strip().lower().replace('"', "").replace("'", "")
        if q_type in QUESTION_TYPES:
            return q_type
        # Fuzzy match
        for key in QUESTION_TYPES:
            if key in q_type:
                return key
        return "factual"  # default
    except Exception:
        return "factual"


def is_complex(question_type: str) -> bool:
    """Whether this question type should use ESCARGOT reasoning."""
    return question_type in COMPLEX_TYPES


def needs_rag(question_type: str) -> bool:
    """Whether this question type needs RAG retrieval."""
    return question_type not in ("general_chat", "optimization")
