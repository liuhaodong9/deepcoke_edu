"""焦化文献定量数据离线抽取脚本。

从 ChromaDB 拿每篇文献的全部 chunks，喂给 LLM，强制输出
{samples: [...], experiments: [...], microstructure: [...]} JSON，
落库到 papers.db 的 coal_samples / coke_experiments / carbon_microstructure。

设计:
- 每篇文献单独一次抽取，互不影响（一篇坏掉不影响其他）
- 每个数值字段必须带 evidence_quote，事后用字符串匹配校验
- 抽完写一行 jsonl 日志到 data/extraction_log.jsonl，方便回查

CLI:
  python -X utf8 -m deepcoke.literature_qa.extract_quant_table --paper-id 5
  python -X utf8 -m deepcoke.literature_qa.extract_quant_table --all
  python -X utf8 -m deepcoke.literature_qa.extract_quant_table --all --limit 10
  python -X utf8 -m deepcoke.literature_qa.extract_quant_table --all --skip-existing
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import config
from ..llm_client import chat_json
from ..vectorstore.chromadb_store import get_collection
from .quant_schema import (
    PAPERS_DB_PATH,
    get_conn,
    init_quant_tables,
)


# ── 配置 ────────────────────────────────────────────────────────────
EXTRACTION_LOG = config.DATA_DIR / "extraction_log.jsonl"
# LLM 原始输出落盘目录(每篇一个 json),供事后重新校验而不必重跑 LLM
RAW_OUTPUT_DIR = config.DATA_DIR / "extraction_raw"

# 接地校验阈值: evidence_quote 的有效 token 在全文中的出现比例下限。
# 由 paper 6(真值 ~0.44)/paper 10(真值 1.0)/假值(0.0)的判别实验定标。
QUOTE_OVERLAP_MIN = 0.4

# 喂给 LLM 的 chunks 总长上限（字符）。超过截断。
MAX_CONTEXT_CHARS = 24000

# 抽取时排除的章节（综述/格式化区不要喂，污染数值）
EXCLUDED_SECTIONS = {"abstract", "references", "acknowledgements", "acknowledgments"}


# ── 物理合理范围 sanity check ────────────────────────────────────────
SANITY_RANGES = {
    # coal_samples
    "ash_pct": (0, 60),
    "volatile_pct": (0, 60),
    "fixed_carbon_pct": (10, 95),
    "sulfur_pct": (0, 10),
    "vitrinite_reflectance": (0.2, 4.0),
    "fluidity_log_ddpm": (0, 5.5),
    # coke_experiments
    "coking_temp_c": (300, 1500),
    "heating_rate_c_per_min": (0.1, 100),
    "coking_time_min": (1, 10000),
    "cri": (0, 100),
    "csr": (0, 100),
    "cbi": (0, 100),
    "coke_yield_pct": (0, 100),
    # carbon_microstructure
    "La_nm": (0.3, 100),
    "Lc_nm": (0.3, 100),
    "d002_nm": (0.30, 0.45),
    "xrd_peak_2theta": (10, 35),
    "isotropic_pct": (0, 100),
    "anisotropic_pct": (0, 100),
    "mosaic_pct": (0, 100),
    "porosity_pct": (0, 100),
    "mean_pore_size_um": (0.001, 1000),
}


# ── Prompt ─────────────────────────────────────────────────────────
_SYS_PROMPT = """You are an expert metallurgical chemist extracting quantitative data from coal coking research papers.

Given the Methods/Results/Discussion text of one paper, extract THREE arrays of records:

1) `samples` — one record per distinct coal sample analyzed:
   {sample_label, coal_type, origin, ash_pct, volatile_pct, fixed_carbon_pct, sulfur_pct,
    vitrinite_reflectance, fluidity_log_ddpm, evidence_section, evidence_quote}

