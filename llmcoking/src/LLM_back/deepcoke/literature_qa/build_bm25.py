"""
为 coking_papers collection 构建 BM25 索引(中英混合分词),pickle 保存到 data/bm25_index.pkl。
service 启动时懒加载。

Usage:
    cd D:\\deepcoke\\deepcoke_edu\\llmcoking\\src\\LLM_back
    python -X utf8 -u -m deepcoke.literature_qa.build_bm25
"""
import pickle
import re
import time

import jieba
from rank_bm25 import BM25Okapi

from deepcoke import config
from deepcoke.vectorstore.chromadb_store import get_chroma_client

BM25_INDEX_PATH = config.DATA_DIR / "bm25_index.pkl"

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[一-龥]")
_STOPWORDS = set(
    "a an and are as at be by for from has have he in is it its of on or "
    "that the to was were will with the 的 了 在 是 我 有 和 就 不 也 都 而 及 与 这 那 "
    "之 其 以 于 等 一 二 三 这种 这种 一些 一个 一种".split()
)


def tokenize(text: str) -> list[str]:
    """中英混合分词:英文按词、中文按 jieba。"""
    text = text.lower()
    # 英文/数字提取
    ascii_tokens = re.findall(r"[a-z0-9]+", text)
    # 中文按 jieba
    cn_tokens = []
    for seg in jieba.cut_for_search(re.sub(r"[a-z0-9\W]+", " ", text)):
        seg = seg.strip()
        if seg and len(seg) >= 1:
            cn_tokens.append(seg)
    tokens = [t for t in ascii_tokens + cn_tokens if t not in _STOPWORDS and len(t) > 1]
    return tokens


def main():
    print("[1/4] 加载 ChromaDB ...")
    client = get_chroma_client()
    col = client.get_collection(config.CHROMADB_COLLECTION)
    print(f"  chunks: {col.count()}")

    print("[2/4] 拉全部 chunk(documents + metadatas) ...")
    t0 = time.time()
    data = col.get(include=["documents", "metadatas"])
    n = len(data["ids"])
    print(f"  got {n} chunks  耗时 {time.time()-t0:.1f}s")

    print("[3/4] 分词(中英混合,jieba)...")
    t0 = time.time()
    corpus_tokens = []
    for i, doc in enumerate(data["documents"], 1):
        corpus_tokens.append(tokenize(doc))
        if i % 1000 == 0:
            print(f"  tokenized {i}/{n}")
    print(f"  分词完成 耗时 {time.time()-t0:.1f}s,平均 {sum(len(t) for t in corpus_tokens)/n:.0f} tokens/chunk")

    print("[4/4] 构建 BM25Okapi 索引 ...")
    t0 = time.time()
    bm25 = BM25Okapi(corpus_tokens)
    print(f"  构建完成 耗时 {time.time()-t0:.1f}s")

    # 提取 paper_id 数组(同 chunk_id 顺序)用于过滤
    paper_ids = [m["paper_id"] for m in data["metadatas"]]
    chunk_ids = data["ids"]

    out = {
        "bm25": bm25,
        "chunk_ids": chunk_ids,
        "paper_ids": paper_ids,
        "documents": data["documents"],
        "metadatas": data["metadatas"],
    }

    BM25_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(BM25_INDEX_PATH, "wb") as f:
        pickle.dump(out, f)
    sz_mb = BM25_INDEX_PATH.stat().st_size / 1024 / 1024
    print(f"\nDONE  写入 {BM25_INDEX_PATH}  ({sz_mb:.1f} MB)")


if __name__ == "__main__":
    main()
