"""
Phase 2 图表理解 — 给每个 figure chunk 用 VLM 生成图像描述,存 papers.db + 回写 chroma。

流程(每个 figure chunk):
  从 chroma 拿 figure chunk(paper_id/chunk_index/page/bbox/caption)
  → 渲染图注上方一条带(figure_render)→ VLM 描述(vlm_client)
  → 存 figure_summaries 表 + 回写该 chunk(document 拼上描述, metadata 加 figure_summary)

可断点续跑:已在 figure_summaries 表里的 (paper_id, chunk_index) 跳过。
图很多(生产 ~2000+),慢且耗 VLM,建议先 --limit 试跑、确认 VLM 通了再全量。

用法:
  cd src/LLM_back
  # 单篇试 / 限量试
  python -X utf8 -m deepcoke.literature_qa.build_figure_summaries --paper_id 6
  python -X utf8 -m deepcoke.literature_qa.build_figure_summaries --limit 20
  # 全量
  python -X utf8 -m deepcoke.literature_qa.build_figure_summaries
"""
import sys
import time
import argparse
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from deepcoke import config
from deepcoke.vectorstore.chromadb_store import get_collection
from deepcoke.ingestion.figure_render import render_figure_crop, render_page_png
from deepcoke import vlm_client

PROMPT = (
    "这是一篇焦化/煤炭/材料领域学术论文里的一张插图(附图注)。请用中文 60-120 字描述:"
    "图的类型(折线图/柱状图/示意图/SEM/TEM/XRD 谱/流程图等)、横纵轴或观察对象、"
    "以及图中体现的关键趋势或结论。只输出描述正文,不要'本图''该图'之类套话。\n图注:{caption}"
)


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS figure_summaries (
            paper_id INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            figure_no TEXT,
            page INTEGER,
            caption TEXT,
            summary TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (paper_id, chunk_index)
        )
    """)
    conn.commit()


def _parse_bbox(s):
    try:
        return [float(v) for v in (s or "").split(",")]
    except Exception:
        return None


def get_figure_chunks(coll):
    """取所有 figure 类型 chunk。"""
    raw = coll.get(where={"block_type": "figure"}, limit=100000)
    out = []
    if not raw or not raw.get("ids"):
        return out
    for i, cid in enumerate(raw["ids"]):
        m = raw["metadatas"][i] or {}
        out.append({
            "chunk_id": cid,
            "paper_id": m.get("paper_id"),
            "chunk_index": m.get("chunk_index", 0),
            "page": m.get("page_start", 0),
            "figure_no": m.get("figure_no", ""),
            "bbox": _parse_bbox(m.get("bbox", "")),
            "caption": raw["documents"][i] or "",
            "meta": m,
        })
    return out


def run(limit=None, only_paper=None):
    conn = sqlite3.connect(str(config.DATA_DIR / "papers.db"))
    ensure_table(conn)

    # paper_id → file_path
    paths = {r[0]: r[1] for r in conn.execute("SELECT id, file_path FROM papers").fetchall()}
    done = {(r[0], r[1]) for r in conn.execute(
        "SELECT paper_id, chunk_index FROM figure_summaries").fetchall()}

    coll = get_collection()
    figs = get_figure_chunks(coll)
    if only_paper:
        figs = [f for f in figs if f["paper_id"] == only_paper]
    figs = [f for f in figs if (f["paper_id"], f["chunk_index"]) not in done]
    figs.sort(key=lambda f: (f["paper_id"] or 0, f["chunk_index"]))
    if limit:
        figs = figs[:limit]

    print(f"待处理 figure chunk: {len(figs)} (已完成 {len(done)})")
    if not vlm_client.vlm_available():
        print(f"⚠️ VLM 端点连不上 ({vlm_client.VLM_MODE} @ {config.VLM_BASE_URL}, model={config.VLM_MODEL})")
        print("   请先确认视觉模型已部署(Ollama: ollama pull qwen2.5vl;或 vLLM 起 VL 模型),再跑。")
        return

    ok = fail = skip = 0
    t0 = time.time()
    for i, f in enumerate(figs, 1):
        pid = f["paper_id"]
        fp = paths.get(pid)
        if not fp or not Path(fp).exists():
            skip += 1
            continue
        # 渲染图像:优先图注上方裁带,bbox 缺失退整页
        png = None
        if f["bbox"] and len(f["bbox"]) == 4:
            png = render_figure_crop(fp, f["page"], f["bbox"])
        if png is None:
            png = render_page_png(fp, f["page"])
        if png is None:
            skip += 1
            continue

        try:
            summary = vlm_client.describe_image(png, PROMPT.format(caption=f["caption"][:300]))
        except Exception as e:
            print(f"  [{i}/{len(figs)}] VLM 失败 paper={pid} ci={f['chunk_index']}: {str(e)[:80]}")
            fail += 1
            continue
        if not summary:
            fail += 1
            continue

        # 存表
        conn.execute(
            "INSERT OR REPLACE INTO figure_summaries (paper_id, chunk_index, figure_no, page, caption, summary) "
            "VALUES (?,?,?,?,?,?)",
            (pid, f["chunk_index"], f["figure_no"], f["page"], f["caption"][:500], summary),
        )
        conn.commit()
        # 回写 chroma chunk:document 拼描述(供检索), metadata 加 figure_summary
        new_doc = f["caption"].strip() + "\n[图像描述] " + summary
        new_meta = dict(f["meta"])
        new_meta["figure_summary"] = summary[:900]
        try:
            coll.upsert(ids=[f["chunk_id"]], documents=[new_doc], metadatas=[new_meta])
        except Exception as e:
            print(f"  warn: 回写 chroma 失败 {f['chunk_id']}: {str(e)[:60]}")
        ok += 1
        if i % 10 == 0 or i == len(figs):
            el = time.time() - t0
            rate = el / max(ok, 1)
            print(f"  [{i}/{len(figs)}] ok={ok} fail={fail} skip={skip} | {el:.0f}s ({rate:.1f}s/图)")

    conn.close()
    print(f"\n完成: ok={ok} fail={fail} skip={skip} | {time.time()-t0:.0f}s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--paper_id", type=int, default=None)
    args = ap.parse_args()
    run(limit=args.limit, only_paper=args.paper_id)


if __name__ == "__main__":
    main()