2) `experiments` — one record per distinct carbonization/coking experiment (different blend OR different temperature counts as a different experiment):
   {sample_label, blend_recipe, coking_temp_c, heating_rate_c_per_min, coking_time_min,
    cri, csr, cbi, coke_yield_pct, gas_composition, evidence_section, evidence_quote}
   - `blend_recipe`: list of {sample_label, pct} (sum should ~100). Single-coal experiments: a single entry with pct=100.
   - `gas_composition`: object like {H2: 50.2, CO: 30.1, CH4: 10.0, CO2: 5.0} in vol%.

3) `microstructure` — one record per distinct sample for which X-ray/optical microstructure was reported:
   {sample_label, La_nm, Lc_nm, d002_nm, xrd_peak_2theta, isotropic_pct, anisotropic_pct,
    mosaic_pct, porosity_pct, mean_pore_size_um, evidence_section, evidence_quote}

STRICT RULES — violating any disqualifies the record:
- For every NUMERIC field, you MUST provide an `evidence_quote` (≤200 chars of EXACT VERBATIM text from the source) that contains the number. If no quote can be found, the field MUST be null.
- Missing/unmentioned values → null. NEVER fill with 0, "N/A", "unknown", or made-up numbers.
- DO NOT pull numbers from Abstract or summary paragraphs — those are ranges, not measurements.
- Unit normalization (apply BEFORE writing):
    * Temperature → ℃ (Celsius). If °F or K, convert.
    * Fluidity → log(ddpm). If reported as ddpm, take log10.
    * CRI/CSR/CBI/coke_yield → percent in [0, 100].
    * d002 → nm (NOT angstroms). 0.34 nm = 3.4 Å.
    * La/Lc → nm.
    * Pore size → μm.
- If the paper reports MULTIPLE blends or temperatures, output ONE record per condition. NEVER average them.
- `evidence_section` should be the closest section name you can identify (e.g. "Results", "Table 3", "Section 3.2").

Output ONLY a valid JSON object with exactly these three top-level keys:
{
  "samples": [...],
  "experiments": [...],
  "microstructure": [...]
}
No prose, no markdown fences, no explanations.
"""


_FEW_SHOT_USER = """### Example input ###
Paper title: Effect of vitrinite reflectance on CSR of metallurgical coke
Section: Materials and Methods
Two bituminous coals were used: Coal A (Vdaf=28.5%, Ad=8.2%, Ro,max=1.05%) and Coal B (Vdaf=22.1%, Ad=9.4%, Ro,max=1.32%).

