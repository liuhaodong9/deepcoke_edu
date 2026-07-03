"""P2 垂直特色:篇级实验条件画像抽取(焦化过程参数—碳结构—性能指标)。

跟定量三表(行级逐样品数值)互补:本模块产出每篇一个"实验条件卡片",
用于来源卡快速展示 + 检索过滤 + GraphRAG 联动。字段贴合博士课题。

产出:papers.db 新表 exp_conditions(paper_id 主键) + 回写 chroma chunk metadata(exp_* 标签,便于软路由)。

字段:
  coal_types      煤种/煤阶(气煤/肥煤/焦煤/瘦煤/无烟煤/褐煤...)
  macerals        镜质组/惰质组/壳质组 相关
  temp_range      温度范围(如 "600-1000℃")
  heating_rate    升温速率(如 "3℃/min")
  atmosphere      气氛(N2/Ar/真空/空气...)
  residence_time  停留/保温时间
  methods         表征方法(XRD/Raman/HRTEM/NMR/FTIR/TG...)
  structure_idx   结构指标(La/Lc/d002/乱层/微晶...)
  perf_idx        性能指标(CSR/CRI/强度/反应性/孔隙率...)

用法(服务器容器内,LLM 在线,可断点续,~226篇 20-40min,与聊天抢 72B):
  cd /opt/deepcoke/code/src/LLM_back
  LLM_MODE=openai DEEPSEEK_BASE_URL=http://127.0.0.1:11434/v1 DEEPSEEK_MODEL=qwen3:8b \
    DEEPSEEK_API_KEY=vllm-local CUDA_VISIBLE_DEVICES= \
    nohup /opt/conda/envs/deepcoke/bin/python -X utf8 -u -m deepcoke.literature_qa.extract_exp_conditions > /tmp/exp_cond.log 2>&1 &
  # 完成标志: 日志末尾 "[exp_cond] 完成";  --force 重跑;  --no-chroma 只写库
"""
import sys
import os
import json
import re
import time
import argparse
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from deepcoke import config              # noqa: E402
from deepcoke.llm_client import chat_json   # noqa: E402

_FIELDS = ["coal_types", "macerals", "temp_range", "heating_rate",
           "atmosphere", "residence_time", "methods", "structure_idx", "perf_idx"]

_PROMPT = """你是焦化/煤化学领域专家。从论文标题+摘要抽取"实验条件画像"。只输出 JSON,字段:
{
 "coal_types": "煤种/煤阶(气煤/肥煤/焦煤/瘦煤/无烟煤/褐煤/烟煤等,或空)",
 "macerals": "镜质组/惰质组/壳质组 相关(或空)",
 "temp_range": "温度范围如 600-1000℃(或空)",
 "heating_rate": "升温速率如 3℃/min(或空)",
 "atmosphere": "气氛 N2/Ar/真空/空气/CO2(或空)",
 "residence_time": "停留/保温时间(或空)",
 "methods": "表征方法逗号分隔 XRD,Raman,HRTEM,NMR,FTIR,TG,XPS,SEM(或空)",
 "structure_idx": "结构指标 La,Lc,d002,乱层结构,微晶尺寸,芳香度(或空)",
 "perf_idx": "性能指标 CSR,CRI,强度,反应性,孔隙率,流动度(或空)"
}
只抽论文明确提到的,没有就留空字符串。不编造。只输出 JSON。"""


def extract_one(title: str, abstract: str) -> dict:
    try:
        raw = chat_json(
            [{"role": "system", "content": _PROMPT},
             {"role": "user", "content": f"标题: {title}\n摘要: {abstract[:2000]}"}],
            temperature=0.1,
        )
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw)
        d = json.loads(raw)
        return {f: str(d.get(f, "") or "").strip()[:200] for f in _FIELDS}
    except Exception as e:
        print(f"  抽取失败 '{title[:40]}': {e}")
        return {f: "" for f in _FIELDS}


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS exp_conditions (
            paper_id INTEGER PRIMARY KEY,
            coal_types TEXT, macerals TEXT, temp_range TEXT, heating_rate TEXT,
            atmosphere TEXT, residence_time TEXT, methods TEXT,
            structure_idx TEXT, perf_idx TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def run(force: bool, write_chroma: bool):
    db = sqlite3.connect(str(config.DATA_DIR / "papers.db"))
    ensure_table(db)
    done = set()
    if not force:
        done = {r[0] for r in db.execute("SELECT paper_id FROM exp_conditions")}
    rows = db.execute("SELECT id, title, abstract FROM papers ORDER BY id").fetchall()
    todo = [r for r in rows if r[0] not in done]
    print(f"实验条件抽取: 待处理 {len(todo)}/{len(rows)} 篇")

    assigned = {}
    t0 = time.time()
    for i, (pid, title, abstract) in enumerate(todo, 1):
        d = extract_one(title or "", abstract or "")
        db.execute(
            "INSERT OR REPLACE INTO exp_conditions "
            "(paper_id, coal_types, macerals, temp_range, heating_rate, atmosphere, "
            "residence_time, methods, structure_idx, perf_idx) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, d["coal_types"], d["macerals"], d["temp_range"], d["heating_rate"],
             d["atmosphere"], d["residence_time"], d["methods"], d["structure_idx"], d["perf_idx"]))
        assigned[pid] = d
        nonempty = sum(1 for v in d.values() if v)
        if i % 10 == 0:
            db.commit()
        print(f"[{i}/{len(todo)}] pid={pid} {nonempty}/9 字段  {(title or '')[:40]}")
    db.commit()
    print(f"抽取完成 {len(todo)} 篇 ({time.time() - t0:.0f}s)")

    # 回写 chroma:每 chunk 加 exp_methods / exp_coal / exp_perf(精简,供来源卡与过滤)
    if write_chroma and assigned:
        try:
            from deepcoke.vectorstore.chromadb_store import get_collection
            coll = get_collection()
            n = 0
            for pid, d in assigned.items():
                raw = coll.get(where={"paper_id": int(pid)}, include=["metadatas"])
                ids, metas = raw.get("ids") or [], raw.get("metadatas") or []
                if not ids:
                    continue
                for m in metas:
                    m["exp_methods"] = d["methods"][:120]
                    m["exp_coal"] = d["coal_types"][:80]
                    m["exp_perf"] = d["perf_idx"][:80]
                coll.update(ids=ids, metadatas=metas)
                n += len(ids)
            print(f"回写 chroma: {n} chunks 加 exp_* 标签")
        except Exception as e:
            print(f"回写 chroma 失败(不影响库): {e}")

    print("[exp_cond] 完成")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-chroma", action="store_true")
    args = ap.parse_args()
    run(args.force, not args.no_chroma)
