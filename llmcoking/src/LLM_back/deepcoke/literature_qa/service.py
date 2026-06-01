"""
两阶段文献问答服务。

阶段 1: 在 papers_cards 上检索 top-N 文献（粗筛）
阶段 2: 在 coking_papers 上用 paper_id filter 取 top-K chunks（精读）
阶段 3: qwen3:8b 拼上下文生成带文献引用的回答
"""
from __future__ import annotations

import logging
import pickle
import re
from dataclasses import dataclass, field
from pathlib import Path

from deepcoke import config, llm_client
from deepcoke.vectorstore.chromadb_store import get_chroma_client

logger = logging.getLogger("deepcoke.literature_qa")

CARDS_COLLECTION = "papers_cards"
BM25_INDEX_PATH = config.DATA_DIR / "bm25_index.pkl"
RERANKER_PATH = config.DATA_DIR / "bge-reranker-base"

DEFAULT_N_PAPERS = 5            # Stage 1 粗筛召回的 paper 数(类 PaperQA2:少而精)
DEFAULT_K_CHUNKS = 10           # Stage 2 最终给 LLM 的 chunks 数(5 papers × 2 chunks/paper)
# 混合检索:dense 召回 + BM25 召回各取 N,合并去重后送 reranker 取最终 top-K
HYBRID_DENSE_PER_PAPER = 2     # 每篇 dense 取几条
HYBRID_BM25_POOL = 30          # BM25 候选池大小(在候选 paper 内)
# Per-paper 多样化:防止少数 paper 抢占所有 chunks slot,保证多视角覆盖
# (NotebookLM / PaperQA2 思路:每篇 paper 取 1-2 段,组合成跨文献综述输入)
PER_PAPER_CHUNKS = 2

# Section 权重 — 修正 Abstract 语义浓缩造成的"检索偏向":
# Abstract 单 chunk 跟问题相似度天然高(浓缩了关键词),容易挤掉 Methods/Results 的具体 chunks。
# 降权噪音段(Preamble/References)+ 中等降权 Abstract,让 Methods/Results/Discussion 上来。
_SECTION_WEIGHTS = {
    # 噪音段 — 大幅降权(论文页眉、引文列表、致谢、附录等无实质内容)
    "preamble": 0.3,
    "references": 0.2, "reference": 0.2,
    "acknowledgments": 0.3, "acknowledgement": 0.3, "acknowledgements": 0.3,
    "appendix": 0.5,
    # Abstract — 中等降权(保留少量但不让它独占 top-K)
    "abstract": 0.6,
    # Introduction — 轻微降权(背景介绍,不如 Methods/Results 具体)
    "introduction": 0.85,
    # 其它(methods/results/discussion/experimental/...)默认 1.0
}


def _section_weight(section: str) -> float:
    """根据 chunk 的 section 名给检索 score 一个倍率。
    section 名样式很多(如 "1. Introduction" / "INTRODUCTION" / "method"),
    统一去前导数字编号 + 小写后再查表。"""
    s = (section or "").lower().strip()
    s = re.sub(r"^\d+\.?\s*", "", s).strip()
    return _SECTION_WEIGHTS.get(s, 1.0)


# ─── 全局缓存(懒加载)─────────────────────────────────────────
_bm25_state = None     # dict | False(表示加载失败,以后不再重试)
_reranker = None       # CrossEncoder | False


def _load_bm25():
    """返回 BM25 状态 dict 或 None。失败后缓存 False 不再重试。"""
    global _bm25_state
    if _bm25_state is False:
        return None
    if _bm25_state is not None:
        return _bm25_state
    if not BM25_INDEX_PATH.exists():
        logger.warning(f"[litqa] BM25 索引未找到: {BM25_INDEX_PATH}, 跳过 BM25 召回")
        _bm25_state = False
        return None
    try:
        with open(BM25_INDEX_PATH, "rb") as f:
            state = pickle.load(f)
        # 反向索引:paper_id → list of chunk-array-position
        pos_by_pid = {}
        for pos, pid in enumerate(state["paper_ids"]):
            pos_by_pid.setdefault(pid, []).append(pos)
        state["pos_by_paper"] = pos_by_pid
        _bm25_state = state
        logger.info(f"[litqa] BM25 索引已加载: {len(state['chunk_ids'])} chunks")
        return state
    except Exception as e:
        logger.error(f"[litqa] BM25 索引加载失败: {e}")
        _bm25_state = False
        return None


