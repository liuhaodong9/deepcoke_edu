"""
DeepCoke centralized configuration.
"""
import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CHROMADB_DIR = DATA_DIR / "chromadb"
PAPERS_DIR = Path(os.getenv("PAPERS_DIR", str(BASE_DIR.parent.parent.parent / "Coal blend paper")))

# ── LLM (Ollama local Qwen3) ─────────────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "ollama")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "http://localhost:11434/v1")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "qwen3:8b")

# ── Embedding ─────────────────────────────────────────────────────
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", str(BASE_DIR / "data" / "bge-base-en-v1.5"))

# ── ChromaDB ──────────────────────────────────────────────────────
CHROMADB_COLLECTION = "coking_papers"

# ── Neo4j Knowledge Graph ─────────────────────────────────────────
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "deepcoke2024")

# ── ESCARGOT ──────────────────────────────────────────────────────
ESCARGOT_DIR = Path(os.getenv("ESCARGOT_DIR", str(BASE_DIR.parent.parent.parent / "escargot")))
ESCARGOT_TIMEOUT = 90  # seconds
ESCARGOT_MAX_TOKENS = 8000

# ── Retrieval ─────────────────────────────────────────────────────
RETRIEVAL_TOP_K = 10
CHUNK_SIZE = 500       # tokens
CHUNK_OVERLAP = 50     # tokens

# ── MySQL (same as existing) ──────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:123456@127.0.0.1:3306/chat_db?charset=utf8mb4"
)
