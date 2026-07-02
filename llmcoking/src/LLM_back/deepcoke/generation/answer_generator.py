"""
Evidence-driven answer generation module.
Generates answers grounded in retrieved literature evidence with inline citations.
"""
from ..llm_client import chat
from ..vectorstore.retriever import RetrievedChunk


def build_evidence_context(chunks: list[RetrievedChunk]) -> tuple[str, list[dict]]:
    """
    Build a formatted evidence context string and reference list from retrieved chunks.

    支持两种模式:
    - 新 (FulltextEvidence pack): chunks 是单条,text 已是按 plan 拼好的多篇全文(带 [N]/[#M])
      直接返回 chunks[0].text 作 evidence_text, references 由前端从 LITQA_META.papers 渲染
    - 旧 (chunk-by-chunk): chunks 是多条原文段, 按 paper_id 去重拼成 [N] (section) text

    Returns:
        (evidence_text, references_list)
    """
    if not chunks:
        return "", []

    # 新模式: enhanced_pipeline 的 summary_filter_fulltext 节点输出
    first = chunks[0]
    if (first.section == "FulltextEvidence" or first.chunk_index == -4) and first.text:
        return first.text, []  # references 给空,LITQA_META.papers 已带完整信息

    # 旧模式: legacy chunk-RAG / literature_qa 路径
    unique_chunks = []
    paper_sections = set()
    for chunk in chunks:
        key = (chunk.paper_id, chunk.section)
        if key not in paper_sections:
            paper_sections.add(key)
            unique_chunks.append(chunk)

    evidence_parts = []
    references = []
    ref_map = {}  # paper_id -> reference number

    for i, chunk in enumerate(unique_chunks[:10], 1):
        pid = chunk.paper_id
        if pid not in ref_map:
            ref_map[pid] = len(references) + 1
            references.append({
                "num": ref_map[pid],
                "title": chunk.title,
                "year": chunk.year,
                "authors": chunk.authors,
                "category": chunk.category,
            })

        ref_num = ref_map[pid]
        evidence_parts.append(
            f"[{ref_num}] ({chunk.section}) {chunk.text[:1200]}"
        )

    evidence_text = "\n\n".join(evidence_parts)
    return evidence_text, references


def format_references(references: list[dict]) -> str:
    """Format the reference list as markdown."""
    if not references:
        return ""

    lines = ["\n\n---\n\n**参考文献：**"]
    for ref in references:
        authors = ref["authors"]
        if len(authors) > 50:
            authors = authors[:50] + " et al."
        year = f" ({ref['year']})" if ref["year"] else ""
        lines.append(f"[{ref['num']}] {authors}. \"{ref['title']}\"{year}")

    return "\n".join(lines)


_MODE_INSTRUCTIONS = {
    "review": (
        "\n【本次为「综述模式」】请把回答组织成一篇结构化文献综述,分节:"
        "研究背景 / 核心机制 / 方法与表征 / 主要发现 / 争议与趋势,每节都用 [N] 标注来源。"
    ),
    "compare": (
        "\n【本次为「对比模式」】回答主体必须是一个 Markdown 对比表(逐篇横向对比:"
        "材料/煤种、工艺条件、核心结论、关键数值,每格带 [N]),表格前后各一两句话即可,不要长篇散文。"
    ),
}


