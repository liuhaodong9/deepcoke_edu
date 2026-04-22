"""
DeepCoke Supervisor — LLM 驱动的智能路由决策
替换关键词匹配 classifier，支持多 agent 串行计划。
"""
import json
import logging
import re
from .llm_client import chat_json

logger = logging.getLogger("deepcoke.supervisor")

# 可用 agent 及其描述
AGENT_DESCRIPTIONS = {
    "coal_price":      "煤价查询 — 查询今日煤炭市场行情、成交价、报价",
    "oven_control":    "焦炉操作 — 装填配煤方案到焦炉、开启/关闭数字孪生监控",
    "optimization":    "配煤优化 — 优化配煤比例、预测焦炭质量(CRI/CSR/M10/M25)、寻找最优配方",
    "data_management": "数据管理 — 煤样数据的增删改查、CNN预测",
    "knowledge_qa":    "知识问答 — 焦化领域文献检索、学术问答、因果分析、工艺流程",
    "simple_chat":     "闲聊 — 问候、闲聊、非焦化领域话题",
}

_SUPERVISOR_PROMPT = """你是 DeepCoke 焦化配煤机器人的调度主管（Supervisor）。
根据用户的问题，决定应该调用哪些 Agent 来处理，以及调用顺序。

可用的 Agent：
- coal_price: 煤价查询 — 查询今日煤炭市场行情、成交价、报价
- oven_control: 焦炉操作 — 装填配煤方案到焦炉、开启/关闭数字孪生监控
- optimization: 配煤优化 — 优化配煤比例、预测焦炭质量(CRI/CSR/M10/M25)、寻找最优配方
- data_management: 数据管理 — 煤样数据的增删改查、CNN预测
- knowledge_qa: 知识问答 — 焦化领域文献检索、学术问答、因果分析、工艺流程
- simple_chat: 闲聊 — 问候、闲聊、非焦化领域话题

规则：
1. 大多数问题只需要一个 Agent
2. 跨域问题可以串行调用多个 Agent，按执行顺序排列
   例如："查一下澳煤价格然后帮我配煤" → ["coal_price", "optimization"]
   例如："先看看煤仓有哪些煤，然后优化配比" → ["data_management", "optimization"]
3. 如果不确定，优先选 knowledge_qa（比 simple_chat 更有用）

返回严格 JSON（不要 markdown 包裹）：
{"agents": ["agent1"], "reasoning": "一句话解释为什么这样路由"}

只返回 JSON，不要其他内容。"""


def _quick_classify(question: str) -> list[str] | None:
    """
    关键词快速匹配（保留作为快速通道，避免简单问题浪费 LLM 调用）。
    返回 None 表示需要 LLM 决策。
    """
    # 煤价查询（最高优先级）
    if re.search(r"成交价|煤价|报价|行情|市场价|今日.*价|价格查询|煤炭.*价格|焦煤.*价格", question):
        return ["coal_price"]

    # 焦炉操作
    if re.search(r"填入.*焦炉|装入.*焦炉|焦炉.*装|焦炉.*填|开启.*孪生|数字孪生.*监控|启动.*监控|开启.*监控|关闭.*监控", question):
        return ["oven_control"]

    # 数据管理（明确的增删改操作）
    if re.search(
        r"添加.*煤|新增.*煤|录入.*煤|删除.*煤|移除.*煤|修改.*煤|更新.*煤"
        r"|加一个煤|加几个煤|加条煤|查看.*煤样|所有煤样|煤样.*列表|煤样.*数据库"
        r"|CNN.*预测|用CNN|用模型预测",
        question,
    ):
        return ["data_management"]

    # 简单问候
    if re.search(r"^(你好|hi|hello|嗨|早|在吗|你是谁)\s*[?？!！。.]*$", question, re.IGNORECASE):
        return ["simple_chat"]

    return None  # 需要 LLM 决策


def supervisor_decide(question: str) -> dict:
    """
    Supervisor 决策入口。
    返回 {"agents": [...], "reasoning": "..."}
    """
    # 1) 关键词快速通道
    quick = _quick_classify(question)
    if quick is not None:
        return {"agents": quick, "reasoning": "关键词匹配快速路由"}

    # 2) LLM 决策
    try:
        raw = chat_json(
            [{"role": "system", "content": _SUPERVISOR_PROMPT},
             {"role": "user", "content": question}],
            temperature=0.0,
        )
        # 清理可能的 markdown 包裹
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        result = json.loads(raw)
        agents = result.get("agents", [])
        reasoning = result.get("reasoning", "")

        # 验证 agent 名称合法
        valid_agents = [a for a in agents if a in AGENT_DESCRIPTIONS]
        if not valid_agents:
            logger.warning(f"[supervisor] LLM 返回无效 agents: {agents}，fallback to knowledge_qa")
            return {"agents": ["knowledge_qa"], "reasoning": "LLM 路由结果无效，默认知识问答"}

        logger.info(f"[supervisor] decision: {valid_agents} — {reasoning}")
        return {"agents": valid_agents, "reasoning": reasoning}

    except Exception as e:
        logger.error(f"[supervisor] LLM 决策异常: {e}，fallback to knowledge_qa")
        return {"agents": ["knowledge_qa"], "reasoning": f"LLM 异常({e})，默认知识问答"}
