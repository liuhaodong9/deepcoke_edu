"""B 评估:基于真实论文标题,用 LLM 反推"该篇应被检索到的中文问题+英文query",
生成 gold 候选题(expected_paper_id 绑真实 id,不用人工猜命中哪篇)。

产出 eval/gold_candidates.json(GoldItem retrieval 格式)。人工过一遍(删不合适的/改问题措辞)后
合并进 gold_set.json 即可用 eval_paper_selection / run_scorecard 评测。

用法(服务器容器内,LLM 在线):
  cd /opt/deepcoke/code/src/LLM_back
  LLM_MODE=openai DEEPSEEK_BASE_URL=http://127.0.0.1:11434/v1 DEEPSEEK_MODEL=qwen3:8b \
    DEEPSEEK_API_KEY=vllm-local CUDA_VISIBLE_DEVICES= \
    /opt/conda/envs/deepcoke/bin/python -X utf8 -m deepcoke.literature_qa.eval.gen_gold_candidates --n 30
"""
import sys
import json
import re
import argparse
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from deepcoke import config              # noqa: E402
from deepcoke.llm_client import chat_json   # noqa: E402

_PROMPT = """给定一篇煤焦化领域论文的标题(可能含 OCR 噪声),生成一个"用户最可能用来找到这篇论文的问题"。

只输出 JSON:{"question": "中文问题", "query": "English search query", "keyword": "命中该篇正文最可能出现的一个英文关键短语"}

要求:问题具体、像真实科研提问;query 是精炼英文检索式;keyword 是该主题核心术语(小写)。
只输出 JSON。"""


def gen_one(title: str) -> dict:
    try:
        raw = chat_json(
            [{"role": "system", "content": _PROMPT},
             {"role": "user", "content": f"标题: {title}"}],
            temperature=0.2,
        )
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        d = json.loads(raw)
        return {"question": d.get("question", ""), "query": d.get("query", ""),
                "keyword": d.get("keyword", "")}
    except Exception as e:
        print(f"  生成失败: {e}")
        return {}


def run(n: int):
    db = sqlite3.connect(str(config.DATA_DIR / "papers.db"))
    # 挑标题较完整的(过滤太短/纯噪声),均匀取 n 篇
    rows = db.execute(
        "SELECT id, title FROM papers WHERE title IS NOT NULL AND LENGTH(title) > 25 ORDER BY id"
    ).fetchall()
    step = max(1, len(rows) // n)
    picked = rows[::step][:n]
    print(f"从 {len(rows)} 篇里均匀取 {len(picked)} 篇生成 gold 候选…")

    out = []
    for i, (pid, title) in enumerate(picked, 1):
        g = gen_one(title)
        if not g.get("question"):
            continue
        out.append({
            "id": f"auto{pid}",
            "type": "retrieval",
            "question": g["question"],
            "query": g["query"] or g["question"],
            "expected_paper_id": pid,
            "expected_substring": g.get("keyword", ""),
            "note": f"auto-gen from title: {title[:50]}",
        })
        print(f"[{i}/{len(picked)}] pid={pid}: {g['question'][:45]}")

    out_file = Path(__file__).resolve().parent / "gold_candidates.json"
    json.dump(out, open(out_file, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n生成 {len(out)} 题 → {out_file}")
    print("人工过一遍(删不合适的),再合并进 gold_set.json 即可评测。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    run(ap.parse_args().n)
