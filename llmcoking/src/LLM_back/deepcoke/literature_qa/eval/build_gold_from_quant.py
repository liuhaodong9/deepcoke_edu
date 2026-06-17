"""从定量表自动生成 retrieval gold items(服务器上 quant 表有数据时跑)。

每条带 evidence_quote 的定量记录 → 一道检索题:
  - expected_paper_id = 该记录 paper_id
  - expected_substring = evidence_quote 里一个有数字的短片段
  - query = evidence_quote 前若干词(英文)
命中判定 = 检索 top_k 里有该论文且含该子串。零人工标注。

用法:
  cd src/LLM_back
  python -X utf8 -m deepcoke.literature_qa.eval.build_gold_from_quant \
      --out deepcoke/literature_qa/eval/gold_auto.json --per_table 12
"""
import sys
import json
import argparse
import sqlite3
import re

from ... import config

# 各表挑一个"指标字段名",拼问题用
_TABLE_FIELDS = {
    "coal_samples": ["volatile_matter_pct", "ash_pct", "sulfur_pct"],
    "coke_experiments": ["csr", "cri", "coking_temp_c"],
    "carbon_microstructure": ["La_nm", "Lc_nm", "d002_nm"],
}


def _has_col(cols, name):
    return name in cols


def _pick_substring(quote: str) -> str:
    """从 evidence_quote 里挑一个含数字的短片段(6~40 字符)作判定子串。"""
    if not quote:
        return ""
    m = re.search(r"[\w\.\-%]*\d[\w\.\-%]*(?:\s+\w+){0,3}", quote)
    return (m.group(0).strip() if m else quote[:30]).strip()


def build(out_path: str, per_table: int = 12):
    db = config.DATA_DIR / "papers.db"
    conn = sqlite3.connect(str(db))
    items = []
    qid = 0

    for table, fields in _TABLE_FIELDS.items():
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if not cols:
            continue
        quote_col = "evidence_quote" if _has_col(cols, "evidence_quote") else None
        label_col = "sample_label" if _has_col(cols, "sample_label") else None
        if not quote_col:
            print(f"  {table}: 无 evidence_quote 列,跳过")
            continue

        rows = conn.execute(
            f"SELECT paper_id, {label_col or 'paper_id'}, {quote_col} FROM {table} "
            f"WHERE {quote_col} IS NOT NULL AND {quote_col} != '' LIMIT ?",
            (per_table,),
        ).fetchall()

        for paper_id, label, quote in rows:
            sub = _pick_substring(quote)
            if not sub:
                continue
            qid += 1
            items.append({
                "id": f"auto{qid:03d}",
                "type": "retrieval",
                "note": f"auto/{table}",
                "question": f"{label} 的相关定量数据(来自 paper {paper_id})",
                "query": " ".join(quote.split()[:8]),
                "expected_paper_id": int(paper_id),
                "expected_substring": sub,
            })

    conn.close()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print(f"生成 {len(items)} 条 gold → {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="gold_auto.json")
    ap.add_argument("--per_table", type=int, default=12)
    args = ap.parse_args()
    build(args.out, args.per_table)


if __name__ == "__main__":
    main()
