"""评测 harness — 跑 gold set,输出记分卡。

指标:
  retrieval: recall@k(命中)+ page_correct(±1 页内)
  table:     cell 级准确率(标准表 vs extract_table)
  ocr:       字符级相似度 → 漏字率(1 - 相似度)
  chart:     图注关键词覆盖率(Phase1;Phase2 接 VLM 改人工/LLM-judge)

用法:
  cd src/LLM_back
  python -X utf8 -m deepcoke.literature_qa.eval.eval_harness \
      deepcoke/literature_qa/eval/gold_set.json --top_k 8

注意:retrieval 的 page_correct / table / chart 指标需库已用**新 ingestion 重抽**
(带 page/section/table metadata)才有意义;旧库会大面积降级。
"""
import sys
import argparse
import difflib
import re
from collections import defaultdict

from .gold_schema import load_gold_set, GoldItem


# ──────────────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def eval_retrieval(item: GoldItem, top_k: int) -> dict:
    """检索命中 + 页码正确。"""
    from ...vectorstore.retriever import retrieve
    q = item.query or item.question
    chunks = retrieve(q, top_k=top_k)

    sub = _norm(item.expected_substring)
    hit_chunk = None
    for c in chunks:
        ok_paper = (item.expected_paper_id is None) or (c.paper_id == item.expected_paper_id)
        ok_sub = (not sub) or (sub in _norm(c.text))
        if ok_paper and ok_sub:
            hit_chunk = c
            break

    hit = hit_chunk is not None
    page_correct = None
    if hit and item.expected_page is not None:
        page_correct = abs(int(hit_chunk.page_start) - int(item.expected_page)) <= 1

    return {"hit": hit, "page_correct": page_correct,
            "hit_page": hit_chunk.page_start if hit else None,
            "rank": chunks.index(hit_chunk) + 1 if hit else None}


def eval_table(item: GoldItem) -> dict:
    """表格 cell 级准确率。"""
    from ... import agent_tools as T
    if item.table_paper_id is None:
        return {"skipped": "示例条目,未填 table_paper_id(库重抽后补真实 id)"}
    res = T.tool_extract_table(item.table_paper_id, table_no=item.expected_table_no or None)
    tables = res.get("tables", [])
    if not tables:
        return {"found": False, "cell_accuracy": 0.0}

    # 把抽到的 markdown 还原成单元格集合,与标准表比对(忽略顺序的集合命中率)
    got_cells = set()
    for t in tables:
        for line in t["markdown"].splitlines():
            if line.strip().startswith("|") and set(line) != set("|- "):
                for cell in line.strip("|").split("|"):
                    cn = _norm(cell)
                    if cn and cn != "---":
                        got_cells.add(cn)

    gold_cells = {_norm(c) for row in item.expected_cells for c in row if _norm(c)}
    if not gold_cells:
        return {"found": True, "cell_accuracy": None, "note": "无标准 cells"}
    matched = sum(1 for g in gold_cells if g in got_cells)
    return {"found": True, "cell_accuracy": round(matched / len(gold_cells), 3),
            "matched": matched, "gold_total": len(gold_cells)}


def eval_ocr(item: GoldItem) -> dict:
    """字符级相似度 → 漏字率。"""
    from ...ingestion.pdf_parser import parse_pdf
    if not item.ocr_pdf_path or item.ocr_page is None:
        return {"skipped": "缺 ocr_pdf_path/ocr_page"}
    parsed = parse_pdf(item.ocr_pdf_path)
    if not parsed:
        return {"skipped": "解析失败(可能扫描件需 OCR)"}
    # 取该页文本:从 blocks 里筛 page==ocr_page
    page_text = "\n".join(b.text for b in parsed.blocks if getattr(b, "page", -1) == item.ocr_page)
    ratio = difflib.SequenceMatcher(None, _norm(item.expected_text), _norm(page_text)).ratio()
    return {"similarity": round(ratio, 3), "miss_rate": round(1 - ratio, 3),
            "got_chars": len(page_text)}


def eval_chart(item: GoldItem) -> dict:
    """Phase1:图注关键词覆盖率。"""
    from ... import agent_tools as T
    if item.chart_paper_id is None:
        return {"skipped": "示例条目,未填 chart_paper_id(库重抽后补真实 id)"}
    res = T.tool_analyze_chart(item.chart_paper_id, figure_no=item.figure_no or None)
    figs = res.get("figures", [])
    if not figs:
        return {"found": False, "keyword_coverage": 0.0}
    caption = _norm(figs[0].get("caption", ""))
    kws = [_norm(k) for k in item.expected_summary_keywords]
    if not kws:
        return {"found": True, "keyword_coverage": None}
    cov = sum(1 for k in kws if k in caption) / len(kws)
    return {"found": True, "keyword_coverage": round(cov, 3),
            "note": "Phase1 仅图注;Phase2 应换 VLM 摘要 + LLM-judge"}


# ──────────────────────────────────────────────────────────────────
def run(gold_path: str, top_k: int = 8):
    items = load_gold_set(gold_path)
    by_type = defaultdict(list)
    print(f"加载 gold set: {len(items)} 题  (top_k={top_k})\n")

    for it in items:
        if it.type == "retrieval":
            r = eval_retrieval(it, top_k)
        elif it.type == "table":
            r = eval_table(it)
        elif it.type == "ocr":
            r = eval_ocr(it)
        elif it.type == "chart":
            r = eval_chart(it)
        else:
            r = {"error": f"unknown type {it.type}"}
        by_type[it.type].append(r)
        print(f"[{it.type:9}] {it.id}: {r}")

    # 记分卡
    print("\n" + "=" * 60)
    print("  记分卡")
    print("=" * 60)
    rt = by_type.get("retrieval", [])
    if rt:
        hits = [x for x in rt if x.get("hit")]
        pages = [x["page_correct"] for x in rt if x.get("page_correct") is not None]
        print(f"  retrieval: 命中率 {len(hits)}/{len(rt)} = {len(hits)/len(rt):.1%}")
        if pages:
            print(f"             页码正确率 {sum(pages)}/{len(pages)} = {sum(pages)/len(pages):.1%}")
        else:
            print(f"             页码正确率: 无可评样本(需新 ingestion 重抽 + gold 标注 expected_page)")
    tb = by_type.get("table", [])
    if tb:
        accs = [x["cell_accuracy"] for x in tb if x.get("cell_accuracy") is not None]
        if accs:
            print(f"  table:     平均 cell 准确率 {sum(accs)/len(accs):.1%} ({len(accs)} 表)")
        else:
            print(f"  table:     无可评样本(库未重抽/无标准 cells)")
    oc = by_type.get("ocr", [])
    if oc:
        miss = [x["miss_rate"] for x in oc if "miss_rate" in x]
        if miss:
            print(f"  ocr:       平均漏字率 {sum(miss)/len(miss):.1%} ({len(miss)} 页)")
        else:
            print(f"  ocr:       无可评样本")
    ch = by_type.get("chart", [])
    if ch:
        cov = [x["keyword_coverage"] for x in ch if x.get("keyword_coverage") is not None]
        if cov:
            print(f"  chart:     图注关键词覆盖 {sum(cov)/len(cov):.1%} (Phase1;Phase2 接 VLM)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gold_path", help="gold set JSON 路径")
    ap.add_argument("--top_k", type=int, default=8)
    args = ap.parse_args()
    run(args.gold_path, args.top_k)


if __name__ == "__main__":
    main()
