"""
Build the coking domain knowledge graph from parsed papers.
Extracts entities (concepts, methods, materials, properties) and relationships
using LLM, then writes to Neo4j.

Usage:
    cd D:\焦化机器人PC端\llmcoking\src\LLM_back
    python -m deepcoke.knowledge_graph.builder
"""
import json
import re
import logging

from ..llm_client import chat_json
from .neo4j_client import execute_cypher
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


def extract_entities(title: str, abstract: str, keywords: list[str]) -> dict:
    """Extract entities from a paper's metadata using LLM."""
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


def create_constraints():
    """Create unique constraints in Neo4j."""
    constraints = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Paper) REQUIRE p.paper_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Author) REQUIRE a.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Concept) REQUIRE c.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Method) REQUIRE m.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (mat:Material) REQUIRE mat.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (prop:Property) REQUIRE prop.name IS UNIQUE",
    ]
    for c in constraints:
        try:
            execute_cypher(c)
        except Exception as e:
            logger.warning(f"Constraint creation: {e}")


def build_paper_subgraph(paper_id: int, title: str, year: int | None,
                         authors: list[str], entities: dict):
    """Build the knowledge graph subgraph for a single paper."""
    # Create Paper node
    execute_cypher(
        "MERGE (p:Paper {paper_id: $pid}) SET p.title = $title, p.year = $year",
        {"pid": paper_id, "title": title, "year": year or 0},
    )

    # Create Author nodes and WROTE relationships
    for author in authors[:10]:  # limit to first 10 authors
        name = author.strip()
        if not name:
            continue
        execute_cypher(
            "MERGE (a:Author {name: $name}) "
            "WITH a MATCH (p:Paper {paper_id: $pid}) "
            "MERGE (a)-[:WROTE]->(p)",
            {"name": name, "pid": paper_id},
        )

    # Create Concept nodes and STUDIES_CONCEPT relationships
    for concept in entities.get("concepts", []):
        concept = concept.strip()
        if not concept:
            continue
        execute_cypher(
            "MERGE (c:Concept {name: $name}) "
            "WITH c MATCH (p:Paper {paper_id: $pid}) "
            "MERGE (p)-[:STUDIES_CONCEPT]->(c)",
            {"name": concept, "pid": paper_id},
        )

    # Create Method nodes and USES_METHOD relationships
    for method in entities.get("methods", []):
        method = method.strip()
        if not method:
            continue
        execute_cypher(
            "MERGE (m:Method {name: $name}) "
            "WITH m MATCH (p:Paper {paper_id: $pid}) "
            "MERGE (p)-[:USES_METHOD]->(m)",
            {"name": method, "pid": paper_id},
        )

    # Create Material nodes and ANALYZES_MATERIAL relationships
    for material in entities.get("materials", []):
        material = material.strip()
        if not material:
            continue
        execute_cypher(
            "MERGE (mat:Material {name: $name}) "
            "WITH mat MATCH (p:Paper {paper_id: $pid}) "
            "MERGE (p)-[:ANALYZES_MATERIAL]->(mat)",
            {"name": material, "pid": paper_id},
        )

    # Create Property nodes and MEASURES_PROPERTY relationships
    for prop in entities.get("properties", []):
        if isinstance(prop, dict):
            name = prop.get("name", "").strip()
            unit = prop.get("unit", "")
        else:
            name = str(prop).strip()
            unit = ""
        if not name:
            continue
        execute_cypher(
            "MERGE (pr:Property {name: $name}) SET pr.unit = $unit "
            "WITH pr MATCH (p:Paper {paper_id: $pid}) "
            "MERGE (p)-[:MEASURES_PROPERTY]->(pr)",
            {"name": name, "unit": unit, "pid": paper_id},
        )

    # Create RELATED_TO relationships between concepts
    for rel in entities.get("concept_relations", []):
        if len(rel) >= 2:
            c1, c2 = rel[0].strip(), rel[1].strip()
            if c1 and c2:
                execute_cypher(
                    "MERGE (c1:Concept {name: $c1}) "
                    "MERGE (c2:Concept {name: $c2}) "
                    "MERGE (c1)-[:RELATED_TO]->(c2)",
                    {"c1": c1, "c2": c2},
                )


def run():
    """Build KG from all papers in the SQLite papers database."""
    import sqlite3
    papers_db = config.DATA_DIR / "papers.db"
    if not papers_db.exists():
        print(f"ERROR: Papers database not found at {papers_db}")
        print("Run ingestion first: python -m deepcoke.ingestion.run_ingestion")
        return

    conn = sqlite3.connect(str(papers_db))
    conn.row_factory = sqlite3.Row

    # Create constraints first
    create_constraints()

    # Fetch all papers
    rows = conn.execute("SELECT id, title, authors, abstract, keywords, year FROM papers").fetchall()
    total = len(rows)
    print(f"Building KG for {total} papers...")

    for i, row in enumerate(rows, 1):
        paper_id = row["id"]
        title = row["title"] or ""
        authors_json = row["authors"]
        abstract = row["abstract"] or ""
        keywords_json = row["keywords"]
        year = row["year"]

        authors = json.loads(authors_json) if authors_json else []
        keywords = json.loads(keywords_json) if keywords_json else []

        print(f"[{i}/{total}] {title[:60]}")

        entities = extract_entities(title, abstract, keywords)
        build_paper_subgraph(paper_id, title, year, authors, entities)

    conn.close()
    print(f"\nKG build complete for {total} papers.")


if __name__ == "__main__":
    run()
