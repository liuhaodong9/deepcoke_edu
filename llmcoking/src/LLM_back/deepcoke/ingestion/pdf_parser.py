"""
结构化 PDF 解析 — 输出带位置信息的文档模型(页码 / bbox / 标题层级 / 章节 / 段落 / 表格 / 图注)。

主解析器 PyMuPDF(fitz):用 get_text("dict") 拿每个 block 的 bbox + 字号,
真页码(不再 char-offset 估算),按字号 + 编号检测标题层级。
表格用 pdfplumber.extract_tables() 结构化抽取,并从正文流剔除避免乱码污染。
图片 Phase 1 只存图注(Fig.N caption),VLM 图像摘要延到 Phase 2。

向后兼容:ParsedPaper 仍暴露 raw_text / sections / page_count,
新增 blocks(结构化块列表),下游分块器吃 blocks。
"""
import re
from pathlib import Path
from dataclasses import dataclass, field


# ──────────────────────────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────────────────────────
@dataclass
class Block:
    """结构化文档块。type ∈ {heading, paragraph, table, figure}。"""
    type: str
    text: str                       # heading/paragraph: 文本; table: markdown 渲染; figure: 图注
    page: int                       # 0-based 真页码
    bbox: tuple = (0.0, 0.0, 0.0, 0.0)
    level: int = 0                  # heading 层级 1/2/3; 非标题为 0
    section_path: str = ""          # 所属章节路径,如 "3 Results > 3.2 CSR"
    table_rows: list = None         # table: 结构化二维数组
    table_no: str = ""              # "Table 3"
    figure_no: str = ""             # "Figure 2"
    caption: str = ""               # 表注 / 图注


@dataclass
class PaperSection:
    """向后兼容:章节(由 blocks 聚合而成)。"""
    title: str
    text: str
    page_start: int
    page_end: int


@dataclass
class ParsedPaper:
    file_path: str
    raw_text: str
    sections: list = field(default_factory=list)   # list[PaperSection] 向后兼容
    blocks: list = field(default_factory=list)      # list[Block] 新结构化输出
    page_count: int = 0


# ──────────────────────────────────────────────────────────────────
# 标题 / 图表标注 正则
# ──────────────────────────────────────────────────────────────────
# 标准学术章节名(辅助:命中即使字号不突出也提升为标题)
_SECTION_WORDS = (
    r"Abstract|Introduction|Background|Literature\s+Review|"
    r"Experiment(?:al)?|Materials?\s+and\s+Methods?|Methodology|Methods?|"
    r"Results?\s+and\s+Discussion|Results?|Discussion|"
    r"Conclusions?|Concluding\s+Remarks|Summary|Acknowledg[e]?ments?|"
    r"References|Appendix|Supplementary|Nomenclature"
)
_SECTION_RE = re.compile(rf"^(?:\d+\.?\s+)?(?:{_SECTION_WORDS})\b", re.IGNORECASE)
# 编号标题:"3 Results" / "3.2 CSR prediction" / "3.2.1 ..."
_NUMBERED_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+\S")
_FIG_CAPTION_RE = re.compile(r"^(Fig(?:ure)?\.?\s*(\d+[A-Za-z]?))", re.IGNORECASE)
_TABLE_CAPTION_RE = re.compile(r"^(Tab(?:le)?\.?\s*(\d+[A-Za-z]?))", re.IGNORECASE)


def parse_pdf(pdf_path: str | Path) -> ParsedPaper | None:
    """解析 PDF。fitz 为主(结构化),失败退 pdfplumber 纯文本。"""
    import os
    if os.getenv("DEEPCOKE_SKIP_FITZ", "").lower() not in ("1", "true"):
        result = _parse_with_fitz(pdf_path)
        if result is not None:
            return result
    return _parse_with_pdfplumber_textonly(pdf_path)


