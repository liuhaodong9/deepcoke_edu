"""
Semantic retrieval over the ChromaDB coking papers collection.
"""
from dataclasses import dataclass

from .chromadb_store import get_collection
from .. import config


@dataclass
class RetrievedChunk:
    text: str
    paper_id: int
    title: str
    section: str
    category: str
    year: int
    authors: str
    keywords: str
    score: float  # cosine similarity (higher = more similar)
    chunk_index: int


def retrieve(
    query: str,
    top_k: int | None = None,
    where: dict | None = None,
) -> list[RetrievedChunk]:
    """
    Retrieve top-k most relevant chunks for a query.

    Args:
        query: English search query text.
        top_k: Number of results (default from config).
        where: Optional ChromaDB metadata filter, e.g. {"category": "CSR & CRI"}.

    Returns:
        List of RetrievedChunk sorted by relevance.
    """
    k = top_k or config.RETRIEVAL_TOP_K
    collection = get_collection()

    query_params = {
        "query_texts": [query],
        "n_results": k,
    }
    if where:
        query_params["where"] = where

    results = collection.query(**query_params)

    chunks = []
    if not results or not results["ids"] or not results["ids"][0]:
        return chunks

    for i, doc_id in enumerate(results["ids"][0]):
        meta = results["metadatas"][0][i]
        distance = results["distances"][0][i] if results.get("distances") else 0.0
        # ChromaDB returns distances; for cosine, similarity = 1 - distance
        similarity = 1.0 - distance

        chunks.append(RetrievedChunk(
            text=results["documents"][0][i],
            paper_id=meta.get("paper_id", 0),
            title=meta.get("title", ""),
            section=meta.get("section", ""),
            category=meta.get("category", ""),
            year=meta.get("year", 0),
            authors=meta.get("authors", ""),
            keywords=meta.get("keywords", ""),
            score=similarity,
            chunk_index=meta.get("chunk_index", 0),
        ))

    return chunks
