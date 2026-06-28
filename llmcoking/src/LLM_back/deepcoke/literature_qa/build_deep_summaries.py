"""
为每篇文献生成结构化深度摘要(800-1200字)。

跟 build_cards.py 区别:
- build_cards: 80-150 字短 abstract (快速元数据)
- 本脚本: 800-1200 字结构化 deep summary (代替全文给 agent 用)

设计:
1. papers.db 加新列 deep_summary TEXT (IF NOT EXISTS)
2. 读每篇全文(从 ChromaDB 拼回所有 chunks,跳 References/Acknowledgments)
3. 喂给 LLM 生成结构化摘要(研究问题/方法/发现/参数/局限)
4. 写回 papers.db
5. 支持 --resume 跳过已生成的, --limit N 测试

Usage(在 dbcloud 容器内):
    cd /opt/deepcoke/code/src/LLM_back
    export LLM_MODE=openai
    export DEEPSEEK_BASE_URL=http://127.0.0.1:11434/v1
    export DEEPSEEK_MODEL=qwen3:8b
    export DEEPSEEK_API_KEY=vllm-local
    python -X utf8 -m deepcoke.literature_qa.build_deep_summaries --limit 3   # 先测 3 篇
    python -X utf8 -m deepcoke.literature_qa.build_deep_summaries             # 全量(~2小时)

输出文件不变 (papers.db),但加了 deep_summary 列。
"""
import argparse
import logging
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger("deep_summaries")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


SUMMARY_PROMPT = """你是焦化/煤炭领域的研究助理。下面是一篇学术论文的正文,每段开头有 [#N] 标记表示原文段落编号。

请生成一份 800-1200 字的**结构化深度摘要**,将完整代替全文给后续问答系统使用。

要求:
1. 必须**保留所有定量数据**(温度/压力/比例/相关系数 r²/百分比等),不要省略数字。
2. **每个 claim 末尾必须加 [#N] 引用标记**,N 是原文对应段落编号(例:"Zofiówka 60-80% 时 CSR≥45 [#15]")。
   - 一句话可能引用多个段落,如 "[#15][#16]"。
   - 没有原文依据的内容不要写。
3. 不要写"本文研究了..."、"本文提出了..."这类空话,直接陈述事实。
4. 区分"实验数据"与"作者推断/解释",注明哪些是实测。
5. 用中文输出,术语保留英文(如 CSR、CRI、VM、Ash 等专业缩写)。

按下面 Markdown 结构输出(不要前缀,不要 markdown 代码块包裹):

## 研究问题
(1-2 句,论文要解决什么具体问题,带 [#N] 引用)

## 关键方法
(实验/计算/建模方法,含关键设备/试剂/算法 + 关键参数,带 [#N] 引用)

## 主要发现
(论文核心结论,**每个 claim 必须有 [#N]**,且**必须包含定量数据**)

## 关键参数与适用条件
(论文中讨论的主要变量范围、煤种组合、工况条件,带 [#N])

## 局限性
(论文自承的局限,带 [#N];或显而易见的不适用范围)

## 与焦化/煤炭主线的关系
(本论文跟"焦炭质量 / 配煤优化 / 碳中和 / 热解反应"等主线问题的关联,不需要引用)

论文正文:
{fulltext}

深度摘要(每个 claim 末尾必须加 [#N] 引用):"""


SKIP_SECTIONS = {
    "references", "reference", "bibliography",
    "acknowledgments", "acknowledgements", "acknowledgment",
    "author contributions", "competing interests",
    "supplementary", "supplementary material",
    "appendix",
}
MAX_FULLTEXT_CHARS = 38000   # 给 LLM 的全文上限(留 4K context 给 prompt + 1500 chars summary)