Section: Results
A blend of 70% Coal A and 30% Coal B was coked at 1050°C for 18 h. The resulting coke gave CRI=27.3% and CSR=64.5%. A second blend (50:50) at the same temperature gave CRI=29.8%, CSR=58.2%. XRD of the 70:30 coke showed La=4.2 nm, Lc=2.1 nm, d002=3.45 Å.
"""

_FEW_SHOT_ASSISTANT = """{
  "samples": [
    {"sample_label": "Coal A", "coal_type": null, "origin": null, "ash_pct": 8.2, "volatile_pct": 28.5, "fixed_carbon_pct": null, "sulfur_pct": null, "vitrinite_reflectance": 1.05, "fluidity_log_ddpm": null, "evidence_section": "Materials and Methods", "evidence_quote": "Coal A (Vdaf=28.5%, Ad=8.2%, Ro,max=1.05%)"},
    {"sample_label": "Coal B", "coal_type": null, "origin": null, "ash_pct": 9.4, "volatile_pct": 22.1, "fixed_carbon_pct": null, "sulfur_pct": null, "vitrinite_reflectance": 1.32, "fluidity_log_ddpm": null, "evidence_section": "Materials and Methods", "evidence_quote": "Coal B (Vdaf=22.1%, Ad=9.4%, Ro,max=1.32%)"}
  ],
  "experiments": [
    {"sample_label": "70A/30B blend", "blend_recipe": [{"sample_label": "Coal A", "pct": 70}, {"sample_label": "Coal B", "pct": 30}], "coking_temp_c": 1050, "heating_rate_c_per_min": null, "coking_time_min": 1080, "cri": 27.3, "csr": 64.5, "cbi": null, "coke_yield_pct": null, "gas_composition": null, "evidence_section": "Results", "evidence_quote": "A blend of 70% Coal A and 30% Coal B was coked at 1050°C for 18 h. The resulting coke gave CRI=27.3% and CSR=64.5%."},
    {"sample_label": "50A/50B blend", "blend_recipe": [{"sample_label": "Coal A", "pct": 50}, {"sample_label": "Coal B", "pct": 50}], "coking_temp_c": 1050, "heating_rate_c_per_min": null, "coking_time_min": null, "cri": 29.8, "csr": 58.2, "cbi": null, "coke_yield_pct": null, "gas_composition": null, "evidence_section": "Results", "evidence_quote": "A second blend (50:50) at the same temperature gave CRI=29.8%, CSR=58.2%."}
  ],
  "microstructure": [
    {"sample_label": "70A/30B coke", "La_nm": 4.2, "Lc_nm": 2.1, "d002_nm": 0.345, "xrd_peak_2theta": null, "isotropic_pct": null, "anisotropic_pct": null, "mosaic_pct": null, "porosity_pct": null, "mean_pore_size_um": null, "evidence_section": "Results", "evidence_quote": "XRD of the 70:30 coke showed La=4.2 nm, Lc=2.1 nm, d002=3.45 Å."}
  ]
}"""


# ── 数据结构 ─────────────────────────────────────────────────────────
@dataclass
class ExtractionResult:
    paper_id: int
    status: str  # "ok" / "no_chunks" / "llm_error" / "parse_error" / "db_error"
    samples_count: int = 0
    experiments_count: int = 0
    microstructure_count: int = 0
    dropped_fields: int = 0  # 校验未通过被丢弃的字段总数
    error: str = ""
    elapsed_s: float = 0.0


# ── 1) 从 ChromaDB 取 chunks 并拼接 ─────────────────────────────────
def _fetch_paper_chunks(paper_id: int) -> tuple[str, list[str]]:
    """返回拼好的上下文文本 + 全部原始 chunks（用于 evidence 校验）。"""
    col = get_collection()
    res = col.get(where={"paper_id": paper_id}, include=["documents", "metadatas"])
    docs = res.get("documents") or []
    metas = res.get("metadatas") or []
    if not docs:
        return "", []

    # 按 chunk_index 排序
    items = sorted(zip(docs, metas), key=lambda x: x[1].get("chunk_index", 0))

    pieces = []
    raw_chunks = []
    for doc, meta in items:
        section = (meta.get("section") or "").strip().lower()
        if section in EXCLUDED_SECTIONS:
            continue
        section_label = meta.get("section") or "Body"
        pieces.append(f"\n### Section: {section_label}\n{doc}\n")
        raw_chunks.append(doc)

    full = "".join(pieces).strip()
    if len(full) > MAX_CONTEXT_CHARS:
        full = full[:MAX_CONTEXT_CHARS] + "\n... [truncated]"
    return full, raw_chunks


# ── 2) 调 LLM 抽取 ───────────────────────────────────────────────────
def _strip_json_fence(s: str) -> str:
    s = re.sub(r"^```(?:json)?\s*", "", s.strip())
    s = re.sub(r"\s*```$", "", s)
    return s


def _llm_extract(paper_id: int, paper_title: str, context: str) -> dict:
    """调一次 LLM。失败抛异常，调用方处理。"""
    user_msg = (
        f"Paper title: {paper_title}\nPaper id: {paper_id}\n\n"
        f"Source text:\n{context}\n\n"
        "Now output the JSON object with `samples`, `experiments`, `microstructure`."
    )
    messages = [
        {"role": "system", "content": _SYS_PROMPT},
        {"role": "user", "content": _FEW_SHOT_USER},
        {"role": "assistant", "content": _FEW_SHOT_ASSISTANT},
        {"role": "user", "content": user_msg},
    ]
    raw = chat_json(messages)
    raw = _strip_json_fence(raw)
    return json.loads(raw)


# ── 3) 校验 ─────────────────────────────────────────────────────────
_NORM_RE = re.compile(r"\s+")


def _normalize_for_match(s: str) -> str:
    """归一化空白/全角字符，做 evidence_quote 子串匹配用。"""
    if not s:
        return ""
    s = s.replace("％", "%").replace("℃", "°C").replace("，", ",").replace("。", ".")
    s = _NORM_RE.sub(" ", s).strip().lower()
    return s


def _validate_numeric(value: Any, field_name: str) -> tuple[Any, bool]:
    """返回 (cleaned_value, ok)。值不在 sanity 范围或解析失败 → (None, False)。"""
    if value is None:
        return None, True
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None, False
    lo, hi = SANITY_RANGES.get(field_name, (None, None))
    if lo is not None and (v < lo or v > hi):
        return None, False
    return v, True


def _validate_evidence(quote: str | None, raw_chunks: list[str]) -> bool:
    """evidence_quote 必须能在某 chunk 中字符串匹配（归一化后）。"""
    if not quote:
        return False
    nq = _normalize_for_match(quote)
    # 太短的 quote 不算证据（< 15 个字符）
    if len(nq) < 15:
        return False
    for c in raw_chunks:
        if nq in _normalize_for_match(c):
            return True
    return False


# ── 逐字段接地校验(2026-06 重写,替代整行一刀切) ──────────────────────
# 判别实验结论: LLM 抽的数字 96% 逐字存在于原文,但旧的 evidence_quote
# 精确子串校验只放过 12%(表格切 chunk 后空白/顺序乱掉)。改成三道闸:
#   1) sanity 物理范围 (_validate_numeric)
#   2) 数值逐字出现在归一化全文 (_number_in_text)
#   3) 该记录 evidence_quote 的 token 在全文重合 >= QUOTE_OVERLAP_MIN
# 任一不过只丢该字段,不连坐整条记录。

def _number_variants(value: Any) -> set[str]:
    """生成数值的多种字符串形式(整数/一位/两位小数/去尾零),用于逐字定位。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        s = str(value).strip().lower()
        return {s} if s else set()
    out = {str(value).strip().lower(), f"{f:.1f}", f"{f:.2f}"}
    if f == int(f):
        out.add(str(int(f)))
    out.add((f"{f:.3f}").rstrip("0").rstrip("."))
    return {s for s in out if s}


