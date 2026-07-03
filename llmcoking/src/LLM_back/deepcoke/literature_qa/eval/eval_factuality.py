"""⑤ 答案事实性评估(半自动)。

流程:对每道 gold 题跑生产回答 → "裁判 LLM"抽 5-8 条关键结论 → 逐条初判
(supported 有据 / generalized 泛化 / unsupported 无据 / wrong 错误) → 存 factuality_review.json。
人工过一遍改判定后,跑 --score 出四率:事实正确率/证据支持率/弱支持率/错误率。

判定用同一套证据(回答里的 [N] 对应文献片段),裁判只依据证据不凭常识。

用法(服务器容器内,LLM 在线):
  cd /opt/deepcoke/code/src/LLM_back
  LLM_MODE=openai DEEPSEEK_BASE_URL=http://127.0.0.1:11434/v1 DEEPSEEK_MODEL=qwen3:8b \
    DEEPSEEK_API_KEY=vllm-local CUDA_VISIBLE_DEVICES= \
    /opt/conda/envs/deepcoke/bin/python -X utf8 -m deepcoke.literature_qa.eval.eval_factuality \
      deepcoke/literature_qa/eval/gold_candidates.json --limit 10
  # 人工改完 factuality_review.json 的 verdict 后:  --score
"""
import sys
import json
import re
import asyncio
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from deepcoke.enhanced_pipeline_graph import process_question   # noqa: E402
from deepcoke.llm_client import chat_json                       # noqa: E402
from .gold_schema import load_gold_set                          # noqa: E402

_REVIEW_FILE = Path(__file__).resolve().parent / "factuality_review.json"
_META_RE = re.compile(r"<!--LITQA_META:([\s\S]*?)-->")

_JUDGE_PROMPT = """你是严格的焦化领域学术审稿人。给你一段"回答"和它引用的"证据片段"。
把回答拆成 5-8 条关键结论,逐条只依据证据判定(不许用常识补):

- supported  : 结论有证据直接支持
- generalized: 大意对但表述过度概括/超出证据范围
- unsupported: 证据里找不到支持
- wrong      : 与证据矛盾或明显误读

只输出 JSON:{"claims":[{"claim":"结论文本","verdict":"supported|generalized|unsupported|wrong"}]}"""


async def _answer_and_evidence(question: str):
    parts = []
    async for p in process_question(question, history=[], mode="qa"):
        parts.append(p)
    full = "".join(parts)
    answer = re.sub(r"<!--[\s\S]*?-->", "", full)
    answer = re.sub(r"<details[\s\S]*?</details>", "", answer)
    answer = re.sub(r"<[^>]+>", "", answer).strip()
    evid = ""
    m = _META_RE.search(full)
    if m:
        try:
            chunks = json.loads(m.group(1)).get("chunks") or []
            evid = "\n".join(f"[{c.get('ref')}] {(c.get('text') or '')[:300]}" for c in chunks[:12])
        except Exception:
            pass
    return answer[:3000], evid[:6000]


def _judge(answer: str, evidence: str) -> list:
    try:
        raw = chat_json([{"role": "system", "content": _JUDGE_PROMPT},
                         {"role": "user", "content": f"回答:\n{answer}\n\n证据片段:\n{evidence}"}],
                        temperature=0.0)
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw).get("claims") or []
    except Exception as e:
        print(f"  裁判失败: {e}")
        return []


async def _run(gold_path, limit):
    items = [g for g in load_gold_set(gold_path) if (g.question or g.query)]
    items = items[:limit] if limit else items
    out = []
    for i, g in enumerate(items, 1):
        q = g.question or g.query
        ans, evid = await _answer_and_evidence(q)
        claims = _judge(ans, evid)
        out.append({"id": g.id, "question": q, "claims": claims})
        n_ok = sum(1 for c in claims if c.get("verdict") == "supported")
        print(f"[{i}/{len(items)}] {g.id}: {len(claims)} 结论, {n_ok} supported  {q[:35]}")
    json.dump(out, open(_REVIEW_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n→ {_REVIEW_FILE}\n人工过一遍改 verdict(supported/generalized/unsupported/wrong),再跑 --score")


def score():
    if not _REVIEW_FILE.exists():
        print("先跑生成 factuality_review.json")
        return
    data = json.load(open(_REVIEW_FILE, encoding="utf-8"))
    import collections
    c = collections.Counter()
    for item in data:
        for cl in item.get("claims", []):
            c[cl.get("verdict", "?")] += 1
    total = sum(c.values())
    if not total:
        print("无结论可评")
        return
    print("=" * 44)
    print(f"事实性记分卡(共 {total} 条结论,{len(data)} 题)")
    print("=" * 44)
    print(f"  事实正确率(supported):     {c['supported']}/{total} = {c['supported']/total:.1%}")
    print(f"  证据支持率(supported+泛化): {(c['supported']+c['generalized'])}/{total} = {(c['supported']+c['generalized'])/total:.1%}")
    print(f"  弱支持率(generalized):     {c['generalized']}/{total} = {c['generalized']/total:.1%}")
    print(f"  无据率(unsupported):       {c['unsupported']}/{total} = {c['unsupported']/total:.1%}")
    print(f"  错误率(wrong):             {c['wrong']}/{total} = {c['wrong']/total:.1%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gold_path", nargs="?", default="deepcoke/literature_qa/eval/gold_candidates.json")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--score", action="store_true", help="只根据(人工改过的)review 文件算指标")
    args = ap.parse_args()
    if args.score:
        score()
    else:
        asyncio.run(_run(args.gold_path, args.limit))


if __name__ == "__main__":
    main()
