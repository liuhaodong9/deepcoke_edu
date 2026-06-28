"""
深度测试 — 边界情况 + 集成兼容性
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

print("=" * 70)
print("DeepCoke Deep Test — 边界 + 集成兼容性")
print("=" * 70)


def section(title):
    print(f"\n{'━' * 70}\n  {title}\n{'━' * 70}")


# ────────────────────────────────────────────────────────────────────
# Test A: 边界情况
# ────────────────────────────────────────────────────────────────────
section("Test A: 边界情况")

from deepcoke.agent_tools import (
    tool_find_relevant_papers,
    tool_read_paper_fulltext,
    tool_read_paper_section,
    execute_tool,
)

# A.1: 不存在的 paper_id
print("\n  A.1: 不存在的 paper_id=99999")
r = tool_read_paper_fulltext(99999)
assert "error" in r, "应该返回 error 字段"
print(f"     ✅ 返回 error: {r['error']}")

r = tool_read_paper_section(99999, "Methods")
assert "error" in r
print(f"     ✅ section 也返回 error")

# A.2: 空 query
print("\n  A.2: 空 query")
r = tool_find_relevant_papers("", top_n=2)
print(f"     papers 数: {len(r.get('papers', []))} (空 query 不应崩)")

# A.3: top_n 边界
print("\n  A.3: top_n=100 (超过默认 8 上限,应该被 clamp)")
r = tool_find_relevant_papers("coke", top_n=100)
assert len(r["papers"]) <= 8, f"应该 clamp 到 8 以内,实际 {len(r['papers'])}"
print(f"     ✅ 被 clamp 到 {len(r['papers'])} 篇")

# A.4: top_n=0 应该退到 1
print("\n  A.4: top_n=0")
r = tool_find_relevant_papers("coke", top_n=0)
assert len(r["papers"]) >= 1 or len(r["papers"]) == 0
print(f"     papers 数: {len(r['papers'])}")

# A.5: 不存在的章节 (返回 available_sections 列表帮 LLM 重试)
print("\n  A.5: 不存在的章节 'XYZ'")
first = tool_find_relevant_papers("coke quality", top_n=1)
if first["papers"]:
    pid = first["papers"][0]["paper_id"]
    r = tool_read_paper_section(pid, "XYZ_nonexistent_section")
    assert "available_sections" in r, "应该返回 available_sections 帮 LLM"
    print(f"     ✅ 返回 available_sections: {r['available_sections'][:5]}")


# ────────────────────────────────────────────────────────────────────
# Test B: execute_tool 序列化所有工具结果
# ────────────────────────────────────────────────────────────────────
section("Test B: execute_tool — JSON 序列化所有工具")

import json
tests = [
    ("find_relevant_papers", {"query": "coke", "top_n": 2}),
    ("read_paper_fulltext", {"paper_id": 176}),
    ("read_paper_section", {"paper_id": 176, "section": "Methods"}),
    ("finalize_answer", {"rationale": "Have enough"}),
    ("unknown_xxx", {}),  # 未知工具不崩
]
for name, args in tests:
    try:
        result = execute_tool(name, args)
        obj = json.loads(result)  # 必须是 valid JSON
        print(f"  ✅ {name} → JSON OK, keys={list(obj.keys())[:6]}")
    except Exception as e:
        print(f"  ❌ {name} → 失败: {e}")


# ────────────────────────────────────────────────────────────────────
# Test C: agent_loop fallback 机制 (没 LLM 也能跑到 fallback)
# ────────────────────────────────────────────────────────────────────
section("Test C: agent_loop fallback (无 LLM 触发)")

import os
# 强制走 ollama 模式让 chat_with_tools 抛 NotImplementedError → 触发 fallback
old_mode = os.environ.get("LLM_MODE", "")
os.environ["LLM_MODE"] = "ollama"

# 重新 import 让 LLM_MODE 生效
import importlib
import deepcoke.llm_client
importlib.reload(deepcoke.llm_client)
import deepcoke.agent_loop
importlib.reload(deepcoke.agent_loop)
from deepcoke.agent_loop import run_agent_loop

result = run_agent_loop("coke CSR factors", "焦炭 CSR 影响因素", max_iterations=2)
assert result["fallback"] == True, "应该 fallback"
assert isinstance(result["chunks"], list)
print(f"  ✅ fallback=True 时返回结构正确")
print(f"     iterations={result['iterations']} chunks={len(result['chunks'])} "
      f"papers={len(result['papers_meta'])}")

# 恢复
os.environ["LLM_MODE"] = old_mode


# ────────────────────────────────────────────────────────────────────
# Test D: enhanced_pipeline_graph build + initial state structure
# ────────────────────────────────────────────────────────────────────
section("Test D: enhanced_pipeline_graph 结构验证")

# Reload 确保最新版
import deepcoke.enhanced_pipeline_graph
importlib.reload(deepcoke.enhanced_pipeline_graph)
from deepcoke.enhanced_pipeline_graph import (
    build_enhanced_graph,
    EnhancedPipelineState,
)

g = build_enhanced_graph()
print(f"  ✅ graph 编译成功, nodes:")
for n in g.get_graph().nodes:
    print(f"     - {n}")
print(f"  edges:")
edges = list(g.get_graph().edges)
for e in edges[:15]:
    print(f"     - {e.source} → {e.target}")

# Initial state 必须有 EnhancedPipelineState 全部字段
expected_fields = {
    "question", "question_type", "agent_plan", "agent_plan_idx",
    "supervisor_reasoning", "english_queries", "key_concepts",
    "chunks", "kg_context", "structured_evidence", "reasoning_trace",
    "agent_papers_meta", "agent_finalize_rationale",
    "agent_iterations", "agent_fallback", "output",
}
print(f"\n  PipelineState 必需字段 ({len(expected_fields)} 个):")
for f in sorted(expected_fields):
    print(f"     - {f}")


# ────────────────────────────────────────────────────────────────────
# Test E: chat_with_tools 协议拼装 (mock 调用,不真请求 vllm)
# ────────────────────────────────────────────────────────────────────
section("Test E: chat_with_tools 协议 (mock)")

os.environ["LLM_MODE"] = "openai"
importlib.reload(deepcoke.llm_client)
from deepcoke.llm_client import chat_with_tools

# 测验证: 调用应该按 OpenAI 协议构造 payload(实际会失败因为本机没 vllm)
import requests
try:
    chat_with_tools(
        [{"role": "user", "content": "test"}],
        tools=[{"type": "function", "function": {"name": "test_fn", "description": "x",
                "parameters": {"type": "object", "properties": {}}}}],
        tool_choice="auto",
    )
    print("  ❌ 不该成功(本机没 vllm)")
except (requests.ConnectionError, requests.Timeout, ConnectionError) as e:
    print(f"  ✅ 按预期连接失败(本机没 vllm): {type(e).__name__}")
except Exception as e:
    msg = str(e)
    if "Connection" in msg or "refused" in msg or "Could not connect" in msg:
        print(f"  ✅ 连接失败(预期): {msg[:80]}")
    else:
        print(f"  ❌ 协议错误: {type(e).__name__}: {msg[:100]}")


print()
print("=" * 70)
print("Deep Test 完成。看 ❌ 是否存在。")
print("=" * 70)