def _number_in_text(value: Any, norm_text: str) -> bool:
    """数值是否逐字出现在归一化全文中。"""
    return any(s in norm_text for s in _number_variants(value))


def _quote_overlap(quote: str | None, norm_text: str) -> float:
    """evidence_quote 的有效 token(>=2 字)在全文中的出现比例 [0,1]。
    引用太短(<3 个有效 token)直接判 0,避免空洞引用蒙混。"""
    if not quote:
        return 0.0
    qt = {t for t in _normalize_for_match(quote).split() if len(t) >= 2}
    if len(qt) < 3:
        return 0.0
    return sum(1 for t in qt if t in norm_text) / len(qt)


# 数值字段映射：表名 → [(json_key, db_column, sanity_key)]
_NUMERIC_FIELDS = {
    "samples": [
        ("ash_pct", "ash_pct", "ash_pct"),
        ("volatile_pct", "volatile_pct", "volatile_pct"),
        ("fixed_carbon_pct", "fixed_carbon_pct", "fixed_carbon_pct"),
        ("sulfur_pct", "sulfur_pct", "sulfur_pct"),
        ("vitrinite_reflectance", "vitrinite_reflectance", "vitrinite_reflectance"),
        ("fluidity_log_ddpm", "fluidity_log_ddpm", "fluidity_log_ddpm"),
    ],
    "experiments": [
        ("coking_temp_c", "coking_temp_c", "coking_temp_c"),
        ("heating_rate_c_per_min", "heating_rate_c_per_min", "heating_rate_c_per_min"),
        ("coking_time_min", "coking_time_min", "coking_time_min"),
        ("cri", "cri", "cri"),
        ("csr", "csr", "csr"),
        ("cbi", "cbi", "cbi"),
        ("coke_yield_pct", "coke_yield_pct", "coke_yield_pct"),
    ],
    "microstructure": [
        ("La_nm", "La_nm", "La_nm"),
        ("Lc_nm", "Lc_nm", "Lc_nm"),
        ("d002_nm", "d002_nm", "d002_nm"),
        ("xrd_peak_2theta", "xrd_peak_2theta", "xrd_peak_2theta"),
        ("isotropic_pct", "isotropic_pct", "isotropic_pct"),
        ("anisotropic_pct", "anisotropic_pct", "anisotropic_pct"),
        ("mosaic_pct", "mosaic_pct", "mosaic_pct"),
        ("porosity_pct", "porosity_pct", "porosity_pct"),
        ("mean_pore_size_um", "mean_pore_size_um", "mean_pore_size_um"),
    ],
}


