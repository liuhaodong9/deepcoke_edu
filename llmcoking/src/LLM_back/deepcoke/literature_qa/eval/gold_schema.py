"""评测 gold set 数据模型与读取。

一个 gold item 描述一道题及其"标准出处",harness 据此算指标。
type 决定走哪条评测:
  retrieval — 检索命中 + 页码正确
  table     — 表格解析准确(cell 级)
  ocr       — OCR 漏字率(字符级 diff)
  chart     — 图表理解(Phase1 看图注关键词覆盖,Phase2 接 VLM)
"""
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GoldItem:
    id: str
    type: str                         # retrieval | table | ocr | chart
    note: str = ""

    # --- retrieval ---
    question: str = ""                # 中文问题(展示用)
    query: str = ""                   # 实际检索 query(英文最佳)
    expected_paper_id: int = None     # 期望命中的论文 id(可空)
    expected_substring: str = ""      # 命中 chunk 必须含的子串(可空,二选一)
    expected_page: int = None         # 0-based 期望页码(可空 → 跳过页码指标)

    # --- table ---
    table_paper_id: int = None
    expected_table_no: str = ""
    expected_cells: list = field(default_factory=list)   # 二维数组,标准表

    # --- ocr ---
    ocr_pdf_path: str = ""
    ocr_page: int = None
    expected_text: str = ""           # 人工转写的该页文本

    # --- chart ---
    chart_paper_id: int = None
    figure_no: str = ""
    expected_summary_keywords: list = field(default_factory=list)


def load_gold_set(path: str | Path) -> list:
    """读 gold set JSON(list[dict]) → list[GoldItem]。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = []
    for d in data:
        # 只保留 GoldItem 已知字段,容错多余键
        known = {k: v for k, v in d.items() if k in GoldItem.__dataclass_fields__}
        items.append(GoldItem(**known))
    return items
