"""
Extract entities from papers using LLM and save to JSON.
No Neo4j needed - just LLM inference.

Usage:
    cd ~/llmcoking/src/LLM_back
    python -m deepcoke.knowledge_graph.extract_entities

Output: deepcoke/data/kg_entities.json
"""
import json
import re
import sys
import time
import sqlite3
import logging

sys.stdout.reconfigure(line_buffering=True)

from ..llm_client import chat_json
from .. import config

logger = logging.getLogger(__name__)

_ENTITY_EXTRACT_PROMPT = """You are a domain expert in coal coking and coal blending science.

Given the title, abstract, and keywords of a research paper, extract entities and relationships.

Return a JSON object with:
{
  "concepts": ["CSR", "coal fluidity", ...],
  "methods": ["TG-MS", "FTIR", ...],
  "materials": ["bituminous coal", "semi-coke", ...],
  "properties": [{"name": "CSR", "unit": "%"}, ...],
  "concept_relations": [["concept1", "concept2"], ...]
}

Rules:
- Extract only entities explicitly mentioned or strongly implied.
- Normalize names: use standard abbreviations (CSR, CRI, FTIR, NMR, TG-MS, etc.).
- Keep material names specific when possible (e.g., "Washed coking coal" not just "coal").
- Return ONLY the JSON object.
"""


def extract_entities(title, abstract, keywords):
    user_msg = (
        f"Title: {title}\n"
        f"Abstract: {abstract[:2000]}\n"
        f"Keywords: {', '.join(keywords)}"
    )
    try:
        raw = chat_json(
            [{"role": "system", "content": _ENTITY_EXTRACT_PROMPT},
             {"role": "user", "content": user_msg}],
            temperature=0.1,
        )
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Entity extraction failed for '{title[:50]}': {e}")
        return {"concepts": [], "methods": [], "materials": [],
                "properties": [], "concept_relations": []}


def run():
    papers_db = config.DATA_DIR / "papers.db"
    output_file = config.DATA_DIR / "kg_entities.json"

    if not papers_db.exists():
        print(f"ERROR: papers.db not found at {papers_db}")
        return

    conn = sqlite3.connect(str(papers_db))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT id, title, authors, abstract, keywords, year FROM papers"
    ).fetchall()
    total = len(rows)
    print(f"Extracting entities from {total} papers...")

    # Load existing progress if any
    results = []
    done_ids = set()
    if output_file.exists():
        with open(output_file, "r", encoding="utf-8") as f:
            results = json.load(f)
            done_ids = {r["paper_id"] for r in results}
        print(f"Resuming: {len(done_ids)} already done")

    t0 = time.time()
    for i, row in enumerate(rows, 1):
        paper_id = row["id"]
        if paper_id in done_ids:
            continue

        title = row["title"] or ""
        authors = json.loads(row["authors"]) if row["authors"] else []
        abstract = row["abstract"] or ""
        keywords = json.loads(row["keywords"]) if row["keywords"] else []
        year = row["year"]

        print(f"[{i}/{total}] {title[:60]}")

        entities = extract_entities(title, abstract, keywords)
        results.append({
            "paper_id": paper_id,
            "title": title,
            "year": year,
            "authors": authors,
            "entities": entities,
        })

        # Save progress every 10 papers
        if len(results) % 10 == 0:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            elapsed = time.time() - t0
            remaining = elapsed / (i - len(done_ids)) * (total - i)
            print(f"  >>> saved {len(results)} | {elapsed:.0f}s elapsed | ~{remaining:.0f}s remaining")

    # Final save
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    conn.close()
    print(f"\nDone! {len(results)} papers -> {output_file}")


if __name__ == "__main__":
    run()
