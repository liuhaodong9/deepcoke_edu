"""
Translate Chinese questions to English search queries for cross-lingual retrieval.
Also extracts key concepts for knowledge graph lookup.
"""
import json
import re

from ..llm_client import chat_json

_TRANSLATE_PROMPT = """You are a bilingual assistant for a coal coking domain Q&A system.

Given a Chinese question about coal coking, coal blending, or related topics:
1. Generate 2-3 English search queries optimized for retrieving relevant academic papers.
2. Extract key domain concepts/entities for knowledge graph lookup.

Return a JSON object:
{
  "english_queries": ["query1 about CSR and coal blending", "query2 about ..."],
  "key_concepts": ["CSR", "coal fluidity", "vitrinite"],
  "key_methods": ["FTIR", "TG-MS"],
  "key_materials": ["coking coal", "semi-coke"]
}

Rules:
- Queries should use standard English academic terminology.
- Use common abbreviations (CSR, CRI, FTIR, NMR, TG-MS, etc.).
- If the question is already in English, still generate optimized queries.
- Return ONLY the JSON object."""


def translate_query(question: str) -> dict:
    """
    Translate a Chinese question into English search queries
    and extract key concepts.

    Returns:
        {
            "english_queries": [...],
            "key_concepts": [...],
            "key_methods": [...],
            "key_materials": [...]
        }
    """
    try:
        raw = chat_json(
            [{"role": "system", "content": _TRANSLATE_PROMPT},
             {"role": "user", "content": question}],
            temperature=0.1,
        )
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)

        return {
            "english_queries": data.get("english_queries", [question]),
            "key_concepts": data.get("key_concepts", []),
            "key_methods": data.get("key_methods", []),
            "key_materials": data.get("key_materials", []),
        }
    except Exception:
        # Fallback: use original question as-is
        return {
            "english_queries": [question],
            "key_concepts": [],
            "key_methods": [],
            "key_materials": [],
        }
