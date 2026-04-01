"""
Import pre-extracted entities from JSON into Neo4j.
No LLM needed - just reads kg_entities.json and writes to Neo4j.

Usage:
    cd ~/llmcoking/src/LLM_back
    python -m deepcoke.knowledge_graph.import_entities

Requires: Neo4j running at bolt://localhost:7687
Input: deepcoke/data/kg_entities.json (from extract_entities.py)
"""
import json
import sys
import time

sys.stdout.reconfigure(line_buffering=True)

from .neo4j_client import execute_cypher
from .builder import create_constraints, build_paper_subgraph
from .. import config


def run():
    input_file = config.DATA_DIR / "kg_entities.json"

    if not input_file.exists():
        print(f"ERROR: {input_file} not found.")
        print("Run extract_entities.py first (on GPU server recommended).")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        papers = json.load(f)

    total = len(papers)
    print(f"Importing {total} papers into Neo4j...")

    # Create constraints
    create_constraints()

    t0 = time.time()
    for i, paper in enumerate(papers, 1):
        paper_id = paper["paper_id"]
        title = paper.get("title", "")
        year = paper.get("year")
        authors = paper.get("authors", [])
        entities = paper.get("entities", {})

        print(f"[{i}/{total}] {title[:60]}")
        build_paper_subgraph(paper_id, title, year, authors, entities)

    elapsed = time.time() - t0
    print(f"\nDone! Imported {total} papers into Neo4j in {elapsed:.1f}s")

    # Print stats
    stats = execute_cypher(
        "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS cnt ORDER BY cnt DESC"
    )
    if stats:
        print("\nGraph stats:")
        for s in stats:
            print(f"  {s['label']}: {s['cnt']}")

    rel_stats = execute_cypher(
        "MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS cnt ORDER BY cnt DESC"
    )
    if rel_stats:
        print("\nRelationships:")
        for s in rel_stats:
            print(f"  {s['rel']}: {s['cnt']}")


if __name__ == "__main__":
    run()
