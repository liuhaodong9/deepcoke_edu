"""
Knowledge graph schema definitions for the coking domain.
Node types and relationship types used in Neo4j.
"""
from dataclasses import dataclass


# ── Node types ────────────────────────────────────────────────────

@dataclass
class PaperNode:
    paper_id: int
    title: str
    year: int | None = None
    doi: str = ""


@dataclass
class AuthorNode:
    name: str
    affiliation: str = ""


@dataclass
class ConceptNode:
    name: str
    category: str = ""  # e.g., "property", "process", "material"


@dataclass
class MethodNode:
    name: str  # e.g., "TG-MS", "FTIR", "NMR"


@dataclass
class MaterialNode:
    name: str  # e.g., specific coal types, coke types


@dataclass
class PropertyNode:
    name: str
    unit: str = ""  # e.g., "CSR (%)", "CRI (%)"


# ── Relationship types ────────────────────────────────────────────

RELATIONSHIP_TYPES = [
    "WROTE",             # Author -> Paper
    "CITES",             # Paper -> Paper
    "STUDIES_CONCEPT",   # Paper -> Concept
    "USES_METHOD",       # Paper -> Method
    "ANALYZES_MATERIAL", # Paper -> Material
    "MEASURES_PROPERTY", # Paper -> Property
    "RELATED_TO",        # Concept -> Concept
    "CHARACTERIZES",     # Method -> Property
    "HAS_PROPERTY",      # Material -> Property
]

# Node type names for ESCARGOT integration
NODE_TYPES = "Paper, Author, Concept, Method, Material, Property"
RELATIONSHIP_TYPES_STR = ", ".join(RELATIONSHIP_TYPES)

# ── Cypher schema description for LLM prompting ──────────────────

CYPHER_SCHEMA = """
Node types:
- Paper: paper_id (int), title (str), year (int), doi (str)
- Author: name (str), affiliation (str)
- Concept: name (str), category (str)
- Method: name (str)
- Material: name (str)
- Property: name (str), unit (str)

Relationships:
- (Author)-[:WROTE]->(Paper)
- (Paper)-[:CITES]->(Paper)
- (Paper)-[:STUDIES_CONCEPT]->(Concept)
- (Paper)-[:USES_METHOD]->(Method)
- (Paper)-[:ANALYZES_MATERIAL]->(Material)
- (Paper)-[:MEASURES_PROPERTY]->(Property)
- (Concept)-[:RELATED_TO]->(Concept)
- (Method)-[:CHARACTERIZES]->(Property)
- (Material)-[:HAS_PROPERTY]->(Property)
""".strip()
