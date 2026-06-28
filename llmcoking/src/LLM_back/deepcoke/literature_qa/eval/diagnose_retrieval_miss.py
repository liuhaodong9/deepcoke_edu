"""诊断检索 miss 的根因:是"该段没被检索到"还是"substring 不在任何 chunk 里"。

对每条 retrieval gold,跑 hybrid 检索;miss 的再全量扫该 paper 的所有 chunk:
  - in_corpus_not_retrieved : substring 在该 paper 某个 chunk 里,但没进 top_k  → 检索排名问题(调 top_k/融合)
  - not_in_corpus           : substring 不在该 paper 任何 chunk 里              → 切块切开 / gold 质量(evidence_quote 非逐字)
  - no_paper_chunks         : 该 paper 在库里没 chunk(数据缺)

用法(容器内 deepcoke 环境):
  python -X utf8 -m deepcoke.literature_qa.eval.diagnose_retrieval_miss \
      deepcoke/literature_qa/eval/gold_auto.json --top_k 8
"""
import sys
import argparse
import re
from collections import Counter

from .gold_schema import load_gold_set
from ...vectorstore.chromadb_store import get_collection


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def _paper_chunk_texts(pid: int) -> list:
    """该 paper 的全部 chunk 文本(全量,不走检索)。"""
    coll = get_collection()
    raw = coll.get(where={"paper_id": int(pid)}, include=["documents"])
    return raw.get("documents", []) or []


def run(gold_path: str, top_k: int = 8):
    from ...agent_tools import hybrid_search
    items = [g for g in load_gold_set(gold_path) if g.type == "retrieval"]
    print(f"诊断 {len(items)} 条 retrieval gold (top_k={top_k})\n")

    cls = Counter()
    examples = {"in_corpus_not_retrieved": [], "not_in_corpus": [], "no_paper_chunks": []}

    for it in items:
        q = it.query or it.question
        sub = _norm(it.expected_substring)
        chunks = hybrid_search(q, top_k=top_k)
        # 命中判定(同 eval_harness)
        hit = any(
            ((it.expected_paper_id is None) or (c.paper_id == it.expected_paper_id))
            and (not sub or sub in _norm(c.text))
            for c in chunks
        )
        if hit:
            cls["hit"] += 1
            continue

        # miss → 全量扫该 paper
        pid = it.expected_paper_id
        texts = _paper_chunk_texts(pid) if pid else []
        if pid and not texts:
            cls["no_paper_chunks"] += 1
            if len(examples["no_paper_chunks"]) < 5:
                examples["no_paper_chunks"].append((it.id, pid))
            continue
        in_corpus = any(sub in _norm(t) for t in texts) if sub else False
        if in_corpus:
            cls["in_corpus_not_retrieved"] += 1
            if len(examples["in_corpus_not_retrieved"]) < 8:
                examples["in_corpus_not_retrieved"].append((it.id, pid, it.expected_substring[:40]))
        else:
            cls["not_in_corpus"] += 1
            if len(examples["not_in_corpus"]) < 8:
                examples["not_in_corpus"].append((it.id, pid, it.expected_substring[:40]))

    total = len(items)
    print("=" * 60)
    print("  诊断分类")
    print("=" * 60)
    print(f"  命中 hit                      : {cls['hit']}/{total}")
    print(f"  ★ 在库但没检索到(排名病)    : {cls['in_corpus_not_retrieved']}/{total}  → 调 top_k/融合")
    print(f"  ★ substring 不在任何 chunk    : {cls['not_in_corpus']}/{total}  → 切块切开/gold 非逐字")
    print(f"  该 paper 无 chunk(数据缺)    : {cls['no_paper_chunks']}/{total}")
    print()
    for k, exs in examples.items():
        if exs:
            print(f"  [{k}] 例:")
            for e in exs:
                print(f"     {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gold_path")
    ap.add_argument("--top_k", type=int, default=8)
    args = ap.parse_args()
    run(args.gold_path, args.top_k)


if __name__ == "__main__":
    main()