def build_answer_prompt(
    question: str,
    evidence_text: str,
    kg_context: str = "",
    reasoning_trace: str = "",
    structured_evidence: str = "",
    mode: str = "qa",
) -> list[dict]:
    """Build the prompt messages for answer generation。mode: qa/review/compare(玻尔-A 回答模式)。"""
    system_prompt = (
        "你是高校智慧化工软件平台 DeepResearch，由苏州龙泰氢一能源科技有限公司研发。"
        "请基于提供的文献证据回答用户问题。\n\n"
        "【证据结构】\n"
        "  你看到的「相关文献证据」按 [N] 分篇，每篇内部按 [#M] 分段：\n"
        "    ## Paper [1] <title> ...\n"
        "    [#1] <chunk 1 内容>\n"
        "    [#2] <chunk 2 内容>\n"
        "    ## Paper [2] <title> ...\n"
        "    [#1] <chunk 1 内容>\n"
        "  [#M] 标记只是帮你理解段落边界，**严禁在回答里写 [#M]**。\n"
        "  回答里只用 [N] 引用整篇 paper，例如 \"焦炭 CSR 与挥发分负相关 [1][2]\"。\n\n"
        "【证据优先级】\n"
        "  1. 优先使用「结构化字典」里的数值——这些是从文献中抽出的精确实验数据，可直接引用。\n"
        "     引用字典数值时，用「字典数据来源」里给出的对应 [N] 编号（不要自己另编号）。\n"
        "  2. 「结构化字典」未覆盖的，用「相关文献证据」全文补充（用 [1][2] 标注引用）。\n"
        "  3. 两类证据都没有的，再用专业知识回答，并说明需要进一步查阅。\n\n"
        "中文术语规范(严格遵守,不要用错误版本):\n"
        "  ✓ 镜质组(不是\"镜质体\"),镜质组反射率(不是\"镜质体反射率\")\n"
        "  ✓ 惰质组(不是\"惰性成分\"、\"惰性组分\"、\"惰组分\"、\"惰质体\")\n"
        "  ✓ 壳质组(不是\"壳质体\")\n"
        "  ✓ 胶质层(不是\"塑性层\"、\"塑性区\")\n"
        "  ✓ 热塑性区间(不是\"塑性区域\")\n"
        "  ✓ 胶质体(不是\"塑性体\")\n"
        "  ✓ 炼焦煤(不是\"焦化煤\")\n"
        "  ✓ 焦炭反应性 / CRI(不是\"焦炭反应率\"、\"焦炭活性\")\n"
        "  ✓ 反应后强度 / CSR(不是\"反应后焦强度\")\n"
        "  ✓ 半焦(不是\"半焦炭\")\n"
        "  ✓ 焦末(不是\"焦粉\"、\"焦灰\")\n"
        "  ✓ 流动度(不是\"流体性\")\n"
        "  ✓ 焦化压力(不是\"焦化压强\")\n"
        "  ✓ 微孔(不是\"微孔率\"、\"微孔度\")\n\n"
        "要求：\n"
        "1. 用中文回答，专业术语可保留英文\n"
        "2. 引用证据时使用 [1][2] 等 paper 级标注，证据里的 [#M] 段标记**严禁出现在回答里**\n"
        "3. 如果证据不足以完全回答问题，明确说明哪些方面需要进一步研究\n"
        "4. 使用标准 Markdown 格式\n"
        "5. 数学公式使用 $$ 包裹\n"
        "6. 不要提供 mermaid 图\n"
        "7. 回答要有逻辑结构，先概述再详述\n"
        "8. 当回答涉及 3 篇及以上文献、且适合横向对比时，在末尾追加一节「## 文献对比」，"
        "用 Markdown 表格逐篇对比。每行一篇文献，首列为文献编号 [N]，列尽量含：材料/煤种、"
        "关键工艺条件、核心结论、关键数值。示例：\n"
        "   | 文献 | 材料/煤种 | 工艺条件 | 核心结论 | 关键数值 |\n"
        "   | --- | --- | --- | --- | --- |\n"
        "   | [1] | 气煤+焦煤 | 1000°C, 3°C/min | CSR 随挥发分升高而下降 | CSR 62→48 |\n"
        "   单元格里的数值/结论也带 [N] 引用；某维度文献没提就留空，**严禁编造**。"
        "单篇文献或非对比类问题不要硬凑对比表。"
    )

    user_parts = [f"**用户问题：** {question}\n"]

    if structured_evidence:
        user_parts.append(f"**结构化字典（最高优先级）：**\n{structured_evidence}\n")

    if evidence_text:
        user_parts.append(f"**相关文献证据：**\n{evidence_text}\n")

    if kg_context:
        user_parts.append(f"**知识图谱信息：**\n{kg_context}\n")

    if reasoning_trace:
        user_parts.append(f"**推理分析：**\n{reasoning_trace}\n")

    if not evidence_text and not kg_context and not structured_evidence:
        user_parts.append(
            "（未检索到直接相关的文献证据，请基于你的专业知识回答，并说明需要进一步查阅文献。）"
        )

    system_prompt += _MODE_INSTRUCTIONS.get(mode, "")

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


import re as _re

# stream 后处理: LLM 偶尔违反 prompt 仍输出 [#N], 用 tail buffer + regex 删除
_SEGMENT_MARK_RE = _re.compile(r"\s*\[#\d+\]")
_STREAM_BUF_TAIL = 10  # 保留末尾 10 字符防 [#N] 跨 piece 被切


def _strip_segment_marks_stream(stream):
    """Wrap an iterator yielding text pieces, strip [#N] segment marks on the fly."""
    buf = ""
    for piece in stream:
        if not piece:
            continue
        buf += piece
        if len(buf) > _STREAM_BUF_TAIL:
            head = buf[:-_STREAM_BUF_TAIL]
            tail = buf[-_STREAM_BUF_TAIL:]
            cleaned = _SEGMENT_MARK_RE.sub("", head)
            if cleaned:
                yield cleaned
            buf = tail
    # flush remaining
    if buf:
        yield _SEGMENT_MARK_RE.sub("", buf)


def generate_answer_stream(
    question: str,
    chunks: list[RetrievedChunk],
    kg_context: str = "",
    reasoning_trace: str = "",
    structured_evidence: str = "",
    mode: str = "qa",
):
    """
    Generate a streaming answer with citations.

    Yields text chunks that can be streamed to the frontend.
    LLM 偶尔违反 prompt 输出 [#N], stream 流式 tail buffer 兜底删除。
    """
    evidence_text, references = build_evidence_context(chunks)
    messages = build_answer_prompt(question, evidence_text, kg_context, reasoning_trace, structured_evidence, mode)

    def raw_pieces():
        stream = chat(messages, stream=True)
        for chunk in stream:
            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                yield piece

    for cleaned in _strip_segment_marks_stream(raw_pieces()):
        yield cleaned

    # Append references (legacy 模式才有 refs; 新 FulltextEvidence 模式 refs=[],
    # 前端从 LITQA_META.papers 渲染参考文献)
    if references:
        ref_text = format_references(references)
        yield ref_text