def _load_reranker():
    """返回 BGE-reranker CrossEncoder 或 None。"""
    global _reranker
    if _reranker is False:
        return None
    if _reranker is not None:
        return _reranker
    if not RERANKER_PATH.exists() or not (RERANKER_PATH / "config.json").exists():
        logger.warning(f"[litqa] reranker 未找到: {RERANKER_PATH}, 跳过重排")
        _reranker = False
        return None
    try:
        from sentence_transformers import CrossEncoder
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _reranker = CrossEncoder(str(RERANKER_PATH), max_length=512, device=device)
        logger.info(f"[litqa] BGE-reranker 已加载 (device={device})")
        return _reranker
    except Exception as e:
        logger.error(f"[litqa] reranker 加载失败: {e}")
        _reranker = False
        return None


def _bm25_recall(question: str, paper_ids: list[int], pool: int) -> list[tuple[str, str, dict, float]]:
    """在指定 paper_ids 范围内做 BM25 召回,返回 [(chunk_id, doc, metadata, score)]。"""
    from .build_bm25 import tokenize
    state = _load_bm25()
    if state is None:
        return []
    q_tokens = tokenize(question)
    if not q_tokens:
        return []
    # 只算候选 paper 对应的 chunk score(全量算也快,但局部更精确)
    pos_set = set()
    for pid in paper_ids:
        pos_set.update(state["pos_by_paper"].get(pid, []))
    if not pos_set:
        return []
    all_scores = state["bm25"].get_scores(q_tokens)
    positions = sorted(pos_set, key=lambda p: -float(all_scores[p]))[:pool]
    out = []
    for p in positions:
        score = float(all_scores[p])
        if score <= 0:
            continue
        out.append((state["chunk_ids"][p], state["documents"][p], state["metadatas"][p], score))
    return out

# 中文术语规范 — 内嵌到所有 LLM 答题 prompt,约束 LLM 把英文 chunks 翻成中文时用学界惯用术语
# 注意:这些是 LLM 易错对照,LLM 在没有提示时会按训练数据里见过最多的写法写,常跟焦化中文学界惯用相反
_TERM_GUIDE = """
中文术语规范(严格遵守,不要用错误版本):
  ✓ 镜质组(不是"镜质体"),镜质组反射率(不是"镜质体反射率")
  ✓ 惰质组(不是"惰性成分"、"惰性组分"、"惰组分"、"惰质体")
  ✓ 壳质组(不是"壳质体")
  ✓ 胶质层(不是"塑性层"、"塑性区")
  ✓ 热塑性区间(不是"塑性区域")
  ✓ 胶质体(不是"塑性体")
  ✓ 炼焦煤(不是"焦化煤")
  ✓ 焦炭反应性 / CRI(不是"焦炭反应率"、"焦炭活性")
  ✓ 反应后强度 / CSR(不是"反应后焦强度")
  ✓ 半焦(不是"半焦炭")
  ✓ 焦末(不是"焦粉"、"焦灰")
  ✓ 流动度(不是"流体性")
  ✓ 焦化压力(不是"焦化压强")
  ✓ 微孔(不是"微孔率"、"微孔度")
""".strip()


ANSWER_PROMPT = f"""你是一位焦化与煤化工领域的科研助手。请根据下面提供的文献片段回答用户问题。

{_TERM_GUIDE}

要求:
- 只使用片段中的信息,不编造。
- 回答用中文,简明、有条理。
- 引用时用 [n] 标注,n 是片段编号。
- 末尾不要再列参考文献清单——会自动追加。
- 如果片段不足以回答,直接说"现有文献不足以回答,需要补充材料"。

文献片段:
{{snippets}}

用户问题: {{question}}

回答:"""


