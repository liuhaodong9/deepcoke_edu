"""结构化字典 NL→SQL 查询。

输入用户问题，让 LLM 翻成 SQLite SELECT，沙箱执行，结果格式化为 Markdown 表格。

调用方式（顶层 API）：
    from deepcoke.literature_qa.quant_query import lookup_structured
    md = lookup_structured("挥发分 28-32% 的炼焦煤 CSR 一般多少？")
    # 命中返回 markdown，未命中或失败返回 ""，调用方静默回退

安全设计：
- SQL 必须是单条 SELECT，禁止 PRAGMA / ATTACH / 写操作
- FROM/JOIN 只允许 quant_schema.QUERYABLE_TABLES 白名单
- 强制 LIMIT 50 兜底
- 用只读 sqlite3 连接执行
"""
from __future__ import annotations

import html
import json
import logging
import re
import sqlite3
from typing import Any

from ..llm_client import chat_json
from .quant_schema import PAPERS_DB_PATH, QUERYABLE_TABLES

logger = logging.getLogger(__name__)

MAX_RESULT_ROWS = 50

# 危险关键字 — 任何一个出现就拒绝执行
_FORBIDDEN_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "pragma", "attach", "detach", "vacuum", "replace",
    "into", "load_extension", ";",   # 多语句也禁
)

# 给 LLM 看的 schema 描述（中文注释 + 字段含义）
_SCHEMA_PROMPT = """SQLite 数据库 papers.db 含以下四张可查表（全部小写、加 backtick 避免冲突）：

▼ 表 papers — 文献元数据（每篇一行）
  id INTEGER PK, title TEXT, authors TEXT(JSON list), year INTEGER, category TEXT, abstract TEXT, keywords TEXT(JSON list)

▼ 表 coal_samples — 煤样工业分析（一篇可多行，paper_id JOIN papers.id）
  id, paper_id, sample_label TEXT, coal_type TEXT (气煤/肥煤/焦煤/瘦煤/无烟煤等),
  origin TEXT (产地), ash_pct REAL (灰分 %), volatile_pct REAL (挥发分 Vdaf %),
  fixed_carbon_pct REAL, sulfur_pct REAL (全硫 %),
  vitrinite_reflectance REAL (镜质组反射率 Ro,max %),
  fluidity_log_ddpm REAL (Gieseler 最大流动度 log(ddpm)),
  evidence_section TEXT, evidence_quote TEXT

▼ 表 coke_experiments — 焦化实验（一篇可多组，paper_id JOIN papers.id）
  id, paper_id, sample_label TEXT, blend_recipe_json TEXT (JSON, 配比),
  coking_temp_c REAL (℃), heating_rate_c_per_min REAL, coking_time_min REAL,
  cri REAL (焦炭反应性 % 0-100), csr REAL (反应后强度 % 0-100), cbi REAL,
  coke_yield_pct REAL, gas_composition_json TEXT (JSON, vol%),
  evidence_section, evidence_quote

▼ 表 carbon_microstructure — 碳微晶/显微结构（paper_id JOIN papers.id）
  id, paper_id, sample_label TEXT,
  La_nm REAL (XRD 微晶 La 尺寸 nm), Lc_nm REAL (XRD 微晶 Lc nm),
  d002_nm REAL (002 面间距 nm), xrd_peak_2theta REAL,
  isotropic_pct REAL, anisotropic_pct REAL, mosaic_pct REAL,
  porosity_pct REAL, mean_pore_size_um REAL,
  evidence_section, evidence_quote

规则：
- 任何数值字段都可能是 NULL；用 IS NOT NULL 过滤掉缺失。
- 用户问"X 煤"通常是 coal_type LIKE '%X%' 或 origin LIKE '%X%' 或 sample_label LIKE '%X%'。
- 几乎所有查询都要 JOIN papers 取 title/year 给引用：JOIN papers p ON x.paper_id = p.id。
- 想看具体数值就 SELECT 该字段；想统计就 AVG/MIN/MAX/COUNT。
- 默认 LIMIT 30。
"""

