"""
Extract metadata (title, authors, abstract, keywords, year) from parsed papers
using LLM-based extraction.
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..llm_client import chat_json


@dataclass
class PaperMetadata:
    title: str = ""
    authors: list[str] = None
    abstract: str = ""
    keywords: list[str] = None
    year: int | None = None

    def __post_init__(self):
        if self.authors is None:
            self.authors = []
        if self.keywords is None:
            self.keywords = []


_EXTRACT_PROMPT = """You are a metadata extraction assistant for academic papers about coal coking, coal blending, and related topics.

Given the first ~2 pages of text from a PDF paper, extract the following metadata as a JSON object:
{
  "title": "full paper title",
  "authors": ["Author One", "Author Two"],
  "abstract": "the full abstract text",
  "keywords": ["keyword1", "keyword2"],
  "year": 2020
}

Rules:
- If a field cannot be determined, use empty string/list/null.
- For year, look for publication year in headers, footers, or journal info.
- Return ONLY the JSON object, no other text.
"""


def extract_metadata(first_pages_text: str, file_path: str = "") -> PaperMetadata:
    """Extract metadata from the first ~2 pages of paper text."""
    # Truncate to ~3000 chars to stay within reasonable token limits
    text = first_pages_text[:3000]

    messages = [
        {"role": "system", "content": _EXTRACT_PROMPT},
        {"role": "user", "content": f"File: {Path(file_path).name}\n\nText:\n{text}"},
    ]

    try:
        raw = chat_json(messages, temperature=0.1)
        # Clean potential markdown code fences
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
    except (json.JSONDecodeError, Exception):
        # Fallback: try to extract title from first line
        lines = first_pages_text.strip().split("\n")
        title_guess = lines[0].strip() if lines else Path(file_path).stem
        return PaperMetadata(title=title_guess)

    return PaperMetadata(
        title=data.get("title", ""),
        authors=data.get("authors", []),
        abstract=data.get("abstract", ""),
        keywords=data.get("keywords", []),
        year=data.get("year"),
    )


def infer_category(file_path: str | Path) -> str:
    """Infer the paper category from its directory path."""
    path = Path(file_path)
    # Walk up to find a parent that's inside Coal blend paper/Coal blend papper/
    parts = path.parts
    for i, part in enumerate(parts):
        if part in ("Coal blend papper", "Coal blend paper"):
            if i + 1 < len(parts) and parts[i + 1] != path.name:
                return parts[i + 1]
    return "uncategorized"
