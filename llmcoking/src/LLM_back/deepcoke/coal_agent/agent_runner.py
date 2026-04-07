"""
配煤优化 Agent Runner — 使用 Ollama 原生 /api/chat 接口进行 tool-calling
"""

import json
import requests
import logging

from .coal_db import get_all_coals
from .quality_predictor import predictor
from .blend_optimizer import optimize_blend

logger = logging.getLogger("deepcoke.coal_agent")

OLLAMA_BASE = "http://localhost:11434"
OLLAMA_CHAT_URL = f"{OLLAMA_BASE}/api/chat"
MODEL = "qwen3:8b"

# ── 煤样数据缓存 ──────────────────────────────────────────────────
_coal_cache: dict | None = None


def _get_coal_data() -> tuple[list[dict], dict]:
    """返回 (raw_rows, props_dict)，带缓存。"""
    global _coal_cache
    if _coal_cache is not None:
        return _coal_cache
    try:
        rows = get_all_coals()
    except Exception as e:
        logger.warning(f"数据库读取失败: {e}")
        rows = []

    props = {}
    for r in rows:
        name = r["coal_name"]
        props[name] = {
            "price": float(r.get("coal_price") or 0),
            "coal_mad": float(r.get("coal_mad") or 0),
            "Ad": float(r.get("coal_ad") or 0),
            "Vdaf": float(r.get("coal_vdaf") or 0),
            "coal_std": float(r.get("coal_std") or 0),
            "G": float(r.get("G") or 0),
            "X": float(r.get("X") or 0),
            "Y": float(r.get("Y") or 0),
            "coke_CRI": float(r.get("coke_CRI") or 0),
            "coke_CSR": float(r.get("coke_CSR") or 0),
            "coke_M10": float(r.get("coke_M10") or 0),
            "coke_M25": float(r.get("coke_M25") or 0),
        }
    _coal_cache = (rows, props)
    return rows, props


# ── 工具定义 ──────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_coals",
            "description": "列出数据库中所有可用煤种及其属性（价格、挥发分、粘结指数、灰分、CRI、CSR等）",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "optimize_blend",
            "description": "根据约束条件（CRI/CSR/M10/M25范围、Vdaf/G/Ad限制）优化配煤方案，最小化成本",
            "parameters": {
                "type": "object",
                "properties": {
                    "coal_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "参与配煤的煤种名称列表",
                    },
                    "CRI_min": {"type": "number", "description": "CRI下限"},
                    "CRI_max": {"type": "number", "description": "CRI上限"},
                    "CSR_min": {"type": "number", "description": "CSR下限"},
                    "CSR_max": {"type": "number", "description": "CSR上限"},
                    "M10_min": {"type": "number", "description": "M10下限"},
                    "M10_max": {"type": "number", "description": "M10上限"},
                    "M25_min": {"type": "number", "description": "M25下限"},
                    "M25_max": {"type": "number", "description": "M25上限"},
                    "Vdaf_max": {"type": "number", "description": "挥发分上限"},
                    "G_min": {"type": "number", "description": "粘结指数下限"},
                    "Ad_max": {"type": "number", "description": "灰分上限"},
                    "total_weight_g": {"type": "number", "description": "总重量(克)，默认1000"},
                },
                "required": ["coal_names"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "predict_quality",
            "description": "根据配煤比例预测焦炭质量指标（CRI、CSR），支持多种模型：RF、SVR、KNN、Linear、DecisionTree、GBR",
            "parameters": {
                "type": "object",
                "properties": {
                    "blend_ratios": {
                        "type": "object",
                        "description": "配煤比例，格式: {煤种名: 百分比}，如 {\"气煤\": 20, \"肥煤\": 30}",
                    },
                    "model_name": {
                        "type": "string",
                        "description": "预测模型名称，可选: RF, SVR, KNN, Linear, DecisionTree, GBR，默认RF",
                    },
                },
                "required": ["blend_ratios"],
            },
        },
    },
]

