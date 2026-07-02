"""玻尔-B 一键记分卡:把检索召回 + 论文选取召回 + 引用精度跑成一张卡。

用法(服务器容器内,需 LLM 在线):
  cd /opt/deepcoke/code/src/LLM_back
  CUDA_VISIBLE_DEVICES= python -X utf8 -m deepcoke.literature_qa.eval.run_scorecard \
      --gold deepcoke/literature_qa/eval/gold_set.json \
      --gold_auto deepcoke/literature_qa/eval/gold_auto.json
  # gold_auto(带 expected_paper_id)用于选取召回;gold(问题集)用于引用精度。
  # 没有 gold_auto 就只跑引用精度。
"""
import argparse
import os

from . import eval_citation_precision as ecp

try:
    from . import eval_paper_selection as eps
except Exception:
    eps = None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="deepcoke/literature_qa/eval/gold_set.json")
    ap.add_argument("--gold_auto", default="deepcoke/literature_qa/eval/gold_auto.json")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    print("\n########## DeepResearch 评估记分卡 ##########\n")

    # 1) 论文选取召回(gold 论文是否进选中集)— 需 gold_auto(带 paper_id)
    if eps and os.path.exists(args.gold_auto):
        print("【1/2】论文选取召回")
        try:
            eps.run(args.gold_auto, candidate_n=20, threshold=0.7, floor=12, vote_pool=30)
        except Exception as e:
            print(f"  选取召回评估失败: {e}")
        print()
    else:
        print("【1/2】论文选取召回 — 跳过(无 gold_auto.json,先跑 build_gold_from_quant 生成)\n")

    # 2) 引用精度(回答里的 [N] 是否被证据支持)
    print("【2/2】引用精度")
    ecp.run(args.gold, args.limit)


if __name__ == "__main__":
    main()