def _clean_record(rec: dict, kind: str, norm_text: str) -> tuple[dict, int]:
    """逐字段接地校验。不合格的字段置 None(只丢该字段,不连坐整行)。
    norm_text: 该论文全部 chunk 拼接并归一化后的文本(调用方算好传入,避免重复归一化)。
    返回 (cleaned_rec, dropped_count)。"""
    dropped = 0
    quote = rec.get("evidence_quote") or ""
    # 引用可信度: 整条记录共用一个 quote,只算一次
    quote_ok = _quote_overlap(quote, norm_text) >= QUOTE_OVERLAP_MIN

    for json_key, _db_col, sanity_key in _NUMERIC_FIELDS.get(kind, []):
        v = rec.get(json_key)
        cleaned, _ok_range = _validate_numeric(v, sanity_key)  # 1) sanity 范围
        # 2) 数值必须逐字在全文 且 3) 该记录引用要可信,否则丢这个字段
        if cleaned is not None and not (quote_ok and _number_in_text(cleaned, norm_text)):
            cleaned = None
        if v is not None and cleaned is None:
            dropped += 1
        rec[json_key] = cleaned
    return rec, dropped


# ── 4) 写库 ─────────────────────────────────────────────────────────
def _delete_old_records(conn: sqlite3.Connection, paper_id: int) -> None:
    for tbl in ("coal_samples", "coke_experiments", "carbon_microstructure"):
        conn.execute(f"DELETE FROM {tbl} WHERE paper_id = ?", (paper_id,))


def _insert_samples(conn, paper_id: int, samples: list[dict]) -> int:
    n = 0
    for r in samples:
        conn.execute(
            """INSERT INTO coal_samples
               (paper_id, sample_label, coal_type, origin,
                ash_pct, volatile_pct, fixed_carbon_pct, sulfur_pct,
                vitrinite_reflectance, fluidity_log_ddpm,
                evidence_section, evidence_quote)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (paper_id, r.get("sample_label"), r.get("coal_type"), r.get("origin"),
             r.get("ash_pct"), r.get("volatile_pct"), r.get("fixed_carbon_pct"), r.get("sulfur_pct"),
             r.get("vitrinite_reflectance"), r.get("fluidity_log_ddpm"),
             r.get("evidence_section"), (r.get("evidence_quote") or "")[:300]),
        )
        n += 1
    return n


def _insert_experiments(conn, paper_id: int, exps: list[dict]) -> int:
    n = 0
    for r in exps:
        blend = r.get("blend_recipe")
        blend_json = json.dumps(blend, ensure_ascii=False) if blend else None
        gas = r.get("gas_composition")
        gas_json = json.dumps(gas, ensure_ascii=False) if gas else None
        conn.execute(
            """INSERT INTO coke_experiments
               (paper_id, sample_label, blend_recipe_json,
                coking_temp_c, heating_rate_c_per_min, coking_time_min,
                cri, csr, cbi, coke_yield_pct, gas_composition_json,
                evidence_section, evidence_quote)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (paper_id, r.get("sample_label"), blend_json,
             r.get("coking_temp_c"), r.get("heating_rate_c_per_min"), r.get("coking_time_min"),
             r.get("cri"), r.get("csr"), r.get("cbi"), r.get("coke_yield_pct"), gas_json,
             r.get("evidence_section"), (r.get("evidence_quote") or "")[:300]),
        )
        n += 1
    return n


