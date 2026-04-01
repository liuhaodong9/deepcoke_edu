"""
Section-aware text chunking for academic papers.
"""
from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    section: str
    chunk_index: int


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (1 token ≈ 4 chars for English text)."""
    return len(text) // 4


def chunk_text(text: str, max_tokens: int = 500, overlap_tokens: int = 50) -> list[str]:
    """Split text into chunks of approximately max_tokens with overlap."""
    max_chars = max_tokens * 4
    overlap_chars = overlap_tokens * 4

    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars

        # Try to break at paragraph or sentence boundary
        if end < len(text):
            # Look for paragraph break
            para_break = text.rfind("\n\n", start + max_chars // 2, end)
            if para_break > start:
                end = para_break
            else:
                # Look for sentence break
                sent_break = text.rfind(". ", start + max_chars // 2, end)
                if sent_break > start:
                    end = sent_break + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end - overlap_chars
        if start <= 0 and end >= len(text):
            break

    return chunks


def chunk_sections(
    sections: list,  # list of PaperSection
    max_tokens: int = 500,
    overlap_tokens: int = 50,
) -> list[Chunk]:
    """Chunk paper sections into indexed chunks."""
    all_chunks = []
    idx = 0

    for section in sections:
        section_title = section.title if hasattr(section, "title") else "Unknown"
        section_text = section.text if hasattr(section, "text") else str(section)

        text_chunks = chunk_text(section_text, max_tokens, overlap_tokens)
        for tc in text_chunks:
            all_chunks.append(Chunk(text=tc, section=section_title, chunk_index=idx))
            idx += 1

    return all_chunks