_SYS_TRANSLATE = f"""You translate natural-language questions about coal coking literature into a SINGLE SQLite SELECT statement.

{_SCHEMA_PROMPT}

Output rules — STRICT:
- Output ONLY a JSON object: {{"sql": "...", "intent": "..."}} where `intent` is a one-sentence English explanation.
- The `sql` MUST be a single SELECT statement (no semicolon, no PRAGMA, no comments).
- If the question CANNOT be answered from these tables (e.g. asks for mechanism, opinion, paper-text content), output {{"sql": null, "intent": "not a structured query"}}.
- Prefer LEFT JOIN papers when ambiguous; always include paper title and year in the SELECT for citation.
"""

# Few-shot 示例：每个一对 user/assistant
_FEW_SHOTS = [
    {
        "q": "挥发分在 28%~32% 之间的炼焦煤，CSR 一般多少？",
        "a": {
            "sql": (
                "SELECT p.title, p.year, cs.coal_type, cs.volatile_pct, ce.csr "
                "FROM coal_samples cs "
                "JOIN coke_experiments ce ON ce.paper_id = cs.paper_id AND ce.sample_label = cs.sample_label "
                "JOIN papers p ON p.id = cs.paper_id "
                "WHERE cs.volatile_pct BETWEEN 28 AND 32 AND ce.csr IS NOT NULL "
                "ORDER BY ce.csr DESC LIMIT 30"
            ),
            "intent": "join coal samples with their coking experiments to get CSR for volatile% in 28-32",
        },
    },
    {
        "q": "镜质组反射率最高的几个煤样",
        "a": {
            "sql": (
                "SELECT p.title, p.year, cs.sample_label, cs.coal_type, cs.vitrinite_reflectance "
                "FROM coal_samples cs JOIN papers p ON p.id = cs.paper_id "
                "WHERE cs.vitrinite_reflectance IS NOT NULL "
                "ORDER BY cs.vitrinite_reflectance DESC LIMIT 20"
            ),
            "intent": "rank coal samples by vitrinite reflectance descending",
        },
    },
    {
        "q": "焦化温度对 La 微晶尺寸的影响",
        "a": {
            "sql": (
                "SELECT p.title, ce.coking_temp_c, cm.La_nm, cm.Lc_nm "
                "FROM coke_experiments ce "
                "JOIN carbon_microstructure cm ON cm.paper_id = ce.paper_id AND cm.sample_label = ce.sample_label "
                "JOIN papers p ON p.id = ce.paper_id "
                "WHERE ce.coking_temp_c IS NOT NULL AND cm.La_nm IS NOT NULL "
                "ORDER BY ce.coking_temp_c LIMIT 30"
            ),
            "intent": "pair coking temperature with crystallite La for trend analysis",
        },
    },
    {
        "q": "焦炭气孔的形成机理",
        "a": {"sql": None, "intent": "mechanism / explanation question — not a structured lookup"},
    },
]


# ── 1) NL → SQL ─────────────────────────────────────────────────────
def translate_to_sql(question: str) -> tuple[str | None, str]:
    """返回 (sql 或 None, intent 描述)。失败返回 (None, error 信息)。"""
    messages = [{"role": "system", "content": _SYS_TRANSLATE}]
    for shot in _FEW_SHOTS:
        messages.append({"role": "user", "content": shot["q"]})
        messages.append({"role": "assistant", "content": json.dumps(shot["a"], ensure_ascii=False)})
    messages.append({"role": "user", "content": question})

    try:
        raw = chat_json(messages)
    except Exception as e:
        return None, f"llm_error: {type(e).__name__}: {e}"

    # 去 markdown fence
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # 兜底：从原文里抠 JSON 对象
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None, "parse_error: not JSON"
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            return None, f"parse_error: {e}"

    sql = data.get("sql")
    intent = data.get("intent") or ""
    if sql in (None, "", "null"):
        return None, intent or "no structured query"
    return str(sql).strip(), intent


# ── 1b) 代码强制注入溯源列 ──────────────────────────────────────────
# 8B 模型不肯按 prompt 自己 SELECT paper_id/evidence_quote(实测无视规则+few-shot),
# 改由代码在 SELECT 后插入主表的这两列(别名 _trace_*,避免撞用户列)。
# 前端 onChatClick 用 _trace_quote 在 PDF 文本高亮、_trace_paper_id 取 PDF。
_QUANT_TABLE_RE = re.compile(
    r"\b(?:from|join)\s+(coal_samples|coke_experiments|carbon_microstructure)\b"
    r"(?:\s+(?:as\s+)?"
    r"(?!(?:on|where|join|inner|left|right|cross|group|order|limit|having|union|natural)\b)"
    r"([a-z_]\w*))?",
    re.I,
)
_AGG_RE = re.compile(r"\b(?:count|sum|avg|min|max|group_concat|total)\s*\(", re.I)
_SELECT_HEAD_RE = re.compile(r"(?is)^(\s*select\s+(?:distinct\s+)?)(.*)$")


