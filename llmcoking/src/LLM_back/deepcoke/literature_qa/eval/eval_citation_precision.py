"""玻尔-B 评估:引用精度(citation precision)。

跑一批 gold 问题,走完整生产链路(process_question),聚合每个 [N] 引用是否被所引证据支持
——直接复用生产里 node_verify_citations 算好并发出的 <!--LITQA_CITE_VERIFY--> 结果,不重造打分。

指标:
  citation_precision = 被支持的 [N] 数 / 全部带核验的 [N] 数
  weak_rate          = 弱支持(⚠)占比
  cited_per_q        = 平均每题引用篇数

用法(服务器容器内,需 LLM 在线):
  cd /opt/deepcoke/code/src/LLM_back
  CUDA_VISIBLE_DEVICES= python -X utf8 -m deepcoke.literature_qa.eval.eval_citation_precision \
      deepcoke/literature_qa/eval/gold_set.json
  # 只跑前 N 题快速看:  --limit 10
"""
import sys
import json
import re
import asyncio
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from deepcoke.enhanced_pipeline_graph import process_question  # noqa: E402
from .gold_schema import load_gold_set  # noqa: E402

_VERIFY_RE = re.compile(r"<!--LITQA_CITE_VERIFY:([\s\S]*?)-->")
_META_RE = re.compile(r"<!--LITQA_META:([\s\S]*?)-->")


async def _run_one(question: str) -> dict:
    """跑一题,返回该题的引用核验汇总。"""
    full = []
    async for piece in process_question(question, history=[], mode="qa"):
        full.append(piece)
    text = "".join(full)

    verify = {}
    mv = _VERIFY_RE.search(text)
    if mv:
        try:
            verify = json.loads(mv.group(1))
        except Exception:
            verify = {}

    cited_papers = 0
    mm = _META_RE.search(text)
    if mm:
        try:
            cited_papers = len(json.loads(mm.group(1)).get("papers") or [])
        except Exception:
            pass

    total = len(verify)
    ok = sum(1 for v in verify.values() if v.get("ok"))
    weak = total - ok
    return {"refs": total, "ok": ok, "weak": weak, "cited_papers": cited_papers,
            "scores": [v.get("score") for v in verify.values()]}


async def _run_all(items, limit):
    rows = []
    for i, g in enumerate(items[:limit] if limit else items, 1):
        q = g.question or g.query
        if not q:
            continue
        try:
            r = await _run_one(q)
        except Exception as e:
            print(f"  [{i}] 失败: {e}")
            continue
        rows.append((g.id, q, r))
        flag = "⚠" if r["weak"] else "✓"
        print(f"  [{i}] {flag} {g.id}: 引用 {r['refs']} 个(支持 {r['ok']}/弱 {r['weak']}),命中 {r['cited_papers']} 篇")
    return rows


def run(gold_path: str, limit: int = 0):
    items = [g for g in load_gold_set(gold_path) if (g.question or g.query)]
    print(f"加载 gold: {len(items)} 题,跑引用精度评估(mode=qa)…\n")
    rows = asyncio.run(_run_all(items, limit))

    tot_refs = sum(r["refs"] for _, _, r in rows)
    tot_ok = sum(r["ok"] for _, _, r in rows)
    tot_weak = sum(r["weak"] for _, _, r in rows)
    q_with_refs = sum(1 for _, _, r in rows if r["refs"])
    avg_cited = (sum(r["cited_papers"] for _, _, r in rows) / len(rows)) if rows else 0

    print("\n" + "=" * 48)
    print("记分卡 — 引用精度")
    print("=" * 48)
    print(f"  题数(有引用/总):     {q_with_refs}/{len(rows)}")
    print(f"  引用精度(支持/全部):  {tot_ok}/{tot_refs} = {tot_ok / tot_refs:.1%}" if tot_refs else "  引用精度: 无可评引用")
    print(f"  弱支持率(⚠):          {tot_weak}/{tot_refs} = {tot_weak / tot_refs:.1%}" if tot_refs else "")
    print(f"  平均命中篇数/题:       {avg_cited:.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gold_path", help="gold set JSON 路径")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 题(0=全部)")
    args = ap.parse_args()
    run(args.gold_path, args.limit)


if __name__ == "__main__":
    main()
