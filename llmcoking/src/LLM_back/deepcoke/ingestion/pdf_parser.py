"""
PDF text extraction with section detection.
Uses PyMuPDF (fitz) as primary, pdfplumber as fallback.
"""
import re
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class PaperSection:
    title: str
    text: str
    page_start: int
    page_end: int


@dataclass
class ParsedPaper:
    file_path: str
    raw_text: str
    sections: list[PaperSection] = field(default_factory=list)
    page_count: int = 0


# Common academic section heading patterns
_SECTION_RE = re.compile(
    r"^(?:\d+\.?\s+)?"
    r"(Abstract|Introduction|Background|Literature\s+Review|"
    r"Experiment(?:al)?|Materials?\s+and\s+Methods?|Methods?|"
    r"Results?\s+and\s+Discussion|Results?|Discussion|"
    r"Conclusions?|Summary|Acknowledg[e]?ments?|References|"
    r"Appendix|Supplementary)",
    re.IGNORECASE | re.MULTILINE,
)


def extract_with_fitz(pdf_path: str | Path) -> ParsedPaper | None:
    """Extract text using PyMuPDF (fitz)."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return None

    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return None

    pages_text = []
    for page in doc:
        pages_text.append(page.get_text("text"))

    raw_text = "\n".join(pages_text)
    doc.close()

    if len(raw_text.strip()) < 100:
        return None

    sections = _detect_sections(pages_text)
    return ParsedPaper(
        file_path=str(pdf_path),
        raw_text=raw_text,
        sections=sections,
        page_count=len(pages_text),
    )


def extract_with_pdfplumber(pdf_path: str | Path) -> ParsedPaper | None:
    """Fallback extraction using pdfplumber."""
    try:
        import pdfplumber
    except ImportError:
        return None

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            pages_text = []
            for page in pdf.pages:
                text = page.extract_text() or ""
                pages_text.append(text)
    except Exception:
        return None

    raw_text = "\n".join(pages_text)
    if len(raw_text.strip()) < 100:
        return None

    sections = _detect_sections(pages_text)
    return ParsedPaper(
        file_path=str(pdf_path),
        raw_text=raw_text,
        sections=sections,
        page_count=len(pages_text),
    )


def parse_pdf(pdf_path: str | Path) -> ParsedPaper | None:
    """Parse a PDF file, trying fitz first, then pdfplumber."""
    import os
    if os.getenv("DEEPCOKE_SKIP_FITZ", "").lower() not in ("1", "true"):
        result = extract_with_fitz(pdf_path)
        if result is not None:
            return result
    return extract_with_pdfplumber(pdf_path)


def _detect_sections(pages_text: list[str]) -> list[PaperSection]:
    """Detect sections by heading patterns across pages."""
    full_text = "\n".join(pages_text)
    # Build cumulative char offsets for page boundaries
    page_offsets = []
    offset = 0
    for pt in pages_text:
        page_offsets.append(offset)
        offset += len(pt) + 1  # +1 for the join newline

    matches = list(_SECTION_RE.finditer(full_text))
    if not matches:
        # No sections detected → return entire text as one section
        return [PaperSection(title="Full Text", text=full_text.strip(),
                             page_start=0, page_end=len(pages_text) - 1)]

    sections = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        title = m.group(0).strip()
        text = full_text[start:end].strip()

        # Find page numbers
        page_start = _offset_to_page(start, page_offsets)
        page_end = _offset_to_page(end - 1, page_offsets)
        sections.append(PaperSection(title=title, text=text,
                                     page_start=page_start, page_end=page_end))

    # Prepend content before first section (usually title + abstract header)
    if matches[0].start() > 200:
        preamble = full_text[: matches[0].start()].strip()
        if preamble:
            sections.insert(0, PaperSection(
                title="Preamble", text=preamble,
                page_start=0,
                page_end=_offset_to_page(matches[0].start(), page_offsets),
            ))

    return sections


def _offset_to_page(char_offset: int, page_offsets: list[int]) -> int:
    """Map a character offset to a page index."""
    for i in range(len(page_offsets) - 1, -1, -1):
        if char_offset >= page_offsets[i]:
            return i
    return 0
