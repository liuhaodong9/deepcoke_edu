"""论文选取 eval —— 量 fast_summary "选几篇论文"那一层(retrieve top-8 的 eval 量不到这层)。

复刻 enhanced_pipeline_graph.node_fast_summary_retrieve 的 Step A(投票)+ Step B(BGE rerank+阈值+保底)
选取逻辑,但**旋钮走 CLI 参数**,这样不改生产常量就能横评不同组合。

两个指标:
  期望论文召回 = gold 标的那篇有没有进"选中集"(篇数变多,召回该升)
  平均选取篇数 = 广度

注意:精度(多出来的篇相不相关)没法自动判(gold 没标"相关论文集"),靠抽查眼看。

用法(容器内 deepcoke 环境):
  # 基线
  python -X utf8 -m deepcoke.literature_qa.eval.eval_paper_selection \
      deepcoke/literature_qa/eval/gold_auto.json --candidate_n 8 --threshold 0.7 --floor 5
  # 调大
  python -X utf8 -m deepcoke.literature_qa.eval.eval_paper_selection \
      deepcoke/literature_qa/eval/gold_auto.json --candidate_n 12 --threshold 0.6 --floor 8
"""
import argparse

from .gold_schema import load_gold_set
from ...agent_tools import (
    hybrid_search,
    _vote_papers_from_chunks,
    _get_paper_meta,
    tool_read_paper_summary,
    bge_rerank,
)


def select_papers(query: str, candidate_n: int, threshold: float,
                  floor: int, vote_pool: int) -> list:
    """复刻 fast_summary Step A+B 的选篇,旋钮参数化。返回选中的 paper_id 列表。"""
    # Step A: 检索 + 投票出候选
    all_chunks = hybrid_search(query, top_k=vote_pool)
    cands = _vote_papers_from_chunks(all_chunks, candidate_n)
    if not cands:
        return []
    # Step B: 读 summary → BGE rerank → 过阈值 → 不足保底顶满
    docs = []
    for pid in cands:
        sr = tool_read_paper_summary(pid)
        summ = (sr.get("summary") or "").strip() or (_get_paper_meta(pid).get("title") or f"paper {pid}")
        docs.append((pid, summ[:2000]))
    reranked = bge_rerank(query, docs)
    selected = [(pid, s) for pid, s in reranked if s >= threshold]
    if len(selected) < floor and reranked:
        have = {p for p, _ in selected}
        for pid, s in reranked:
            if pid not in have:
                selected.append((pid, s))
                have.add(pid)
            if len(selected) >= floor:
                break
    return [pid for pid, _ in selected]


def run(gold_path: str, candidate_n: int, threshold: float, floor: int, vote_pool: int):
    items = [g for g in load_gold_set(gold_path)
             if g.type == "retrieval" and g.expected_paper_id]
    print(f"论文选取 eval: {len(items)} 题 "
          f"(candidate_n={candidate_n} threshold={threshold} floor={floor} vote_pool={vote_pool})\n")
    if not items:
        print("无带 expected_paper_id 的 retrieval gold(用 gold_auto.json,种子 gold 没 paper_id)")
        return
    hits = 0
    counts = []
    for it in items:
        sel = select_papers(it.query or it.question, candidate_n, threshold, floor, vote_pool)
        if it.expected_paper_id in sel:
            hits += 1
        counts.append(len(sel))
    n = len(items)
    print("=" * 56)
    print(f"  期望论文召回(选中集含 gold 论文): {hits}/{n} = {hits / n:.1%}")
    print(f"  平均选取篇数: {sum(counts) / len(counts):.1f}  (min {min(counts)} / max {max(counts)})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gold_path")
    ap.add_argument("--candidate_n", type=int, default=8)
    ap.add_argument("--threshold", type=float, default=0.7)
    ap.add_argument("--floor", type=int, default=5)
    ap.add_argument("--vote_pool", type=int, default=30)
    args = ap.parse_args()
    run(args.gold_path, args.candidate_n, args.threshold, args.floor, args.vote_pool)


if __name__ == "__main__":
    main()