SYSTEM_PROMPT = """你是 DeepCoke 配煤优化智能助手。你可以：
1. **查询煤种** — 列出数据库中所有可用煤种及其化验指标
2. **优化配煤** — 根据焦炭质量约束（CRI/CSR/M10/M25）和煤质约束（Vdaf/G/Ad），找到成本最低的配煤方案
3. **预测质量** — 根据用户给定的配煤比例，用机器学习模型预测焦炭的CRI和CSR

工作流程：
- 用户问配煤相关问题时，先用 list_coals 查看可用煤种
- 根据用户需求选择煤种，调用 optimize_blend 或 predict_quality
- 返回结果时用表格格式，清晰展示配比、重量、预测质量等

注意：
- 配比之和应为100%，每种煤的配比范围为0-60%
- CRI越低越好（一般<30为优），CSR越高越好（一般>60为优）
- 回答使用中文，数据用表格展示"""


# ── 结果格式化 ────────────────────────────────────────────────────

def _format_blend_result(result: dict) -> str:
    """将优化结果格式化为 Markdown 表格。"""
    hoppers = result.get("hoppers", [])
    # 过滤掉配比为0的煤种
    hoppers = [h for h in hoppers if h["ratio"] > 0.1]
    lines = []
    lines.append("**配煤方案：**\n")
    lines.append("| 煤种 | 配比(%) | 重量(g) |")
    lines.append("|------|---------|---------|")
    for h in hoppers:
        lines.append(f"| {h['coal']} | {h['ratio']} | {h['weight_g']} |")
    lines.append("")
    lines.append(f"- 总重量：{result.get('total_weight_g', 1000)}g")
    cost = result.get("cost_per_ton", 0)
    if cost > 0:
        lines.append(f"- 吨煤成本：{cost:.1f} 元")
    lines.append(f"- 优化算法：{result.get('optimizer', '')}")
    return "\n".join(lines)


def _format_predict_result(result: dict) -> str:
    """将预测结果格式化为 Markdown 表格。"""
    if "error" in result:
        return json.dumps(result, ensure_ascii=False)
    lines = []
    lines.append("**焦炭质量预测：**\n")
    lines.append("| 指标 | 预测值 |")
    lines.append("|------|--------|")
    for key, val in result.items():
        if key in ("model", "error"):
            continue
        if isinstance(val, (int, float)):
            lines.append(f"| {key} | {val:.2f} |")
        else:
            lines.append(f"| {key} | {val} |")
    if "model" in result:
        lines.append(f"\n- 预测模型：{result['model']}")
    return "\n".join(lines)


# ── 工具执行 ──────────────────────────────────────────────────────

def _exec_tool(name: str, args: dict) -> str:
    """执行工具调用，返回 JSON 字符串结果。"""
    rows, props = _get_coal_data()

    if name == "list_coals":
        if not rows:
            return json.dumps({"error": "数据库中没有煤样数据"}, ensure_ascii=False)
        summary = []
        for r in rows:
            summary.append({
                "煤种": r["coal_name"],
                "类型": r.get("coal_type", ""),
                "价格": r.get("coal_price"),
                "Vdaf": r.get("coal_vdaf"),
                "G": r.get("G"),
                "Ad": r.get("coal_ad"),
                "CRI": r.get("coke_CRI"),
                "CSR": r.get("coke_CSR"),
            })
        return json.dumps({"coals": summary, "count": len(summary)}, ensure_ascii=False)

    elif name == "optimize_blend":
        coal_names = args.get("coal_names", [])
        if not coal_names:
            coal_names = list(props.keys())
        constraints = {}
        for key in ["CRI_min", "CRI_max", "CSR_min", "CSR_max",
                     "M10_min", "M10_max", "M25_min", "M25_max",
                     "Vdaf_max", "G_min", "Ad_max"]:
            if key in args and args[key] is not None:
                constraints[key] = float(args[key])
        total_w = float(args.get("total_weight_g", 1000))
        result = optimize_blend(props, coal_names, constraints, total_w)
        if result is None:
            return json.dumps({"error": "无法找到满足约束的配煤方案，请放宽约束条件"}, ensure_ascii=False)
        return _format_blend_result(result)

    elif name == "predict_quality":
        blend_ratios = args.get("blend_ratios", {})
        model_name = args.get("model_name", "RF")
        result = predictor.predict(blend_ratios, props, model_name)
        return _format_predict_result(result)

    return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)


