"""主题分库 阶段1:给每篇文献打「科学主题」标签(逻辑分库,不物理拆)。

固定一套领域主题(6 个),逐篇 LLM 归类 → 写回 papers.db 的 topic 列 + 回写 chroma chunk metadata。
chunk 继承文献主题 → 检索时可按 topic 软路由(阶段2)。

主题(topic)固定枚举,便于问题侧路由对齐:
  carbon_structure  碳结构演化与微晶(HRTEM/XRD/乱层结构/石墨化)
  coal_blending     配煤优化与煤间相互作用(blend/相容性/配比)
  pyrolysis         煤热解机理(热解/官能团/键能/ReaxFF)
  characterization  表征方法学(NMR/FTIR/XPS/TG-MS/CT 为主的方法论文)
  coke_quality      焦炭质量与预测(CSR/CRI/强度/气孔)
  plastic_layer     胶质层与热塑性(流动度/渗透/膨胀压力)

用法(服务器容器内,LLM 在线,可断点续):
  cd /opt/deepcoke/code/src/LLM_back
  LLM_MODE=openai DEEPSEEK_BASE_URL=http://127.0.0.1:11434/v1 DEEPSEEK_MODEL=qwen3:8b \
    DEEPSEEK_API_KEY=vllm-local CUDA_VISIBLE_DEVICES= \
    /opt/conda/envs/deepcoke/bin/python -X utf8 -m deepcoke.literature_qa.assign_topics
  # 只写库不回写 chroma:  --no-chroma ;  重跑全部:  --force
"""
import sys
import re
import time
import argparse
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from deepcoke import config              # noqa: E402
from deepcoke.llm_client import chat     # noqa: E402

TOPICS = {
    "carbon_structure": "碳结构演化与微晶(HRTEM/XRD/乱层结构/石墨化/微晶尺寸)",
    "coal_blending": "配煤优化与煤间相互作用(blend/相容性/配比/协同)",
    "pyrolysis": "煤热解机理(热解/官能团/键能/自由基/ReaxFF/模型化合物)",
    "characterization": "表征方法学(NMR/FTIR/XPS/TG-MS/CT 等方法本身为主)",
    "coke_quality": "焦炭质量与预测(CSR/CRI/强度/气孔/反应性)",
    "plastic_layer": "胶质层与热塑性(流动度/渗透性/膨胀压力/塑性)",
}
_KEYS = list(TOPICS.keys())

_PROMPT = (
    "你是煤焦化领域专家。把给定论文归入下列 6 个主题之一(只选最主要的一个),只输出主题英文 key。\n\n"
    + "\n".join(f"- {k}: {v}" for k, v in TOPICS.items())
    + "\n\n只输出一个 key(如 carbon_structure),不要解释。"
)


def classify(title: str, abstract: str) -> str:
    try:
        resp = chat(
            [{"role": "system", "content": _PROMPT},
             {"role": "user", "content": f"标题: {title}\n摘要: {abstract[:1500]}"}],
            stream=False,
        )
        # _NonStreamResponse 模拟 OpenAI: resp.choices[0].message.content
        txt = resp.choices[0].message.content or ""
        # Qwen3 可能带 <think>...</think>,剥掉
        txt = re.sub(r"<think>[\s\S]*?</think>", "", txt).lower()
        for k in _KEYS:
            if k in txt:
                return k
        return ""   # 匹配不到返回空(不硬兜底成 carbon_structure,避免掩盖问题)
    except Exception as e:
        print(f"  分类失败: {e}")
        return "carbon_structure"


def ensure_column(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(papers)").fetchall()]
    if "topic" not in cols:
        conn.execute("ALTER TABLE papers ADD COLUMN topic TEXT")
        conn.commit()
        print("papers.db 加 topic 列")


def run(force: bool, write_chroma: bool):
    db = sqlite3.connect(str(config.DATA_DIR / "papers.db"))
    ensure_column(db)
    where = "" if force else "WHERE topic IS NULL OR topic = ''"
    rows = db.execute(f"SELECT id, title, abstract FROM papers {where}").fetchall()
    print(f"待分类 {len(rows)} 篇")

    assigned = {}
    t0 = time.time()
    miss = 0
    for i, (pid, title, abstract) in enumerate(rows, 1):
        topic = classify(title or "", abstract or "")
        if not topic:
            topic = "carbon_structure"   # 兜底(仅少量)
            miss += 1
        db.execute("UPDATE papers SET topic = ? WHERE id = ?", (topic, pid))
        assigned[pid] = topic
        if i % 10 == 0:
            db.commit()
        print(f"[{i}/{len(rows)}] pid={pid} → {topic}  {(title or '')[:40]}")
    if miss:
        print(f"⚠ {miss} 篇 LLM 未给出明确主题,兜底 carbon_structure")
    db.commit()
    print(f"分类完成 {len(rows)} 篇 ({time.time() - t0:.0f}s)")

    # 分布
    import collections
    dist = collections.Counter(r[0] for r in db.execute("SELECT topic FROM papers WHERE topic IS NOT NULL"))
    print("主题分布:", dict(dist))

    # 回写 chroma:chunk metadata 加 topic(检索时 where 过滤/加权用)
    if write_chroma and assigned:
        try:
            from deepcoke.vectorstore.chromadb_store import get_collection
            coll = get_collection()
            n = 0
            for pid, topic in assigned.items():
                raw = coll.get(where={"paper_id": int(pid)}, include=["metadatas"])
                ids = raw.get("ids") or []
                metas = raw.get("metadatas") or []
                if not ids:
                    continue
                for m in metas:
                    m["topic"] = topic
                coll.update(ids=ids, metadatas=metas)
                n += len(ids)
            print(f"回写 chroma: {n} chunks 加 topic")
        except Exception as e:
            print(f"回写 chroma 失败(不影响库标签): {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="重跑全部(默认只跑未分类的)")
    ap.add_argument("--no-chroma", action="store_true", help="只写 papers.db,不回写 chroma")
    args = ap.parse_args()
    run(args.force, not args.no_chroma)
