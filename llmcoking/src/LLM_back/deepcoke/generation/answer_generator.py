"""
Evidence-driven answer generation module.
Generates answers grounded in retrieved literature evidence with inline citations.
"""
from ..llm_client import chat
from ..vectorstore.retriever import RetrievedChunk


def build_evidence_context(chunks: list[RetrievedChunk]) -> tuple[str, list[dict]]:
    """
    Build a formatted evidence context string and reference list from retrieved chunks.

    Returns:
        (evidence_text, references_list)
    """
    if not chunks:
        return "", []

    # Deduplicate by paper_id, keeping highest score per paper
    seen_papers = {}
    for chunk in chunks:
        pid = chunk.paper_id
        if pid not in seen_papers or chunk.score > seen_papers[pid]["score"]:
            seen_papers[pid] = {
                "chunk": chunk,
                "score": chunk.score,
            }

    # Also include unique chunks from same paper if they cover different sections
    unique_chunks = []
    paper_sections = set()
    for chunk in chunks:
        key = (chunk.paper_id, chunk.section)
        if key not in paper_sections:
            paper_sections.add(key)
            unique_chunks.append(chunk)

    # Build evidence text with citation numbers
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


def build_answer_prompt(
    question: str,
    evidence_text: str,
    kg_context: str = "",
    reasoning_trace: str = "",
) -> list[dict]:
    """Build the prompt messages for answer generation."""
    system_prompt = (
        "你是焦化大语言智能问答与分析系统DeepCoke，由苏州龙泰氢一能源科技有限公司研发。"
        "请基于提供的文献证据回答用户问题。\n\n"
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
        "2. 引用证据时使用 [1][2] 等标注\n"
        "3. 如果证据不足以完全回答问题，明确说明哪些方面需要进一步研究\n"
        "4. 使用标准 Markdown 格式\n"
        "5. 数学公式使用 $$ 包裹\n"
        "6. 不要提供 mermaid 图\n"
        "7. 回答要有逻辑结构，先概述再详述"
    )

    user_parts = [f"**用户问题：** {question}\n"]

    if evidence_text:
        user_parts.append(f"**相关文献证据：**\n{evidence_text}\n")

    if kg_context:
        user_parts.append(f"**知识图谱信息：**\n{kg_context}\n")

    if reasoning_trace:
        user_parts.append(f"**推理分析：**\n{reasoning_trace}\n")

    if not evidence_text and not kg_context:
        user_parts.append(
            "（未检索到直接相关的文献证据，请基于你的专业知识回答，并说明需要进一步查阅文献。）"
        )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def generate_answer_stream(
    question: str,
    chunks: list[RetrievedChunk],
    kg_context: str = "",
    reasoning_trace: str = "",
):
    """
    Generate a streaming answer with citations.

    Yields text chunks that can be streamed to the frontend.
    Also yields the reference section at the end.
    """
    evidence_text, references = build_evidence_context(chunks)
    messages = build_answer_prompt(question, evidence_text, kg_context, reasoning_trace)

    # Stream the main answer
    stream = chat(messages, stream=True)
    full_response_parts = []

    for chunk in stream:
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None)
        if not piece:
            continue
        full_response_parts.append(piece)
        yield piece

    # Append references
    if references:
        ref_text = format_references(references)
        yield ref_text
        full_response_parts.append(ref_text)