def _insert_microstructure(conn, paper_id: int, micros: list[dict]) -> int:
    n = 0
    for r in micros:
        conn.execute(
            """INSERT INTO carbon_microstructure
               (paper_id, sample_label,
                La_nm, Lc_nm, d002_nm, xrd_peak_2theta,
                isotropic_pct, anisotropic_pct, mosaic_pct,
                porosity_pct, mean_pore_size_um,
                evidence_section, evidence_quote)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (paper_id, r.get("sample_label"),
             r.get("La_nm"), r.get("Lc_nm"), r.get("d002_nm"), r.get("xrd_peak_2theta"),
             r.get("isotropic_pct"), r.get("anisotropic_pct"), r.get("mosaic_pct"),
             r.get("porosity_pct"), r.get("mean_pore_size_um"),
             r.get("evidence_section"), (r.get("evidence_quote") or "")[:300]),
        )
        n += 1
    return n


# ── 原始输出落盘(供事后重校验,不必重跑 LLM) ─────────────────────────
def _persist_raw(paper_id: int, data: dict) -> None:
    """把 LLM 原始抽取 JSON 落盘。失败不影响主流程。"""
    try:
        RAW_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with (RAW_OUTPUT_DIR / f"{paper_id}.json").open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


# ── 5) 主入口 ───────────────────────────────────────────────────────
def extract_one(paper_id: int, *, replace_existing: bool = True) -> ExtractionResult:
    """抽取单篇文献。replace_existing=True 时先删旧记录再写新的。"""
    t0 = time.time()
    init_quant_tables()

    conn = get_conn()
    try:
        # 查 title
        row = conn.execute("SELECT title FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if not row:
            return ExtractionResult(paper_id=paper_id, status="not_found",
                                    error=f"paper {paper_id} 不存在", elapsed_s=time.time() - t0)
        title = row["title"] or f"paper {paper_id}"

        # 取 chunks
        context, raw_chunks = _fetch_paper_chunks(paper_id)
        if not context or not raw_chunks:
            return ExtractionResult(paper_id=paper_id, status="no_chunks",
                                    error="该文献在 ChromaDB 中无 chunks", elapsed_s=time.time() - t0)

        # 调 LLM
        try:
            data = _llm_extract(paper_id, title, context)
        except json.JSONDecodeError as e:
            return ExtractionResult(paper_id=paper_id, status="parse_error",
                                    error=f"LLM 返回 JSON 解析失败: {e}", elapsed_s=time.time() - t0)
        except Exception as e:
            return ExtractionResult(paper_id=paper_id, status="llm_error",
                                    error=f"{type(e).__name__}: {e}", elapsed_s=time.time() - t0)

        # 原始输出落盘(校验前),便于以后换阈值重校验
        _persist_raw(paper_id, data)

        # 全文归一化一次,接地校验复用(数值逐字匹配 + 引用重合度)
        norm_text = _normalize_for_match(" ".join(raw_chunks))

        # 校验三类记录
        samples = data.get("samples") or []
        experiments = data.get("experiments") or []
        microstructure = data.get("microstructure") or []
        dropped = 0
        cleaned_samples = []
        for r in samples:
            if not isinstance(r, dict):
                continue
            cr, d = _clean_record(r, "samples", norm_text)
            dropped += d
            cleaned_samples.append(cr)
        cleaned_exps = []
        for r in experiments:
            if not isinstance(r, dict):
                continue
            cr, d = _clean_record(r, "experiments", norm_text)
            dropped += d
            cleaned_exps.append(cr)
        cleaned_micros = []
        for r in microstructure:
            if not isinstance(r, dict):
                continue
            cr, d = _clean_record(r, "microstructure", norm_text)
            dropped += d
            cleaned_micros.append(cr)

        # 写库
        try:
            if replace_existing:
                _delete_old_records(conn, paper_id)
            n_s = _insert_samples(conn, paper_id, cleaned_samples)
            n_e = _insert_experiments(conn, paper_id, cleaned_exps)
            n_m = _insert_microstructure(conn, paper_id, cleaned_micros)
            conn.commit()
        except Exception as e:
            conn.rollback()
            return ExtractionResult(paper_id=paper_id, status="db_error",
                                    error=f"{type(e).__name__}: {e}", elapsed_s=time.time() - t0)

        return ExtractionResult(
            paper_id=paper_id, status="ok",
            samples_count=n_s, experiments_count=n_e, microstructure_count=n_m,
            dropped_fields=dropped, elapsed_s=time.time() - t0,
        )
    finally:
        conn.close()


def _papers_already_extracted() -> set[int]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT DISTINCT paper_id FROM coal_samples "
            "UNION SELECT DISTINCT paper_id FROM coke_experiments "
            "UNION SELECT DISTINCT paper_id FROM carbon_microstructure"
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def _list_all_paper_ids() -> list[int]:
    conn = get_conn()
    try:
        return [r[0] for r in conn.execute("SELECT id FROM papers ORDER BY id").fetchall()]
    finally:
        conn.close()


def _append_log(result: ExtractionResult) -> None:
    EXTRACTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with EXTRACTION_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "paper_id": result.paper_id,
            "status": result.status,
            "samples": result.samples_count,
            "experiments": result.experiments_count,
            "microstructure": result.microstructure_count,
            "dropped": result.dropped_fields,
            "error": result.error,
            "elapsed_s": round(result.elapsed_s, 2),
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False) + "\n")


def extract_all(*, skip_existing: bool = True, limit: int | None = None) -> dict:
    init_quant_tables()
    all_ids = _list_all_paper_ids()
    if skip_existing:
        done = _papers_already_extracted()
        all_ids = [i for i in all_ids if i not in done]
    if limit:
        all_ids = all_ids[:limit]

    stats = {"ok": 0, "no_chunks": 0, "llm_error": 0, "parse_error": 0, "db_error": 0, "not_found": 0}
    total = len(all_ids)
    print(f"[extract] 待抽取 {total} 篇")
    for i, pid in enumerate(all_ids, 1):
        try:
            r = extract_one(pid, replace_existing=True)
        except Exception as e:
            r = ExtractionResult(paper_id=pid, status="llm_error",
                                 error=f"unhandled {type(e).__name__}: {e}")
            traceback.print_exc()
        _append_log(r)
        stats[r.status] = stats.get(r.status, 0) + 1
        print(f"[{i}/{total}] paper_id={pid} {r.status} "
              f"samples={r.samples_count} experiments={r.experiments_count} "
              f"micros={r.microstructure_count} dropped={r.dropped_fields} "
              f"{r.elapsed_s:.1f}s "
              f"{('err=' + r.error[:80]) if r.error else ''}")
    return stats


def main():
    ap = argparse.ArgumentParser(description="焦化文献定量数据抽取")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--paper-id", type=int, help="单篇文献抽取")
    g.add_argument("--all", action="store_true", help="全量抽取")
    ap.add_argument("--limit", type=int, default=None, help="限制抽取篇数（搭配 --all）")
    ap.add_argument("--skip-existing", action="store_true",
                    help="跳过已抽过的论文（在三表中任一出现过就算）")
    args = ap.parse_args()

    if args.paper_id:
        r = extract_one(args.paper_id)
        _append_log(r)
        print(json.dumps({
            "paper_id": r.paper_id, "status": r.status,
            "samples": r.samples_count, "experiments": r.experiments_count,
            "microstructure": r.microstructure_count, "dropped": r.dropped_fields,
            "elapsed_s": round(r.elapsed_s, 2),
            "error": r.error,
        }, ensure_ascii=False, indent=2))
        sys.exit(0 if r.status == "ok" else 1)

    if args.all:
        stats = extract_all(skip_existing=args.skip_existing, limit=args.limit)
        print(f"\n[extract] 完成: {stats}")


if __name__ == "__main__":
    main()