# 枚举型问题专用 prompt:用户问的是"有哪些文献",回答采用**叙述式综述**
# (一段话覆盖主题相关的研究,inline 用 [n] 引用),而不是 itemize 列表 —
# 学术综述的自然语感,而非清单式机械堆砌
LIST_PROMPT = f"""你是一位焦化与煤化工领域的科研助手。用户在询问与某主题相关的研究/文献。
请基于下方文献片段(每段开头已给出《标题》及年份),用**一段连贯的中文话**说明
有哪些研究覆盖了这个主题,采用学术综述的叙述风格。

{_TERM_GUIDE}

输出格式(严格遵守):
- 写成**一段或最多两段连贯的散文**,不要用 1. 2. 3. 等编号列表,也不要用 `-` 符号分行。
- 在叙述中提到某项研究时,**inline 用 [n] 标注**引用编号,例如:
    "在配煤优化方向,Adeleke 等 [1] 提出基于数学规划的非焦煤掺入策略;
     Koszorek 团队 [3] 进一步分析了煤质技术参数与焦炭质量的线性关系;
     而 …… [5] 则聚焦于流动性对焦炭品质的影响。"
- 同一篇文献(同一 paper_id)在叙述中只引用其首次出现的最小 [n]。
- 末尾**不要**追加参考文献清单——会自动追加。

重要:
- 不要写"不足以回答"或"现有文献不足"。即使片段较少,也按现有片段叙述。
- 不要用 itemize/bullet 列表。
- 不要编造片段之外的文献。
- 控制在 150-300 字,简洁有条理。

文献片段:
{{snippets}}

用户问题: {{question}}

综述段落:"""


COMPARE_PROMPT = f"""你是一位焦化与煤化工领域的科研助手。用户在做文献综述,请按"文献分组对比"的方式回答。

{_TERM_GUIDE}

要求:
- 把同一篇文献的多个片段视为一个观点;不同文献之间的相同/相异点都要点出。
- 回答结构(中文):
  1. 一段两三句开场,概括本主题下文献的共识或主要分歧
  2. **按观点(而非按文献)** 组织:每个观点开头一句话陈述,后面列出哪几篇文献支持(用 [n] 引用);若有反例或不同视角的文献,接一句"不过《X》认为..."
  3. 末尾一句简短的"小结",指出尚未解决的争议或可补充研究的方向(若片段不足以判断,不写)
- 引用必须用 [n] 标注 n 是片段编号。
- 末尾不要再列参考文献清单——会自动追加。
- 如果片段不足以做对比,直接说"现有文献不足以支撑综述,需要更多材料"。

文献片段(已按论文分组):
{{snippets}}

用户问题: {{question}}

综述:"""


# 触发综述模式的关键词
_COMPARE_KEYWORDS = re.compile(
    r"综述|review|对比|比较|异同|区别|差异|各.{0,3}观点|不同.{0,4}(说法|看法|结论|方法|结果)"
    r"|分歧|争议|主流.{0,3}(观点|看法|认为)|文献.{0,3}(比较|对比|综述)|梳理.{0,3}文献",
    re.IGNORECASE,
)

# 触发枚举模式的关键词:用户问"有哪些文献",回答应该是文献清单(而非内容综述/对比)
# 优先级高于 compare(先判 list)。覆盖典型句式:
#   "关于X的文献有哪些?"、"有哪些关于Y的论文"、"列出/列举XX文献"、"相关研究有哪些"
_LIST_KEYWORDS = re.compile(
    r"(文献|论文|研究|paper).{0,15}(有哪些|哪些|清单|列出|列举)"
    r"|(有哪些|哪些).{0,15}(文献|论文|研究|paper)"
    r"|列(出|举).{0,15}(文献|论文|研究|paper)"
    r"|(相关|有关)(的)?(研究|文献|论文|paper).{0,4}(有哪些|哪些|清单)?"
    r"|(文献|论文|研究)清单",
    re.IGNORECASE,
)


def _detect_mode(question: str) -> str:
    """根据问题文本判定回答模式。优先级: list > compare > normal。"""
    if _LIST_KEYWORDS.search(question):
        return "list"
    if _COMPARE_KEYWORDS.search(question):
        return "compare"
    return "normal"


@dataclass
class PaperHit:
    paper_id: int
    title: str
    authors: str
    year: int
    category: str
    journal: str = ""
    score: float = 0.0


@dataclass
class ChunkHit:
    paper_id: int
    chunk_id: str
    section: str
    text: str
    score: float = 0.0
    paper: PaperHit | None = None


@dataclass
class LitQAResult:
    answer: str
    papers: list[PaperHit] = field(default_factory=list)
    chunks: list[ChunkHit] = field(default_factory=list)
    debug: dict = field(default_factory=dict)