# ──────────────────────────────────────────────────────────────────
# 主解析:fitz 结构化
# ──────────────────────────────────────────────────────────────────
def _parse_with_fitz(pdf_path: str | Path) -> ParsedPaper | None:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return None
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return None

    # 第一步:扫一遍全文 span 字号,定正文字号(按字符数加权的众数)
    body_size = _estimate_body_font_size(doc)

    # 第二步:抽各页表格 bbox + 结构(pdfplumber),建 page -> [(bbox, rows)]
    tables_by_page = _extract_tables_by_page(pdf_path)

    blocks: list[Block] = []
    pages_text: list[str] = []
    section_stack: list[tuple[int, str]] = []   # [(level, title), ...] 维护章节路径

    for page_no, page in enumerate(doc):
        page_dict = page.get_text("dict")
        page_chars: list[str] = []

        # 该页表格 bbox(用于把落在表内的文本块剔除,避免乱码污染段落)
        page_tables = tables_by_page.get(page_no, [])
        table_bboxes = [t[0] for t in page_tables]

        for raw_block in page_dict.get("blocks", []):
            if raw_block.get("type", 0) != 0:
                continue  # type!=0 为图片块,Phase 1 不处理像素
            bbox = tuple(raw_block.get("bbox", (0, 0, 0, 0)))
            if _bbox_in_any(bbox, table_bboxes):
                continue  # 文本落在表格区域内 → 交给表格抽取,跳过

            # 行级处理:fitz 常把标题行和正文段落塞进同一 block,
            # 必须逐行判定,把标题行从段落里拆出来。
            para_lines: list[str] = []   # 累积的正文行

            def _flush_para():
                if not para_lines:
                    return
                ptext = "\n".join(para_lines).strip()
                para_lines.clear()
                if not ptext:
                    return
                blocks.append(Block(
                    type="paragraph", text=ptext, page=page_no, bbox=bbox,
                    section_path=_path_str(section_stack),
                ))

            for line_i, (line_text, line_size, line_bold) in enumerate(_iter_lines(raw_block)):
                line_text = line_text.strip()
                if not line_text:
                    continue
                page_chars.append(line_text)
                is_first_line = (line_i == 0)

                # 图注行
                fig_m = _FIG_CAPTION_RE.match(line_text)
                if fig_m and len(line_text) < 300:
                    _flush_para()
                    blocks.append(Block(
                        type="figure", text=line_text, page=page_no, bbox=bbox,
                        figure_no=_norm_label(fig_m.group(1)), caption=line_text,
                        section_path=_path_str(section_stack),
                    ))
                    continue
                # 表注行 → 回填最近的表
                tab_m = _TABLE_CAPTION_RE.match(line_text)
                if tab_m and len(line_text) < 300:
                    _flush_para()
                    _attach_table_caption(blocks, page_no,
                                          _norm_label(tab_m.group(1)), line_text)
                    continue
                # 标题行
                level = _heading_level(line_text, line_size, line_bold, body_size, is_first_line)
                if level > 0:
                    _flush_para()
                    _update_section_stack(section_stack, level, line_text)
                    blocks.append(Block(
                        type="heading", text=line_text, page=page_no, bbox=bbox,
                        level=level, section_path=_path_str(section_stack),
                    ))
                else:
                    para_lines.append(line_text)

            _flush_para()

        # 该页表格成块(插在该页文本之后,顺序近似)
        for tbbox, rows in page_tables:
            md = _table_to_markdown(rows)
            if not md:
                continue
            blocks.append(Block(
                type="table", text=md, page=page_no, bbox=tbbox,
                table_rows=rows, section_path=_path_str(section_stack),
            ))

        pages_text.append("\n".join(page_chars))

    doc.close()

    raw_text = "\n".join(pages_text)
    if len(raw_text.strip()) < 100:
        return None

    sections = _blocks_to_sections(blocks, len(pages_text))
    return ParsedPaper(
        file_path=str(pdf_path),
        raw_text=raw_text,
        sections=sections,
        blocks=blocks,
        page_count=len(pages_text),
    )


