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

# ── VLM (视觉模型, Phase 2 图表理解) ──────────────────────────────
# 默认复用主 LLM 的后端/模式;视觉模型单独配(Qwen2.5-VL via Ollama 或 vLLM)
VLM_MODE = os.getenv("VLM_MODE", os.getenv("LLM_MODE", "ollama")).lower().strip()
VLM_BASE_URL = os.getenv("VLM_BASE_URL", DEEPSEEK_BASE_URL)
VLM_MODEL = os.getenv("VLM_MODEL", "qwen2.5vl:7b")
VLM_API_KEY = os.getenv("VLM_API_KEY", DEEPSEEK_API_KEY)

# ── Embedding ─────────────────────────────────────────────────────
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", str(BASE_DIR / "data" / "bge-base-en-v1.5"))

# ── ChromaDB ──────────────────────────────────────────────────────
CHROMADB_COLLECTION = "coking_papers"

# ── Neo4j Knowledge Graph ─────────────────────────────────────────
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "deepcoke2024")

# ── Retrieval ─────────────────────────────────────────────────────
RETRIEVAL_TOP_K = 10
CHUNK_SIZE = 500       # tokens
CHUNK_OVERLAP = 50     # tokens

# ── MySQL (same as existing) ──────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:123456@127.0.0.1:3306/chat_db?charset=utf8mb4"
)
