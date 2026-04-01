"""
ChromaDB vector database for storing and retrieving paper chunks.
Uses sentence-transformers with GPU acceleration for embeddings.
"""
import chromadb
from chromadb.config import Settings

from .. import config

_chroma_client: chromadb.ClientAPI | None = None
_embedding_fn = None


def _get_embedding_function():
    """Get a GPU-accelerated sentence-transformers embedding function."""
    global _embedding_fn
    if _embedding_fn is not None:
        return _embedding_fn

    try:
        import torch
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[ChromaDB] 使用设备: {device}")
        print(f"[ChromaDB] 加载 Embedding 模型: {config.EMBEDDING_MODEL} ...")
        print(f"[ChromaDB] （首次运行需从 HuggingFace 下载，可设置 HF_ENDPOINT=https://hf-mirror.com 加速）")
        _embedding_fn = SentenceTransformerEmbeddingFunction(
            model_name=config.EMBEDDING_MODEL,
            device=device,
        )
        print(f"[ChromaDB] Embedding 模型加载完成 OK")
    except Exception as e:
        print(f"[ChromaDB] SentenceTransformer init failed ({e}), using default embeddings")
        _embedding_fn = None

    return _embedding_fn


def get_chroma_client() -> chromadb.ClientAPI:
    """Get or create a persistent ChromaDB client."""
    global _chroma_client
    if _chroma_client is None:
        config.CHROMADB_DIR.mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(
            path=str(config.CHROMADB_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
    return _chroma_client


def get_collection(name: str | None = None):
    """Get or create the coking papers collection with GPU embeddings."""
    client = get_chroma_client()
    col_name = name or config.CHROMADB_COLLECTION

    # 先尝试获取已有 collection（不传 embedding_function 避免冲突）
    existing_names = [c.name for c in client.list_collections()]
    if col_name in existing_names:
        return client.get_collection(name=col_name)

    # 不存在则新建，带 embedding function
    ef = _get_embedding_function()
    kwargs = {
        "name": col_name,
        "metadata": {"hnsw:space": "cosine"},
    }
    if ef is not None:
        kwargs["embedding_function"] = ef
    return client.create_collection(**kwargs)


def upsert_chunks(
    collection,
    paper_id: int,
    chunks: list,  # list of Chunk
    metadata_base: dict,
):
    """Upsert paper chunks into ChromaDB."""
    if not chunks:
        return

    ids = []
    documents = []
    metadatas = []

    for chunk in chunks:
        chunk_id = f"{paper_id}_{chunk.chunk_index}"
        ids.append(chunk_id)
        documents.append(chunk.text)
        meta = {
            **metadata_base,
            "paper_id": paper_id,
            "section": chunk.section,
            "chunk_index": chunk.chunk_index,
        }
        metadatas.append(meta)

    # ChromaDB handles batching internally, but we batch at 100 for safety
    batch_size = 100
    for i in range(0, len(ids), batch_size):
        collection.upsert(
            ids=ids[i:i + batch_size],
            documents=documents[i:i + batch_size],
            metadatas=metadatas[i:i + batch_size],
        )