# ──────────────────────────────────────────────────────────────────
# 字号 / 标题
# ──────────────────────────────────────────────────────────────────
def _estimate_body_font_size(doc) -> float:
    """全文 span 字号按字符数加权,取众数为正文字号。"""
    size_chars: dict[int, int] = {}
    for page in doc:
        for b in page.get_text("dict").get("blocks", []):
            for line in b.get("lines", []):
                for span in line.get("spans", []):
                    sz = round(span.get("size", 0))
                    n = len(span.get("text", ""))
                    if sz > 0 and n > 0:
                        size_chars[sz] = size_chars.get(sz, 0) + n
    if not size_chars:
        return 10.0
    return float(max(size_chars.items(), key=lambda x: x[1])[0])


def _iter_lines(raw_block):
    """逐行 yield (line_text, max_size, is_bold)。"""
    for line in raw_block.get("lines", []):
        span_texts = []
        max_size = 0.0
        is_bold = False
        for span in line.get("spans", []):
            span_texts.append(span.get("text", ""))
            max_size = max(max_size, span.get("size", 0))
            if span.get("flags", 0) & 16:  # fitz flags bit4 = bold
                is_bold = True
        yield "".join(span_texts), max_size, is_bold


def _heading_level(line: str, size: float, is_bold: bool, body_size: float,
                   is_first_line: bool = True) -> int:
    """返回标题层级(1/2/3),0 表示正文。保守判定:标题必短、非整句。

    可靠信号(编号 / 章节词)不限位置;脆弱信号(字号 / 粗体)只在 block 首行才考虑,
    避免把双栏 justified 正文的续行误判成标题。
    """
    s = line.strip()
    n = len(s)
    if n < 2 or n > 120:
        return 0
    word_count = len(s.split())

    # 1) 编号标题 "3 / 3.2 / 3.2.1 Title" → 层级 = 编号深度(封顶 3),可靠
    m = _NUMBERED_RE.match(s)
    if m and word_count <= 14 and size >= body_size - 0.5:
        # 编号后必须接标题样文字:首字母大写 + 非整句,
        # 排除正文 "1.0 and a ..." / "3.2 mol of ... was added."
        rest = s[m.end(1):].strip(" .")
        if rest[:1].isupper() and not rest.endswith((".", "?", "!")):
            return min(m.group(1).count(".") + 1, 3)

    # 整句一律不是标题(放在编号规则后,允许 "4.1. Tar Distillation")
    if s.endswith((".", "?", "!", ":", ";", ",")) and not s[:-1].rstrip().isdigit():
        return 0

    # 2) 标准章节词、且基本就是这个词(<=3 词)→ L1,可靠
    if _SECTION_RE.match(s) and word_count <= 3:
        return 1

    # 以下脆弱信号:仅 block 首行 + 必须标题版式(ALL-CAPS / Title-Case)
    if not is_first_line or not _looks_heading_style(s):
        return 0

    # 3) 字号显著大于正文 + 短
    if word_count <= 12:
        if size >= body_size + 2.5:
            return 1
        if size >= body_size + 1.5:
            return 2

    # 4) 粗体且很短
    if is_bold and word_count <= 8 and 3 <= n <= 60 and size >= body_size - 0.5:
        return 3

    return 0


_STOPWORDS = {"a", "an", "the", "of", "for", "and", "or", "in", "on", "to",
              "with", "by", "from", "as", "at", "vs", "via"}


def _looks_heading_style(s: str) -> bool:
    """标题版式判定:ALL-CAPS,或 Title-Case(实词大多首字母大写)。"""
    letters = [c for c in s if c.isalpha()]
    if len(letters) < 3:
        return False
    # ALL-CAPS
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    if upper_ratio >= 0.85:
        return True
    # Title-Case:非停用词里 >=60% 首字母大写
    content_words = [w for w in s.split() if w.lower() not in _STOPWORDS and w[:1].isalpha()]
    if not content_words:
        return False
    cap = sum(1 for w in content_words if w[:1].isupper())
    return cap / len(content_words) >= 0.6


