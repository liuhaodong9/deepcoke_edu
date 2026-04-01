"""
Neo4j client for the coking domain knowledge graph.
"""
import logging
from typing import Any

from .. import config

logger = logging.getLogger(__name__)

_driver = None


def get_driver():
    """Get or create a Neo4j driver."""
    global _driver
    if _driver is None:
        try:
            from neo4j import GraphDatabase
            _driver = GraphDatabase.driver(
                config.NEO4J_URI,
                auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
            )
        except ImportError:
            logger.warning("neo4j package not installed. KG features disabled.")
            return None
        except Exception as e:
            logger.warning(f"Could not connect to Neo4j: {e}. KG features disabled.")
            return None
    return _driver


def execute_cypher(query: str, params: dict | None = None) -> list[dict[str, Any]]:
    """Execute a Cypher query and return results as list of dicts."""
    driver = get_driver()
    if driver is None:
        return []

    try:
        with driver.session() as session:
            result = session.run(query, params or {})
            return [record.data() for record in result]
    except Exception as e:
        logger.error(f"Cypher query error: {e}\nQuery: {query}")
        return []


def find_related_papers(concept: str, limit: int = 10) -> list[dict]:
    """Find papers that study a given concept."""
    query = """
    MATCH (p:Paper)-[:STUDIES_CONCEPT]->(c:Concept)
    WHERE toLower(c.name) CONTAINS toLower($concept)
    RETURN p.paper_id AS paper_id, p.title AS title, p.year AS year,
           c.name AS concept
    ORDER BY p.year DESC
    LIMIT $limit
    """
    return execute_cypher(query, {"concept": concept, "limit": limit})


def find_paper_methods(paper_id: int) -> list[dict]:
    """Find methods used in a specific paper."""
    query = """
    MATCH (p:Paper {paper_id: $paper_id})-[:USES_METHOD]->(m:Method)
    RETURN m.name AS method
    """
    return execute_cypher(query, {"paper_id": paper_id})


def find_concept_connections(concept1: str, concept2: str) -> list[dict]:
    """Find paths connecting two concepts."""
    query = """
    MATCH path = (c1:Concept)-[*1..3]-(c2:Concept)
    WHERE toLower(c1.name) CONTAINS toLower($c1)
      AND toLower(c2.name) CONTAINS toLower($c2)
    RETURN [n IN nodes(path) | labels(n)[0] + ': ' + coalesce(n.name, n.title, '')] AS path_nodes,
           [r IN relationships(path) | type(r)] AS path_rels
    LIMIT 5
    """
    return execute_cypher(query, {"c1": concept1, "c2": concept2})


def find_materials_with_property(property_name: str) -> list[dict]:
    """Find materials that have a specific property measured."""
    query = """
    MATCH (m:Material)-[:HAS_PROPERTY]->(p:Property)
    WHERE toLower(p.name) CONTAINS toLower($prop)
    RETURN m.name AS material, p.name AS property, p.unit AS unit
    LIMIT 20
    """
    return execute_cypher(query, {"prop": property_name})


def query_kg_with_llm(question: str) -> list[dict]:
    """
    Use LLM to generate a Cypher query from a natural language question,
    then execute it against the knowledge graph.
    """
    from ..llm_client import chat_json
    from .schema import CYPHER_SCHEMA

    prompt = f"""You are a Cypher query generator for a coking domain knowledge graph.

Given the schema:
{CYPHER_SCHEMA}

Generate a Cypher query to answer the user's question. Return ONLY the Cypher query, no explanation.
If the question cannot be answered with the given schema, return "NONE".
"""
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": question},
    ]

    try:
        cypher = chat_json(messages, temperature=0.0)
        cypher = cypher.strip().strip("`").strip()
        if cypher.upper() == "NONE" or not cypher.upper().startswith("MATCH"):
            return []
        return execute_cypher(cypher)
    except Exception as e:
        logger.error(f"LLM Cypher generation error: {e}")
        return []