def inject_provenance(sql: str) -> str:
    """在 SELECT 后强制注入 主表.paper_id / 主表.evidence_quote(别名 _trace_*)。
    - 聚合/分组查询无单行溯源意义 → 原样返回
    - 找不到定量表(纯 papers 查询)→ 原样返回
    取 FROM/JOIN 命中的第一个定量表为主表(其别名,无别名则表名)。"""
    s = sql.strip()
    low = s.lower()
    # 聚合/分组/去重查询无清晰的单行溯源(注入会改变 DISTINCT 语义、膨胀行数)→ 跳过
    if "group by" in low or _AGG_RE.search(s) or re.match(r"(?is)^\s*select\s+distinct\b", s):
        return sql
    m = _QUANT_TABLE_RE.search(s)
    if not m:
        return sql
    alias = m.group(2) or m.group(1)
    mh = _SELECT_HEAD_RE.match(s)
    if not mh:
        return sql
    head, rest = mh.group(1), mh.group(2)
    inject = f"{alias}.paper_id AS _trace_paper_id, {alias}.evidence_quote AS _trace_quote, "
    return head + inject + rest


# ── 2) 沙箱校验 ─────────────────────────────────────────────────────
_ALLOWED_TABLES_RE = re.compile(
    r"\b(from|join)\s+`?(\w+)`?", re.I
)


def is_safe_sql(sql: str) -> tuple[bool, str]:
    """返回 (ok, reason)。所有违规一律拒。"""
    if not sql or not isinstance(sql, str):
        return False, "empty sql"
    s = sql.strip().rstrip(";").strip()
    s_lower = s.lower()

    # 必须以 SELECT 或 WITH（CTE）开头
    if not (s_lower.startswith("select") or s_lower.startswith("with")):
        return False, "must start with SELECT or WITH"

    # 禁词扫描（要忽略字符串字面量里的内容，但简单起见这里直接扫单词边界）
    for kw in _FORBIDDEN_KEYWORDS:
        # ; 直接禁
        if kw == ";":
            if ";" in s:
                return False, "semicolon not allowed"
            continue
        if re.search(rf"\b{re.escape(kw)}\b", s_lower):
            return False, f"forbidden keyword: {kw}"

    # 检查所有 FROM/JOIN 后的表名都在白名单
    tables = {m.group(2).lower() for m in _ALLOWED_TABLES_RE.finditer(s)}
    bad = tables - {t.lower() for t in QUERYABLE_TABLES}
    if bad:
        return False, f"table(s) not in whitelist: {sorted(bad)}"

    return True, "ok"


def _ensure_limit(sql: str) -> str:
    """没显式 LIMIT 就加一个，避免大查询。"""
    if re.search(r"\blimit\b\s+\d+", sql, re.I):
        return sql
    return f"{sql.rstrip().rstrip(';')} LIMIT {MAX_RESULT_ROWS}"


# ── 3) 执行 ─────────────────────────────────────────────────────────
def execute_safely(sql: str) -> tuple[list[dict] | None, str]:
    """跑 SQL。失败返回 (None, error)。成功返回 (rows, '')。只读模式。"""
    ok, reason = is_safe_sql(sql)
    if not ok:
        return None, f"unsafe: {reason}"

    sql_final = _ensure_limit(sql)

    # 只读 URI 连接
    uri = f"file:{PAPERS_DB_PATH.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        return None, f"db_open: {e}"

    try:
        cursor = conn.execute(sql_final)
        rows = [dict(r) for r in cursor.fetchall()]
    except sqlite3.Error as e:
        return None, f"db_exec: {e}"
    finally:
        conn.close()

    return rows, ""


