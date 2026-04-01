"""
Multi-level tagging system for coking domain papers.
Primary tags: folder-based categories (27 existing categories).
Secondary tags: LLM-extracted domain-specific topics.
"""
import json
import re

from ..llm_client import chat_json

# Controlled vocabulary for coking domain topics
COKING_TOPICS = [
    "CSR", "CRI", "coal fluidity", "vitrinite reflectance",
    "maceral analysis", "porosity", "coal rank", "coal blending",
    "coke strength", "thermoplasticity", "pyrolysis", "carbonization",
    "volatile matter", "ash content", "sulfur content",
    "FTIR spectroscopy", "NMR spectroscopy", "TG analysis",
    "XPS analysis", "micro CT", "GC-MS",
    "molecular structure", "bond energy", "functional groups",
    "inertinite", "vitrinite", "exinite",
    "plastic layer", "coking pressure", "contraction",
    "blast furnace", "coke quality prediction",
    "coal petrography", "macromolecular structure",
    "thermal decomposition", "gas evolution",
    "dilatation", "free swelling index",
]

_TAG_PROMPT = """You are a domain expert in coal coking and coal science.

Given the title, abstract, and keywords of a research paper, select 3-5 most relevant topics from the controlled vocabulary below. Also suggest 1-2 NEW topics if the paper covers something not in the list.

Controlled vocabulary:
{topics}

Return a JSON object:
{{
  "selected_topics": ["topic1", "topic2", "topic3"],
  "new_topics": ["novel_topic1"]
}}

Return ONLY the JSON object."""


def generate_tags(title: str, abstract: str, keywords: list[str]) -> list[str]:
    """Generate domain-specific tags for a paper."""
    if not abstract and not title:
        return []

    topics_str = ", ".join(COKING_TOPICS)
    prompt = _TAG_PROMPT.format(topics=topics_str)

    user_msg = (
        f"Title: {title}\n"
        f"Abstract: {abstract[:1500]}\n"
        f"Keywords: {', '.join(keywords)}"
    )

    try:
        raw = chat_json(
            [{"role": "system", "content": prompt},
             {"role": "user", "content": user_msg}],
            temperature=0.1,
        )
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        tags = data.get("selected_topics", []) + data.get("new_topics", [])
        return [t.strip().lower() for t in tags if t.strip()]
    except Exception:
        return []