def add_column_if_missing(conn: sqlite3.Connection):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(papers)").fetchall()]
    if "deep_summary" not in cols:
        conn.execute("ALTER TABLE papers ADD COLUMN deep_summary TEXT")
        conn.commit()
        logger.info("added column papers.deep_summary")
    if "deep_summary_at" not in cols:
        conn.execute("ALTER TABLE papers ADD COLUMN deep_summary_at TIMESTAMP")
        conn.commit()
        logger.info("added column papers.deep_summary_at")
    if "deep_summary_chunks" not in cols:
        # JSON 字段: [{chunk_index, section, text_preview}, ...]
        # 给前端做 [#N] → 原文段落 反查用
        conn.execute("ALTER TABLE papers ADD COLUMN deep_summary_chunks TEXT")
        conn.commit()
        logger.info("added column papers.deep_summary_chunks")


def reconstruct_fulltext(col, paper_id: int) -> tuple[str, str, list[dict]]:
    """从 ChromaDB 拼回某 paper 的所有 chunk,按章节顺序,**每段开头加 [#chunk_index] 编号**。

    返回 (title, numbered_fulltext, chunks_meta)
      - numbered_fulltext: 给 LLM 看的字符串,每段前有 [#N]
      - chunks_meta: [{chunk_index, section, text_preview}] 给 papers.db 存,
                     前端能根据 [#N] 反查到原文段落
    """
    raw = col.get(where={"paper_id": int(paper_id)}, limit=400)
    if not raw or not raw.get("ids"):
        return "", "", []

    title = ""
    section_groups: dict[str, list[tuple[int, str]]] = defaultdict(list)
    section_order: list[str] = []

    for i, meta in enumerate(raw["metadatas"]):
        if not title and meta.get("title"):
            title = meta.get("title", "")
        section = (meta.get("section") or "Body").strip()
        if section.lower() in SKIP_SECTIONS:
            continue
        if section not in section_order:
            section_order.append(section)
        section_groups[section].append((
            meta.get("chunk_index", 0),
            raw["documents"][i],
        ))

    parts = []
    chunks_meta: list[dict] = []
    total_chars = 0
    truncated = False

    for section in section_order:
        chunks_sorted = sorted(section_groups[section])
        section_parts = []
        for ci, txt in chunks_sorted:
            # 截断检查
            chunk_segment = f"\n\n[#{ci}] {txt}"
            if total_chars + len(chunk_segment) > MAX_FULLTEXT_CHARS:
                truncated = True
                break
            section_parts.append(chunk_segment)
            chunks_meta.append({
                "chunk_index": ci,
                "section": section,
                "text_preview": txt[:300],  # 给前端高光时定位用
            })
            total_chars += len(chunk_segment)
        if section_parts:
            parts.append(f"## {section}" + "".join(section_parts))
        if truncated:
            parts.append("... [全文截断,未传所有章节]")
            break

    numbered_fulltext = f"# {title}\n\n" + "\n\n".join(parts) if parts else ""
    return title, numbered_fulltext, chunks_meta