def _update_section_stack(stack: list, level: int, title: str):
    """维护章节路径栈:进新标题时弹出同级及更深级。"""
    title = title.split("\n", 1)[0].strip()
    while stack and stack[-1][0] >= level:
        stack.pop()
    stack.append((level, title))


def _path_str(stack: list) -> str:
    return " > ".join(t for _, t in stack)


# ──────────────────────────────────────────────────────────────────
# 表格(pdfplumber)
# ──────────────────────────────────────────────────────────────────
# 表格抽取策略:仅有线表(精度优先)。
# 无线表用 text 策略噪声太大(会把标题/作者区误抓),降为 Phase 1.5 缺口,宁缺勿滥。
_TABLE_SETTINGS = [
    {"vertical_strategy": "lines", "horizontal_strategy": "lines"},
]


def _extract_tables_by_page(pdf_path) -> dict:
    """用 pdfplumber 抽各页表格,返回 {page_no: [(bbox, rows), ...]}。
    先有线策略;该页无果再用 text 策略兜底无线表,且经过"像不像表"校验防噪。
    bbox 与 fitz 同为左上原点 points 坐标系,可直接复用。"""
    out: dict[int, list] = {}
    try:
        import pdfplumber
    except ImportError:
        return out
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page_no, page in enumerate(pdf.pages):
                page_tables = []
                for si, settings in enumerate(_TABLE_SETTINGS):
                    try:
                        found = page.find_tables(table_settings=settings)
                    except Exception:
                        found = []
                    for t in found:
                        try:
                            rows = _clean_table_rows(t.extract())
                        except Exception:
                            continue
                        # text 策略噪声大,额外要求"像表"
                        if si == 1 and not _looks_tabular(rows):
                            continue
                        if rows:
                            page_tables.append((tuple(t.bbox), rows))
                    if page_tables:
                        break  # 有线策略已命中,不再跑 text 策略
                if page_tables:
                    out[page_no] = page_tables
    except Exception:
        return out
    return out


def _looks_tabular(rows: list) -> bool:
    """无线策略防噪:严格校验,干掉标题/作者稀疏块假表。
    要求:>=3 行、>=2 列、填充率>=0.6、多数行有>=2 非空单元、含数字、单元格普遍短。"""
    if len(rows) < 3 or len(rows[0]) < 2:
        return False
    cells = [c for r in rows for c in r]
    if not cells:
        return False
    fill_ratio = sum(1 for c in cells if c.strip()) / len(cells)
    rows_with_2 = sum(1 for r in rows if sum(1 for c in r if c.strip()) >= 2)
    has_number = any(re.search(r"\d", c) for c in cells)
    short_ratio = sum(1 for c in cells if len(c) <= 25) / len(cells)
    return (fill_ratio >= 0.6
            and rows_with_2 >= len(rows) * 0.6
            and has_number
            and short_ratio >= 0.7)


def _clean_table_rows(rows: list) -> list:
    """清洗:去全空行/列,单元格 None→"",压空白。表格需 >=2 行 >=2 列才算。"""
    if not rows:
        return []
    cleaned = []
    for row in rows:
        cells = [re.sub(r"\s+", " ", (c or "").strip()) for c in row]
        if any(cells):
            cleaned.append(cells)
    if len(cleaned) < 2:
        return []
    ncol = max(len(r) for r in cleaned)
    if ncol < 2:
        return []
    cleaned = [r + [""] * (ncol - len(r)) for r in cleaned]
    return cleaned


def _table_to_markdown(rows: list) -> str:
    """二维数组 → markdown 表(首行为表头)。"""
    if not rows:
        return ""
    header = rows[0]
    body = rows[1:]
    md = ["| " + " | ".join(header) + " |",
          "| " + " | ".join("---" for _ in header) + " |"]
    for r in body:
        md.append("| " + " | ".join(r) + " |")
    return "\n".join(md)


