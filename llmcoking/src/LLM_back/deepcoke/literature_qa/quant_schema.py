"""焦化文献结构化字典 schema。

跟 ingestion/run_ingestion.py 共用 papers.db，新增三张表：
- coal_samples         每个煤样工业分析一行（一篇可多行）
- coke_experiments     每组焦化实验一行（一篇可多行）
- carbon_microstructure 每个样品的碳微晶/显微结构一行

设计原则:
- 数值字段一律 REAL NULL（没抽到就 NULL，不要 0 / "N/A"）
- 每条记录都带 evidence_section + evidence_quote，事后可审计
- 单位归一（注释里写死）；查询时不需要再考虑单位换算
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from deepcoke import config as _cfg


PAPERS_DB_PATH = _cfg.DATA_DIR / "papers.db"


def get_conn(db_path: Path | str | None = None) -> sqlite3.Connection:
    """打开 papers.db。默认走 config.DATA_DIR/papers.db。"""
    path = Path(db_path) if db_path else PAPERS_DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    # 开外键约束（SQLite 默认不开）
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ── 表 1: 煤样工业分析 ──────────────────────────────────────────────
_DDL_COAL_SAMPLES = """
CREATE TABLE IF NOT EXISTS coal_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL,
    sample_label TEXT,                      -- 原文标签，如 "Coal A"、"赤峰 1#"
    coal_type TEXT,                         -- 气煤/肥煤/焦煤/瘦煤/无烟煤
    origin TEXT,                            -- 产地
    ash_pct REAL,                           -- 灰分 Ad %
    volatile_pct REAL,                      -- 挥发分 Vdaf %
    fixed_carbon_pct REAL,                  -- 固定碳 FCd %
    sulfur_pct REAL,                        -- 全硫 St,d %
    vitrinite_reflectance REAL,             -- 镜质组反射率 Ro,max %
    fluidity_log_ddpm REAL,                 -- Gieseler 最大流动度 log(ddpm)
    evidence_section TEXT,                  -- 抽取来源段名
    evidence_quote TEXT,                    -- 抽取来源原句（<= 300 字）
    extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
)
"""

_IDX_COAL_SAMPLES = [
    "CREATE INDEX IF NOT EXISTS idx_coal_samples_paper ON coal_samples(paper_id)",
    "CREATE INDEX IF NOT EXISTS idx_coal_samples_type ON coal_samples(coal_type)",
    "CREATE INDEX IF NOT EXISTS idx_coal_samples_volatile ON coal_samples(volatile_pct)",
]


# ── 表 2: 焦化实验 ──────────────────────────────────────────────────
_DDL_COKE_EXPERIMENTS = """
CREATE TABLE IF NOT EXISTS coke_experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL,
    sample_label TEXT,                      -- 关联到 coal_samples.sample_label（同篇内）
    blend_recipe_json TEXT,                 -- [{sample_label, pct}, ...] JSON
    coking_temp_c REAL,                     -- 焦化温度 ℃
    heating_rate_c_per_min REAL,            -- 升温速率 ℃/min
    coking_time_min REAL,                   -- 结焦时间 min
    cri REAL,                               -- 焦炭反应性 % (0~100)
    csr REAL,                               -- 反应后强度 % (0~100)
    cbi REAL,                               -- Coke Bond Index
    coke_yield_pct REAL,                    -- 焦炭/半焦产率 %
    gas_composition_json TEXT,              -- {H2, CO, CH4, CO2, ...} vol% JSON
    evidence_section TEXT,
    evidence_quote TEXT,
    extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
)
"""

_IDX_COKE_EXPERIMENTS = [
    "CREATE INDEX IF NOT EXISTS idx_coke_exp_paper ON coke_experiments(paper_id)",
    "CREATE INDEX IF NOT EXISTS idx_coke_exp_csr ON coke_experiments(csr)",
    "CREATE INDEX IF NOT EXISTS idx_coke_exp_cri ON coke_experiments(cri)",
    "CREATE INDEX IF NOT EXISTS idx_coke_exp_temp ON coke_experiments(coking_temp_c)",
]


# ── 表 3: 碳微晶 / 显微结构（对应博士课题 2 核心） ──────────────────
_DDL_CARBON_MICROSTRUCTURE = """
CREATE TABLE IF NOT EXISTS carbon_microstructure (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL,
    sample_label TEXT,                      -- 关联 coal_samples / coke_experiments 同名样品
    La_nm REAL,                             -- XRD 微晶 La 尺寸 nm
    Lc_nm REAL,                             -- XRD 微晶 Lc 尺寸 nm
    d002_nm REAL,                           -- 002 面间距 nm
    xrd_peak_2theta REAL,                   -- 002 峰位 2θ (°)
    isotropic_pct REAL,                     -- 显微组分 各向同性 %
    anisotropic_pct REAL,                   -- 显微组分 各向异性 %
    mosaic_pct REAL,                        -- 显微组分 镶嵌 %
    porosity_pct REAL,                      -- 孔隙率 %
    mean_pore_size_um REAL,                 -- 平均孔径 μm
    evidence_section TEXT,
    evidence_quote TEXT,
    extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
)
"""

_IDX_CARBON_MICROSTRUCTURE = [
    "CREATE INDEX IF NOT EXISTS idx_carbon_micro_paper ON carbon_microstructure(paper_id)",
    "CREATE INDEX IF NOT EXISTS idx_carbon_micro_La ON carbon_microstructure(La_nm)",
    "CREATE INDEX IF NOT EXISTS idx_carbon_micro_Lc ON carbon_microstructure(Lc_nm)",
]


# 白名单：NL→SQL 沙箱执行时只允许查这几张表（外加 papers JOIN）
QUERYABLE_TABLES = (
    "coal_samples",
    "coke_experiments",
    "carbon_microstructure",
    "papers",
)


def init_quant_tables(db_path: Path | str | None = None) -> None:
    """幂等创建三张抽取表 + 索引。重复调用安全。"""
    conn = get_conn(db_path)
    try:
        conn.execute(_DDL_COAL_SAMPLES)
        conn.execute(_DDL_COKE_EXPERIMENTS)
        conn.execute(_DDL_CARBON_MICROSTRUCTURE)
        for stmt in (*_IDX_COAL_SAMPLES, *_IDX_COKE_EXPERIMENTS, *_IDX_CARBON_MICROSTRUCTURE):
            conn.execute(stmt)
        conn.commit()
    finally:
        conn.close()


def get_extraction_stats(db_path: Path | str | None = None) -> dict:
    """返回三张表的行数和已覆盖的 paper 数，给抽取脚本和健康检查用。"""
    conn = get_conn(db_path)
    try:
        out = {}
        for tbl in ("coal_samples", "coke_experiments", "carbon_microstructure"):
            row_count = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            paper_count = conn.execute(f"SELECT COUNT(DISTINCT paper_id) FROM {tbl}").fetchone()[0]
            out[tbl] = {"rows": row_count, "papers": paper_count}
        out["total_papers"] = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        return out
    finally:
        conn.close()


if __name__ == "__main__":
    # 命令行入口：python -m deepcoke.literature_qa.quant_schema
    init_quant_tables()
    print("已建表：")
    for tbl, stat in get_extraction_stats().items():
        print(f"  {tbl}: {stat}")