# ── Ollama 原生 API 调用 ─────────────────────────────────────────

def _ollama_chat(messages: list[dict], tools: list | None = None) -> dict:
    """调用 Ollama /api/chat，返回 message 对象。"""
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "options": {"num_ctx": 4096},
    }
    if tools:
        payload["tools"] = tools
    resp = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()["message"]


# ── Agent 主循环 ──────────────────────────────────────────────────

_TOOL_LABELS = {
    "list_coals": "查询可用煤种",
    "optimize_blend": "优化配煤方案",
    "predict_quality": "预测焦炭质量",
}


def run_agent(question: str, max_turns: int = 6, on_progress=None) -> str:
    """
    运行配煤优化 Agent，返回最终回答文本。

    Args:
        question: 用户问题
        max_turns: 最大工具调用轮次
        on_progress: 可选回调 on_progress(step, total, description)
    Returns:
        Agent 的最终文本回答
    """
    def _report(step, total, desc):
        if on_progress:
            on_progress(step, total, desc)

    # 预估总步骤：分析意图(1) + 最多 max_turns 轮工具调用(每轮2步：LLM思考+工具执行) + 生成回答(1)
    # 实际步骤数在运行中动态调整
    total_steps = 4  # 初始预估：分析→查询煤种→优化→生成回答
    current_step = 0

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question + " /nothink"},
    ]

    current_step += 1
    _report(current_step, total_steps, "正在分析配煤需求…")

    for turn in range(max_turns):
        try:
            reply = _ollama_chat(messages, tools=TOOLS)
        except Exception as e:
            logger.error(f"Ollama 调用失败: {e}")
            return f"LLM 调用失败: {e}"

        # 检查是否有 tool_calls
        tool_calls = reply.get("tool_calls")
        if not tool_calls:
            # 没有工具调用，返回文本回答
            current_step = total_steps
            _report(current_step, total_steps, "正在生成最终回答…")
            return reply.get("content", "")

        # 把 assistant 的 tool_calls 消息加入历史
        messages.append(reply)

        # 根据实际工具调用动态更新总步骤数
        remaining_possible = (max_turns - turn - 1)
        total_steps = current_step + len(tool_calls) + max(1, remaining_possible) + 1

        # 执行每个工具调用
        for tc in tool_calls:
            fn = tc["function"]
            tool_name = fn["name"]
            tool_args = fn.get("arguments", {})
            if isinstance(tool_args, str):
                try:
                    tool_args = json.loads(tool_args)
                except json.JSONDecodeError:
                    tool_args = {}

            current_step += 1
            label = _TOOL_LABELS.get(tool_name, tool_name)
            _report(current_step, total_steps, f"正在{label}…")

            logger.info(f"Tool call: {tool_name}({tool_args})")
            result = _exec_tool(tool_name, tool_args)

            messages.append({
                "role": "tool",
                "content": result,
            })

    # 超过最大轮次，做一次最终总结
    current_step += 1
    total_steps = current_step
    _report(current_step, total_steps, "正在生成最终回答…")

    messages.append({"role": "user", "content": "请根据以上工具调用结果给出最终回答。 /nothink"})
    try:
        reply = _ollama_chat(messages)
        return reply.get("content", "")
    except Exception as e:
        return f"生成最终回答失败: {e}"
