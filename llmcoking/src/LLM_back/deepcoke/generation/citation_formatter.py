"""
Citation formatting utilities.
"""


def format_inline_citation(ref_num: int) -> str:
    """Format an inline citation marker."""
    return f"[{ref_num}]"


def format_reference_entry(
    ref_num: int,
    authors: str,
    title: str,
    year: int | None = None,
    category: str = "",
) -> str:
    """Format a single reference entry."""
    if len(authors) > 60:
        authors = authors[:60] + " et al."
    year_str = f" ({year})" if year else ""
    cat_str = f" [{category}]" if category else ""
    return f"[{ref_num}] {authors}. \"{title}\"{year_str}{cat_str}"