def _attach_table_caption(blocks: list, page_no: int, table_no: str, caption: str):
    """把表注回填给同页最近的、尚无编号的 table 块。"""
    for blk in reversed(blocks):
        if blk.type == "table" and blk.page == page_no and not blk.table_no:
            blk.table_no = table_no
            blk.caption = caption
            return
    # 表块可能还没生成(表注在表上方):暂存到一个占位 figure? 简单起见忽略,
    # 由 _extract_tables_by_page 顺序兜底;表注在表下方时此处即可命中。


# ──────────────────────────────────────────────────────────────────
# 几何辅助
# ──────────────────────────────────────────────────────────────────
def _bbox_in_any(bbox: tuple, others: list, iou_thresh: float = 0.5) -> bool:
    """bbox 中心是否落在任一 other 内,或重叠面积占比超阈值。"""
    if not others:
        return False
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    for o in others:
        if o[0] <= cx <= o[2] and o[1] <= cy <= o[3]:
            return True
        # 重叠面积
        ix = max(0, min(bbox[2], o[2]) - max(bbox[0], o[0]))
        iy = max(0, min(bbox[3], o[3]) - max(bbox[1], o[1]))
        inter = ix * iy
        area = max(1e-6, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
        if inter / area > iou_thresh:
            return True
    return False


def _norm_label(s: str) -> str:
    """'Fig.2' / 'figure 2' → 'Figure 2'; 'Tab.3' → 'Table 3'(仅规范前缀)。"""
    s = re.sub(r"\s+", " ", s.strip())
    s = re.sub(r"^Fig(?:ure)?\.?\s*", "Figure ", s, flags=re.IGNORECASE)
    s = re.sub(r"^Tab(?:le)?\.?\s*", "Table ", s, flags=re.IGNORECASE)
    return s


# ──────────────────────────────────────────────────────────────────
# blocks → sections(向后兼容)
# ──────────────────────────────────────────────────────────────────
def _blocks_to_sections(blocks: list, page_count: int) -> list:
    """把结构化 blocks 聚合成扁平 sections(按 L1/L2 标题切),供旧链路使用。"""
    sections: list[PaperSection] = []
    cur_title = "Preamble"
    cur_parts: list[str] = []
    cur_page_start = 0
    cur_page_end = 0

    def flush():
        if cur_parts:
            sections.append(PaperSection(
                title=cur_title, text="\n\n".join(cur_parts),
                page_start=cur_page_start, page_end=cur_page_end,
            ))

    for blk in blocks:
        if blk.type == "heading" and blk.level <= 2:
            flush()
            cur_title = blk.text.split("\n", 1)[0].strip()
            cur_parts = []
            cur_page_start = blk.page
            cur_page_end = blk.page
        else:
            content = blk.text
            if blk.type == "table" and blk.caption:
                content = blk.caption + "\n" + content
            cur_parts.append(content)
            cur_page_end = blk.page

    flush()
    if not sections:
        sections.append(PaperSection(title="Full Text",
                                     text="\n".join(b.text for b in blocks),
                                     page_start=0, page_end=page_count - 1))
    return sections


# ──────────────────────────────────────────────────────────────────
# 退路:pdfplumber 纯文本(fitz 不可用时)
# ──────────────────────────────────────────────────────────────────
def _parse_with_pdfplumber_textonly(pdf_path) -> ParsedPaper | None:
    try:
        import pdfplumber
    except ImportError:
        return None
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            pages_text = [(p.extract_text() or "") for p in pdf.pages]
    except Exception:
        return None
    raw_text = "\n".join(pages_text)
    if len(raw_text.strip()) < 100:
        return None
    # 退路无结构:整篇一个 paragraph 块 + 一个 Full Text section
    blocks = [Block(type="paragraph", text=raw_text, page=0)]
    sections = [PaperSection(title="Full Text", text=raw_text.strip(),
                             page_start=0, page_end=len(pages_text) - 1)]
    return ParsedPaper(file_path=str(pdf_path), raw_text=raw_text,
                       sections=sections, blocks=blocks,
                       page_count=len(pages_text))
