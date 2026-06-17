"""
结构感知分块 — 吃 pdf_parser 的 blocks,按语义结构切,不按固定字数。

规则:
- 标题 + 其下段落聚成一个语义单元,不跨同级/更高级标题。
- 单元超 token 上限 → 只在段落(block)边界切,绝不切段落中间;每片继承 section_path。
- 表格 / 图各自独立 chunk(block_type=table/figure),带 table_no / figure_no / caption。
- 每个 chunk 带全量 metadata:page_start/page_end、section_path、block_type、table_no、figure_no、bbox。

向后兼容:保留 chunk_text / chunk_sections(旧 sections 链路用);新链路用 chunk_blocks。
"""
from dataclasses import dataclass, field


@dataclass
class Chunk:
    text: str
    section: str                # 章节短名(section_path 末段),向后兼容
    chunk_index: int
    page_start: int = 0
    page_end: int = 0
    section_path: str = ""
    block_type: str = "paragraph"   # paragraph | table | figure
    table_no: str = ""
    figure_no: str = ""
    bbox: tuple = (0.0, 0.0, 0.0, 0.0)


def _estimate_tokens(text: str) -> int:
    """粗略 token 估算(英文约 4 char/token)。"""
    return len(text) // 4


def _short_section(section_path: str) -> str:
    """section_path 末段作为短章节名;空则 'Body'。"""
    if not section_path:
        return "Body"
    return section_path.split(">")[-1].strip() or "Body"


# ──────────────────────────────────────────────────────────────────
# 新链路:按 blocks 结构化分块
# ──────────────────────────────────────────────────────────────────
def chunk_blocks(
    blocks: list,                 # list[Block]
    max_tokens: int = 500,
) -> list[Chunk]:
    """把结构化 blocks 切成带 metadata 的 chunks。"""
    chunks: list[Chunk] = []
    idx = 0

    # 段落缓冲(同一 section_path 下连续段落聚合)
    buf_texts: list[str] = []
    buf_pages: list[int] = []
    buf_section_path = ""
    buf_first_bbox = (0.0, 0.0, 0.0, 0.0)
    cur_heading = ""             # 当前语义单元的标题,前置到 chunk 增强上下文

    def flush_buffer():
        nonlocal idx, buf_texts, buf_pages, buf_first_bbox
        if not buf_texts:
            return
        # 拼接后按 token 上限,在段落边界切
        unit_paras = buf_texts[:]
        unit_pages = buf_pages[:]
        cur_paras: list[str] = []
        cur_pages: list[int] = []
        cur_tokens = 0
        heading_prefix = (cur_heading + "\n\n") if cur_heading else ""

        def emit(paras, pages):
            nonlocal idx
            if not paras:
                return
            text = heading_prefix + "\n\n".join(paras)
            chunks.append(Chunk(
                text=text.strip(),
                section=_short_section(buf_section_path),
                chunk_index=idx,
                page_start=min(pages) if pages else 0,
                page_end=max(pages) if pages else 0,
                section_path=buf_section_path,
                block_type="paragraph",
                bbox=buf_first_bbox,
            ))
            idx += 1

        for para, page in zip(unit_paras, unit_pages):
            ptok = _estimate_tokens(para)
            # 单段就超限:单独成 chunk(不切段落中间)
            if ptok >= max_tokens:
                emit(cur_paras, cur_pages)
                cur_paras, cur_pages, cur_tokens = [], [], 0
                emit([para], [page])
                continue
            if cur_tokens + ptok > max_tokens and cur_paras:
                emit(cur_paras, cur_pages)
                cur_paras, cur_pages, cur_tokens = [], [], 0
            cur_paras.append(para)
            cur_pages.append(page)
            cur_tokens += ptok
        emit(cur_paras, cur_pages)

        buf_texts, buf_pages = [], []

    for blk in blocks:
        btype = getattr(blk, "type", "paragraph")

        if btype == "heading":
            # 标题边界:先 flush 上一单元,再更新标题/章节
            flush_buffer()
            cur_heading = blk.text.split("\n", 1)[0].strip()
            buf_section_path = blk.section_path
            continue

        if btype == "table":
            flush_buffer()
            caption = blk.caption or blk.table_no
            content = (caption + "\n" if caption else "") + blk.text
            chunks.append(Chunk(
                text=content.strip(),
                section=_short_section(blk.section_path),
                chunk_index=idx,
                page_start=blk.page, page_end=blk.page,
                section_path=blk.section_path,
                block_type="table",
                table_no=blk.table_no,
                bbox=tuple(blk.bbox),
            ))
            idx += 1
            continue

        if btype == "figure":
            flush_buffer()
            chunks.append(Chunk(
                text=(blk.caption or blk.text).strip(),
                section=_short_section(blk.section_path),
                chunk_index=idx,
                page_start=blk.page, page_end=blk.page,
                section_path=blk.section_path,
                block_type="figure",
                figure_no=blk.figure_no,
                bbox=tuple(blk.bbox),
            ))
            idx += 1
            continue

        # paragraph
        if blk.section_path != buf_section_path and buf_texts:
            flush_buffer()
        if not buf_texts:
            buf_section_path = blk.section_path
            buf_first_bbox = tuple(blk.bbox)
        buf_texts.append(blk.text)
        buf_pages.append(blk.page)

    flush_buffer()
    return chunks


# ──────────────────────────────────────────────────────────────────
# 向后兼容:旧 sections / 纯文本链路
# ──────────────────────────────────────────────────────────────────
def chunk_text(text: str, max_tokens: int = 500, overlap_tokens: int = 50) -> list[str]:
    """纯文本固定字数切(退路,边界 snap)。"""
    max_chars = max_tokens * 4
    overlap_chars = overlap_tokens * 4
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        if end < len(text):
            para_break = text.rfind("\n\n", start + max_chars // 2, end)
            if para_break > start:
                end = para_break
            else:
                sent_break = text.rfind(". ", start + max_chars // 2, end)
                if sent_break > start:
                    end = sent_break + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap_chars
        if start <= 0 and end >= len(text):
            break
    return chunks


def chunk_sections(sections: list, max_tokens: int = 500, overlap_tokens: int = 50) -> list[Chunk]:
    """旧链路:按扁平 sections 固定字数切(无 blocks 时退路)。"""
    all_chunks = []
    idx = 0
    for section in sections:
        section_title = getattr(section, "title", "Unknown")
        section_text = getattr(section, "text", None) or str(section)
        page_start = getattr(section, "page_start", 0)
        page_end = getattr(section, "page_end", 0)
        for tc in chunk_text(section_text, max_tokens, overlap_tokens):
            all_chunks.append(Chunk(
                text=tc, section=section_title, chunk_index=idx,
                page_start=page_start, page_end=page_end,
                section_path=section_title,
            ))
            idx += 1
    return all_chunks