# ── 4) 结果格式化 ───────────────────────────────────────────────────
def _fmt_cell(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        # 数值保留两位小数（除非很小/很大）
        if abs(v) >= 100 or v == int(v):
            return f"{v:.1f}"
        return f"{v:.2f}"
    s = str(v)
    if len(s) > 60:
        return s[:57] + "…"
    return s


def _html_escape(v: Any) -> str:
    return html.escape("" if v is None else str(v), quote=True)


# 溯源驱动列(由 inject_provenance 注入)：不作为可见数据列展示，而是生成"📄 原文"高亮跳转链接
_PROVENANCE_KEYS = ("_trace_paper_id", "_trace_quote")


def format_as_markdown(rows: list[dict], question: str, sql: str) -> str:
    """转 HTML 表 + 每行"📄 原文"溯源链接。空结果返回空字符串。

    paper_id / evidence_quote 两列不显示为数据，而是写入链接的 data-* 属性，
    前端 onChatClick 捕获后用 evidence_quote 在 PDF 里文本高亮（复用 [N] 引用机制）。
    SQL 没带这两列时优雅降级为纯数据表。
    """
    if not rows:
        return ""
    display_cols = [c for c in rows[0].keys() if c not in _PROVENANCE_KEYS]
    has_link = "_trace_paper_id" in rows[0] and "_trace_quote" in rows[0]

    ths = "".join(f"<th>{_html_escape(c)}</th>" for c in display_cols)
    if has_link:
        ths += "<th>原文</th>"

    trs = []
    for r in rows:
        tds = "".join(f"<td>{_html_escape(_fmt_cell(r.get(c)))}</td>" for c in display_cols)
        if has_link:
            pid = r.get("_trace_paper_id")
            quote = (r.get("_trace_quote") or "").strip()
            if pid and quote:
                cell = (
                    f'<a class="quant-cite" href="#" '
                    f'data-paper-id="{_html_escape(pid)}" '
                    f'data-quote="{_html_escape(quote)}" '
                    f'data-title="{_html_escape(r.get("title"))}">📄 原文</a>'
                )
            else:
                cell = "—"
            tds += f"<td>{cell}</td>"
        trs.append(f"<tr>{tds}</tr>")

    # 表格用 HTML(前端 renderMarkdown 对 <table class="quant-table"> 整块占位保护，
    # 标签内的 <a data-*> 才不会被转义)；标题/注脚用 markdown，无需保护。
    table = (
        f'<table class="quant-table"><thead><tr>{ths}</tr></thead>'
        f'<tbody>{"".join(trs)}</tbody></table>'
    )
    truncated = (
        f"\n\n_（共 {len(rows)} 行，已截断到 {MAX_RESULT_ROWS} 行上限）_"
        if len(rows) >= MAX_RESULT_ROWS else ""
    )
    return (
        f"**结构化字典命中** — {len(rows)} 条记录\n\n"
        f"{table}"
        f"{truncated}"
    )


# ── 5) 顶层 API ─────────────────────────────────────────────────────
def lookup_structured(question: str) -> dict:
    """对外接口。返回 dict:
        {
          "hit": bool,           # 是否命中
          "markdown": str,       # 命中时的 markdown 表（未命中为 ""）
          "sql": str | None,     # 生成的 SQL（debug）
          "intent": str,         # LLM 给的意图说明（debug）
          "rows": list[dict],    # 原始行（命中时）
          "error": str,          # 失败时的错误信息（命中或正常未命中时为 ""）
        }
    任何环节失败都返回 hit=False，调用方静默回退到 RAG。"""
    out = {"hit": False, "markdown": "", "sql": None, "intent": "", "rows": [], "error": ""}

    sql, intent = translate_to_sql(question)
    out["intent"] = intent
    if not sql:
        # 这是正常的"不是结构化问题"，不算错误
        return out
    # 代码强制注入溯源列(8B 不肯自己选),供 UI 跳 PDF 高亮
    sql = inject_provenance(sql)
    out["sql"] = sql

    rows, err = execute_safely(sql)
    if err:
        out["error"] = err
        logger.warning(f"[quant_query] sql failed: {err}  sql={sql[:200]}")
        return out

    if not rows:
        # 安全 SQL 但 0 行，也算未命中（表可能还没抽取数据）
        return out

    out["rows"] = rows
    out["markdown"] = format_as_markdown(rows, question, sql)
    out["hit"] = True
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="NL→SQL 字典查询调试")
    ap.add_argument("question", help="自然语言问题")
    args = ap.parse_args()

    result = lookup_structured(args.question)
    print(f"intent: {result['intent']}")
    print(f"sql: {result['sql']}")
    print(f"error: {result['error']}")
    print(f"hit: {result['hit']}  rows: {len(result['rows'])}")
    if result["markdown"]:
        print("\n" + result["markdown"])
