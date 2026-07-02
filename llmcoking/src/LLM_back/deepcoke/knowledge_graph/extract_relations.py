"""批3 关系图谱深化:从每篇 deep_summary/abstract 抽「带方向的关系三元组」。

产出 data/kg_relations.json:[{paper_id, title, year, triples:[[主体,关系,客体], ...]}]
与 kg_entities.json 分离(风险隔离,不动已有共现图);kg_index 读它做有向多跳。

关系类型限定几种(便于聚合):提高/降低/影响/表征/生成/取决于/正相关/负相关。

用法(服务器容器内,LLM 在线,可断点续,每篇 1 次 LLM ≈ 226 篇 30-40min):
  cd /opt/deepcoke/code/src/LLM_back
  LLM_MODE=openai DEEPSEEK_BASE_URL=http://127.0.0.1:11434/v1 DEEPSEEK_MODEL=qwen3:8b \
    DEEPSEEK_API_KEY=vllm-local CUDA_VISIBLE_DEVICES= \
    nohup python -X utf8 -u -m deepcoke.knowledge_graph.extract_relations > /tmp/kg_rel.log 2>&1 &
  # 完成标志:日志末尾 "[relations] 完成";看进度 tail -f /tmp/kg_rel.log
"""
import sys
import json
import time
import re
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from deepcoke import config          # noqa: E402
from deepcoke.llm_client import chat_json   # noqa: E402

_REL_TYPES = ["提高", "降低", "影响", "表征", "生成", "取决于", "正相关", "负相关"]

_PROMPT = """你是煤焦化/碳材料领域专家。给定论文标题+摘要,抽取"带方向的因果/关联关系三元组"。

只输出 JSON:{"triples": [["主体", "关系", "客体"], ...]}

关系(relation)只能用这几种之一:提高、降低、影响、表征、生成、取决于、正相关、负相关。
主体/客体用领域实体的标准简称(镜质组、惰质组、CSR、CRI、挥发分、流动度、乱层结构、微晶尺寸、XRD、HRTEM…)。
示例:[["镜质组含量","提高","CSR"], ["XRD","表征","微晶尺寸"], ["挥发分","负相关","CSR"]]
只抽论文明确支持的关系,最多 8 条;没有就返回 {"triples": []}。只输出 JSON。"""


def extract_relations(title: str, text: str) -> list:
    try:
        raw = chat_json(
            [{"role": "system", "content": _PROMPT},
             {"role": "user", "content": f"标题: {title}\n摘要/概要: {text[:2500]}"}],
            temperature=0.1,
        )
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        triples = json.loads(raw).get("triples") or []
        out = []
        for t in triples:
            if isinstance(t, (list, tuple)) and len(t) == 3:
                s, r, o = str(t[0]).strip(), str(t[1]).strip(), str(t[2]).strip()
                if s and o and r in _REL_TYPES:
                    out.append([s, r, o])
        return out[:8]
    except Exception as e:
        print(f"  抽取失败 '{title[:40]}': {e}")
        return []


def run():
    papers_db = config.DATA_DIR / "papers.db"
    out_file = config.DATA_DIR / "kg_relations.json"
    if not papers_db.exists():
        print(f"ERROR: papers.db not found: {papers_db}")
        return

    conn = sqlite3.connect(str(papers_db))
    conn.row_factory = sqlite3.Row
    cols = [r[1] for r in conn.execute("PRAGMA table_info(papers)").fetchall()]
    text_col = "deep_summary" if "deep_summary" in cols else "abstract"
    rows = conn.execute(
        f"SELECT id, title, year, abstract, {text_col} AS body FROM papers ORDER BY id"
    ).fetchall()
    total = len(rows)
    print(f"抽取关系三元组: {total} 篇 (正文列={text_col})")

    results, done = [], set()
    if out_file.exists():
        results = json.load(open(out_file, encoding="utf-8"))
        done = {r["paper_id"] for r in results}
        print(f"续跑: 已完成 {len(done)} 篇")

    t0 = time.time()
    for i, row in enumerate(rows, 1):
        pid = row["id"]
        if pid in done:
            continue
        title = row["title"] or ""
        body = (row["body"] or row["abstract"] or "").strip()
        if not body:
            continue
        triples = extract_relations(title, body)
        results.append({"paper_id": pid, "title": title, "year": row["year"], "triples": triples})
        print(f"[{i}/{total}] pid={pid} {len(triples)} 三元组  {title[:45]}")
        if i % 10 == 0:
            json.dump(results, open(out_file, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"  已存档 {len(results)} 篇 ({time.time() - t0:.0f}s)")

    json.dump(results, open(out_file, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    n_trip = sum(len(r["triples"]) for r in results)
    print(f"[relations] 完成: {len(results)} 篇, 共 {n_trip} 条关系 → {out_file}")


if __name__ == "__main__":
    run()