def generate_summary(fulltext: str, max_tokens: int = 1800) -> str:
    """调 LLM 生成 deep summary。"""
    from deepcoke.llm_client import chat_json
    prompt = SUMMARY_PROMPT.format(fulltext=fulltext)
    messages = [{"role": "user", "content": prompt}]
    return chat_json(messages, temperature=0.2, max_tokens=max_tokens).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="只处理前 N 篇,0=全部")
    ap.add_argument("--paper-ids", type=str, default="",
                    help="只处理指定 paper_id,逗号分隔,如 191,176,167")
    ap.add_argument("--force", action="store_true",
                    help="覆盖已生成的(默认 skip)")
    ap.add_argument("--db", type=str, default="",
                    help="papers.db 路径(默认 config.DATA_DIR/papers.db)")
    ap.add_argument("--dry-run", action="store_true",
                    help="不调 LLM,用 fake 字符串验证整个流程(拼全文+写 db+进度)")
    args = ap.parse_args()

    from deepcoke import config
    from deepcoke.vectorstore.chromadb_store import get_collection

    db_path = args.db or str(config.DATA_DIR / "papers.db")
    logger.info(f"papers.db = {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    add_column_if_missing(conn)

    coll = get_collection()

    # 选择要处理的 paper_id
    if args.paper_ids:
        target_pids = [int(x) for x in args.paper_ids.split(",") if x.strip()]
    else:
        sql = "SELECT id FROM papers"
        if not args.force:
            sql += " WHERE deep_summary IS NULL OR deep_summary = ''"
        sql += " ORDER BY id"
        if args.limit > 0:
            sql += f" LIMIT {args.limit}"
        target_pids = [r[0] for r in conn.execute(sql).fetchall()]

    logger.info(f"target papers: {len(target_pids)}")

    success = 0
    failed = 0
    skipped = 0
    t_start = time.time()

    for idx, pid in enumerate(target_pids, 1):
        existing = conn.execute(
            "SELECT deep_summary FROM papers WHERE id = ?", (pid,)
        ).fetchone()
        if existing and existing[0] and not args.force:
            skipped += 1
            continue

        try:
            title, fulltext, chunks_meta = reconstruct_fulltext(coll, pid)
            if not fulltext or len(fulltext) < 500:
                logger.warning(f"  [{idx}/{len(target_pids)}] pid={pid} title={title[:60]!r}: fulltext too short ({len(fulltext)} chars), skip")
                failed += 1
                continue

            t0 = time.time()
            if args.dry_run:
                # 生成 fake summary 引用前几个 chunk_index 让前端能看到效果
                cited = [c["chunk_index"] for c in chunks_meta[:3]]
                cite_tag = "".join(f"[#{c}]" for c in cited) if cited else "[#0]"
                summary = (
                    f"[DRY-RUN] Fake summary for paper {pid} ({title[:30]}).\n"
                    f"## 研究问题\nstub stub {cite_tag}.\n"
                    f"## 关键方法\nstub stub {cite_tag}.\n"
                    f"## 主要发现\nstub stub {cite_tag}.\n"
                    f"## 关键参数与适用条件\nstub {cite_tag}.\n"
                    f"## 局限性\nstub {cite_tag}.\n"
                    f"## 与焦化主线的关系\nstub.\n"
                )
            else:
                summary = generate_summary(fulltext)
            elapsed = time.time() - t0

            if len(summary) < 200:
                logger.warning(f"  [{idx}/{len(target_pids)}] pid={pid}: summary too short ({len(summary)} chars), skip write")
                failed += 1
                continue

            import json as _json
            conn.execute(
                "UPDATE papers SET deep_summary = ?, deep_summary_chunks = ?, deep_summary_at = CURRENT_TIMESTAMP WHERE id = ?",
                (summary, _json.dumps(chunks_meta, ensure_ascii=False), pid),
            )
            conn.commit()
            success += 1

            # 统计 summary 里出现了多少 [#N] 引用 + 多少 unique
            import re as _re
            cited_refs = _re.findall(r"\[#(\d+)\]", summary)
            unique_refs = len(set(cited_refs))

            avg_per = (time.time() - t_start) / idx
            eta_min = avg_per * (len(target_pids) - idx) / 60
            logger.info(
                f"  [{idx}/{len(target_pids)}] pid={pid} OK | "
                f"fulltext={len(fulltext)} chunks={len(chunks_meta)} → summary={len(summary)} "
                f"refs={len(cited_refs)}({unique_refs} unique) | "
                f"{elapsed:.1f}s | ETA {eta_min:.0f} min | {title[:50]!r}"
            )
        except Exception as e:
            failed += 1
            logger.error(f"  [{idx}/{len(target_pids)}] pid={pid} ERROR: {e}")
            time.sleep(2)  # 喘口气

    conn.close()
    total_min = (time.time() - t_start) / 60
    logger.info(
        f"=== DONE | success={success} skipped={skipped} failed={failed} | total {total_min:.1f} min"
    )


if __name__ == "__main__":
    main()