def _retrieve_papers(question: str, n: int) -> list[PaperHit]:
    """阶段 1: 在卡片库检索 top-N 文献。"""
    client = get_chroma_client()
    col = client.get_collection(CARDS_COLLECTION)
    res = col.query(query_texts=[question], n_results=n, include=["metadatas", "distances"])
    hits = []
    mds = res["metadatas"][0] if res.get("metadatas") else []
    dists = res["distances"][0] if res.get("distances") else []
    for i, m in enumerate(mds):
        hits.append(PaperHit(
            paper_id=m["paper_id"],
            title=m.get("title", ""),
            authors=m.get("authors", ""),
            year=int(m.get("year") or 0),
            category=m.get("category", ""),
            journal=m.get("journal", ""),
            score=1.0 - float(dists[i]) if i < len(dists) else 0.0,
        ))
    return hits


def _retrieve_chunks(question: str, paper_ids: list[int], k: int) -> list[ChunkHit]:
    """阶段 2: 在源 chunk 库限定 paper_id 检索 top-K。

    注:不用 `where={"paper_id": {"$in": [...]}}` 因为现有 ChromaDB 实例曾经做过
    chunk 删除/metadata 批量更新,$in 多值过滤会触发"Error finding id"内部错误。
    改成每个 paper 单查 top-2,然后客户端合并按 score 取 top-K。
    """
    if not paper_ids:
        return []
    client = get_chroma_client()
    col = client.get_collection(config.CHROMADB_COLLECTION)

    per_paper = max(2, (k + len(paper_ids) - 1) // len(paper_ids) * 2)
    all_hits = []
    for pid in paper_ids:
        try:
            res = col.query(
                query_texts=[question],
                n_results=per_paper,
                where={"paper_id": pid},
                include=["metadatas", "documents", "distances"],
            )
        except Exception:
            continue
        ids = res["ids"][0] if res.get("ids") else []
        mds = res["metadatas"][0] if res.get("metadatas") else []
        docs = res["documents"][0] if res.get("documents") else []
        dists = res["distances"][0] if res.get("distances") else []
        for i in range(len(ids)):
            m = mds[i]
            all_hits.append(ChunkHit(
                paper_id=m["paper_id"],
                chunk_id=ids[i],
                section=m.get("section", ""),
                text=docs[i],
                score=1.0 - float(dists[i]) if i < len(dists) else 0.0,
            ))

    all_hits.sort(key=lambda x: -x.score)
    return _topk_per_paper(all_hits, k, PER_PAPER_CHUNKS)


def _topk_per_paper(cand_list: list, k: int, per_paper: int) -> list:
    """从已按 score 降序排好的候选 list 选 top-K,但每篇 paper 最多 per_paper 段。

    保证 chunks 来源多样化(NotebookLM / PaperQA2 思路):
    避免少数高分 paper 抢占所有 slot,让 LLM 能跨文献综合。
    """
    count_per_pid: dict = {}
    selected = []
    for c in cand_list:
        pid = c.paper_id
        if count_per_pid.get(pid, 0) >= per_paper:
            continue
        selected.append(c)
        count_per_pid[pid] = count_per_pid.get(pid, 0) + 1
        if len(selected) >= k:
            break
    return selected


def _retrieve_chunks_hybrid(question: str, paper_ids: list[int], k: int, bm25_query: str | None = None) -> list[ChunkHit]:
    """混合检索: dense + BM25 → 合并去重 → BGE-reranker 重排 → top-K。

    若 reranker 缺失,用归一化分数加权合并;若 BM25 也缺失,fallback 到纯 dense。

    question:    用于 dense(向量库是英文)和 reranker(bge-reranker 双语)的 query。
    bm25_query:  用于 BM25 的 query(默认 = question);跨语言场景下传入中文原句,
                 让 jieba 分词后命中中文章节标题/术语,与英文 dense 检索互补。
    """
    if not paper_ids:
        return []
    if bm25_query is None:
        bm25_query = question

    # 1) Dense 召回(走原 _retrieve_chunks 拿 each paper top-2)
    dense_hits = _retrieve_chunks(question, paper_ids, k=max(k * 3, HYBRID_DENSE_PER_PAPER * len(paper_ids)))
    dense_by_id = {h.chunk_id: h for h in dense_hits}

    # 2) BM25 召回(用 bm25_query,通常是中文原句)
    bm25_recall = _bm25_recall(bm25_query, paper_ids, HYBRID_BM25_POOL)
    bm25_by_id = {cid: (cid, doc, md, score) for cid, doc, md, score in bm25_recall}

    if not bm25_by_id:
        # 没 BM25,fallback 到纯 dense(section 权重 + per-paper 多样化)
        for h in dense_hits:
            h.score = h.score * _section_weight(h.section)
        dense_hits.sort(key=lambda x: -x.score)
        return _topk_per_paper(dense_hits, k, PER_PAPER_CHUNKS)

    # 3) 合并候选集
    candidates: dict[str, ChunkHit] = {}
    for cid, h in dense_by_id.items():
        candidates[cid] = h
    for cid, (_, doc, md, _score) in bm25_by_id.items():
        if cid in candidates:
            continue
        candidates[cid] = ChunkHit(
            paper_id=md["paper_id"],
            chunk_id=cid,
            section=md.get("section", ""),
            text=doc,
            score=0.0,  # 后面 reranker 会覆盖
        )

    if not candidates:
        return []

    cand_list = list(candidates.values())

    # 4) reranker 重排
    reranker = _load_reranker()
    if reranker is not None:
        try:
            pairs = [(question, c.text) for c in cand_list]
            scores = reranker.predict(pairs, batch_size=32, show_progress_bar=False)
            for h, s in zip(cand_list, scores):
                h.score = float(s)
            # section 权重:reranker score × _section_weight 让 Methods/Results 优先于 Abstract/Preamble
            for h in cand_list:
                h.score = h.score * _section_weight(h.section)
            cand_list.sort(key=lambda x: -x.score)
            return _topk_per_paper(cand_list, k, PER_PAPER_CHUNKS)
        except Exception as e:
            logger.error(f"[litqa] reranker 推理失败: {e},回落到分数归一化合并")

    # 5) Fallback: 归一化 dense+BM25 分数加权合并
    def norm(vals):
        if not vals:
            return {}
        lo, hi = min(vals.values()), max(vals.values())
        if hi - lo < 1e-9:
            return {k: 0.5 for k in vals}
        return {k: (v - lo) / (hi - lo) for k, v in vals.items()}

    dense_scores = {cid: h.score for cid, h in dense_by_id.items()}
    bm25_scores = {cid: s for cid, (_, _, _, s) in bm25_by_id.items()}
    dn = norm(dense_scores)
    bn = norm(bm25_scores)
    for h in cand_list:
        h.score = (0.5 * dn.get(h.chunk_id, 0.0) + 0.5 * bn.get(h.chunk_id, 0.0)) * _section_weight(h.section)
    cand_list.sort(key=lambda x: -x.score)
    return _topk_per_paper(cand_list, k, PER_PAPER_CHUNKS)


def _format_snippets(chunks: list[ChunkHit], papers_by_id: dict[int, PaperHit]) -> str:
    """普通模式: 一段一片,按检索 score 顺序。"""
    lines = []
    for i, c in enumerate(chunks, 1):
        p = papers_by_id.get(c.paper_id)
        head = f"[{i}] 《{(p.title if p else '')}》"
        if p and p.year:
            head += f" ({p.year})"
        if c.section:
            head += f" — {c.section}"
        lines.append(head)
        snippet = c.text.strip().replace("\n", " ")
        if len(snippet) > 1500:
            snippet = snippet[:1500] + "…"
        lines.append(snippet)
        lines.append("")
    return "\n".join(lines).strip()


def _format_snippets_grouped(chunks: list[ChunkHit], papers_by_id: dict[int, PaperHit]) -> str:
    """综述模式: 按论文分组,同一篇的多段聚在一起,便于 LLM 跨段整合观点。"""
    groups: dict[int, list[tuple[int, ChunkHit]]] = {}
    for i, c in enumerate(chunks, 1):
        groups.setdefault(c.paper_id, []).append((i, c))
    lines = []
    for pid, items in groups.items():
        p = papers_by_id.get(pid)
        head_title = p.title if p else "(未知)"
        head_year = f" ({p.year})" if p and p.year else ""
        head_journal = f", *{p.journal}*" if p and p.journal else ""
        lines.append(f"### 《{head_title}》{head_year}{head_journal}")
        for n, c in items:
            section_tag = f" [{c.section}]" if c.section else ""
            snippet = c.text.strip().replace("\n", " ")
            if len(snippet) > 1300:
                snippet = snippet[:1300] + "…"
            lines.append(f"- [{n}]{section_tag} {snippet}")
        lines.append("")
    return "\n".join(lines).strip()


def build_prompt(
    question: str,
    chunks: list[ChunkHit],
    papers_by_id: dict[int, PaperHit],
    mode: str | None = None,
) -> tuple[str, str]:
    """根据 mode 拼装最终 prompt。返回 (prompt, mode)。"""
    if mode is None:
        mode = _detect_mode(question)
    if mode == "list":
        # 枚举型问题:按论文分组让 LLM 一篇一行列出,避免重复同一篇多次
        snippets = _format_snippets_grouped(chunks, papers_by_id)
        prompt = LIST_PROMPT.format(snippets=snippets, question=question)
    elif mode == "compare":
        snippets = _format_snippets_grouped(chunks, papers_by_id)
        prompt = COMPARE_PROMPT.format(snippets=snippets, question=question)
    else:
        snippets = _format_snippets(chunks, papers_by_id)
        prompt = ANSWER_PROMPT.format(snippets=snippets, question=question)
    return prompt, mode


def query(
    question: str,
    n_papers: int = DEFAULT_N_PAPERS,
    k_chunks: int = DEFAULT_K_CHUNKS,
    stream: bool = False,
) -> LitQAResult:
    """两阶段检索 + 回答生成。"""
    papers = _retrieve_papers(question, n_papers)
    if not papers:
        return LitQAResult(answer="卡片库为空或未命中文献。请先运行 build_cards 脚本。", papers=[], chunks=[])

    paper_ids = [p.paper_id for p in papers]
    papers_by_id = {p.paper_id: p for p in papers}
    chunks = _retrieve_chunks_hybrid(question, paper_ids, k_chunks)
    if not chunks:
        return LitQAResult(answer="阶段二检索为空,可能命中的文献无对应 chunk。", papers=papers, chunks=[])
    for c in chunks:
        c.paper = papers_by_id.get(c.paper_id)

    prompt, _mode = build_prompt(question, chunks, papers_by_id)
    msgs = [{"role": "user", "content": prompt}]

    if stream:
        # 流式调用返回 generator
        gen = llm_client.chat(msgs, stream=True)
        return LitQAResult(answer=gen, papers=papers, chunks=chunks, debug={"stream": True})

    answer = llm_client.chat_json(msgs).strip()
    cited_ids = _collect_cited_indices(answer, len(chunks))
    appendix = _build_appendix(chunks, cited_ids)
    if appendix:
        answer = answer.rstrip() + "\n\n" + appendix
    return LitQAResult(answer=answer, papers=papers, chunks=chunks)


def _collect_cited_indices(text: str, n: int) -> list[int]:
    seen = set()
    for m in re.finditer(r"\[(\d+)\]", text):
        i = int(m.group(1))
        if 1 <= i <= n:
            seen.add(i)
    return sorted(seen)


def _build_appendix(chunks: list[ChunkHit], cited: list[int]) -> str:
    """在答案末尾追加被引用文献的列表(只列被 [n] 引到的)。

    格式: [n] 作者. 标题. *期刊名*, 年份.
    缺字段时优雅省略。
    """
    if not cited:
        return ""
    used_papers: dict[int, ChunkHit] = {}
    cite_no: dict[int, int] = {}
    for i in cited:
        c = chunks[i - 1]
        if c.paper_id not in used_papers:
            used_papers[c.paper_id] = c
            cite_no[c.paper_id] = i
    lines = ["**参考文献**"]
    for pid, c in used_papers.items():
        p = c.paper
        if not p:
            continue
        title = (p.title or "(无标题)").strip()
        parts = []
        # 作者
        authors = (p.authors or "").strip()
        if authors and authors not in ("[]", "['']", '[""]'):
            # 多作者只显示前 3 名 + et al.
            tokens = [a.strip() for a in authors.split(",") if a.strip()]
            if len(tokens) > 3:
                authors_disp = ", ".join(tokens[:3]) + ", et al."
            else:
                authors_disp = ", ".join(tokens)
            if not authors_disp.endswith("."):
                authors_disp += "."
            parts.append(authors_disp)
        # 标题
        parts.append(title.rstrip(".") + ".")
        # 期刊 + 年份
        journal = (p.journal or "").strip()
        year = p.year
        if journal and year:
            parts.append(f"*{journal}*, {year}.")
        elif journal:
            parts.append(f"*{journal}*.")
        elif year:
            parts.append(f"{year}.")
        n = cite_no.get(pid, "?")
        lines.append(f"[{n}] " + " ".join(parts))
    return "\n".join(lines)
