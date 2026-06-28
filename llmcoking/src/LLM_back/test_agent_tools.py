"""
本地 smoke test — 验证 agent_tools.py 的 4 个工具函数(不需要 LLM)
直接连本机 ChromaDB,看返回的结构和数据是否符合预期。

用法(在 D:\\deepcoke\\deepcoke_edu\\llmcoking\\src\\LLM_back\\):
    python -X utf8 test_agent_tools.py

如果都过 → agent_tools.py 算法逻辑正确,可以推服务器了
如果某些失败 → 看错误信息修代码
"""
import json
import sys
from pathlib import Path

# 加项目根到 path 让 deepcoke 模块能 import
sys.path.insert(0, str(Path(__file__).parent))

print("=" * 70)
print("DeepCoke Agent Tools — 本地 Smoke Test")
print("=" * 70)


def section(title):
    print(f"\n{'━' * 70}\n  {title}\n{'━' * 70}")


# ────────────────────────────────────────────────────────────────────
# Test 0: import 检查
# ────────────────────────────────────────────────────────────────────
section("Test 0: 模块 import 检查")

try:
    from deepcoke.agent_tools import (
        TOOL_DEFINITIONS,
        tool_find_relevant_papers,
        tool_read_paper_fulltext,
        tool_read_paper_section,
        execute_tool,
        reconstruct_chunks_for_generation,
    )
    print("  ✅ agent_tools import OK")
    print(f"  → TOOL_DEFINITIONS 有 {len(TOOL_DEFINITIONS)} 个工具")
    for t in TOOL_DEFINITIONS:
        print(f"     - {t['function']['name']}: {t['function']['description'][:60]}…")
except Exception as e:
    print(f"  ❌ agent_tools import 失败: {e}")
    sys.exit(1)

try:
    from deepcoke.agent_loop import run_agent_loop
    print("  ✅ agent_loop import OK")
except Exception as e:
    print(f"  ❌ agent_loop import 失败: {e}")

try:
    from deepcoke.enhanced_pipeline_graph import process_question as enhanced_pq
    from deepcoke.enhanced_pipeline_graph import build_enhanced_graph
    print("  ✅ enhanced_pipeline_graph import OK")
    g = build_enhanced_graph()
    print(f"  → graph 编译成功")
except Exception as e:
    print(f"  ❌ enhanced_pipeline_graph 失败: {e}")
    import traceback; traceback.print_exc()

try:
    from deepcoke.llm_client import chat_with_tools
    print("  ✅ llm_client.chat_with_tools import OK")
except Exception as e:
    print(f"  ❌ chat_with_tools import 失败: {e}")


# ────────────────────────────────────────────────────────────────────
# Test 1: find_relevant_papers
# ────────────────────────────────────────────────────────────────────
section("Test 1: tool_find_relevant_papers — 论文级检索")

queries = [
    "What factors affect coke CSR?",
    "How is CRI measured?",
    "Effect of volatile matter on coking coal",
]

for q in queries:
    print(f"\n  Query: {q!r}")
    try:
        result = tool_find_relevant_papers(q, top_n=3)
        papers = result.get("papers", [])
        print(f"  → 找到 {len(papers)} 篇候选论文:")
        for i, p in enumerate(papers, 1):
            title = (p.get("title") or "")[:60]
            score = p.get("max_score", 0)
            hits = p.get("hit_chunks", 0)
            print(f"     [{i}] paper_id={p['paper_id']} score={score} hits={hits}")
            print(f"         {title}")
            abs_preview = (p.get("abstract") or "")[:120].replace("\n", " ")
            if abs_preview:
                print(f"         abstract: {abs_preview}…")
        if not papers:
            print(f"  ⚠️  返回空,可能 ChromaDB 没数据或 query 太冷")
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        import traceback; traceback.print_exc()


# ────────────────────────────────────────────────────────────────────
# Test 2: read_paper_fulltext (取 Test 1 的第一个 paper_id)
# ────────────────────────────────────────────────────────────────────
section("Test 2: tool_read_paper_fulltext — 读全文")

try:
    first_result = tool_find_relevant_papers("coke quality CSR CRI", top_n=1)
    candidates = first_result.get("papers", [])
    if not candidates:
        print("  ⚠️  没找到候选论文,跳过 read_paper_fulltext 测试")
    else:
        pid = candidates[0]["paper_id"]
        print(f"  读 paper_id={pid} 的全文...")
        result = tool_read_paper_fulltext(pid)

        if "error" in result:
            print(f"  ❌ 失败: {result['error']}")
        else:
            print(f"  ✅ 成功")
            print(f"     标题: {result['title'][:80]}")
            print(f"     章节: {result['sections']}")
            print(f"     字数: {result['char_count']}")
            print(f"     截断: {result['truncated']}")
            preview = result["fulltext"][:400].replace("\n", " ")
            print(f"     全文开头: {preview}…")
except Exception as e:
    print(f"  ❌ 失败: {e}")
    import traceback; traceback.print_exc()


# ────────────────────────────────────────────────────────────────────
# Test 3: read_paper_section
# ────────────────────────────────────────────────────────────────────
section("Test 3: tool_read_paper_section — 读单章节")

try:
    first_result = tool_find_relevant_papers("coke quality CSR CRI", top_n=1)
    candidates = first_result.get("papers", [])
    if not candidates:
        print("  ⚠️  跳过(没候选)")
    else:
        pid = candidates[0]["paper_id"]
        # 试常见章节名
        for section_name in ["Methods", "Results", "Abstract", "Introduction"]:
            print(f"\n  读 paper_id={pid} 的 '{section_name}' 章节...")
            result = tool_read_paper_section(pid, section_name)
            if "error" in result:
                print(f"     (无此章节)")
            else:
                print(f"     ✅ 字数 {result['char_count']}, 截断 {result['truncated']}")
                preview = result["text"][:200].replace("\n", " ")
                print(f"     片段: {preview}…")
                break
except Exception as e:
    print(f"  ❌ 失败: {e}")
    import traceback; traceback.print_exc()


# ────────────────────────────────────────────────────────────────────
# Test 4: execute_tool 统一入口 + JSON 序列化
# ────────────────────────────────────────────────────────────────────
section("Test 4: execute_tool — 统一入口 + JSON 兼容")

try:
    result_str = execute_tool("find_relevant_papers", {"query": "coke porosity", "top_n": 2})
    obj = json.loads(result_str)
    print(f"  ✅ find_relevant_papers JSON serializable")
    print(f"     keys: {list(obj.keys())}")

    result_str = execute_tool("finalize_answer", {"rationale": "Already have enough"})
    obj = json.loads(result_str)
    print(f"  ✅ finalize_answer: {obj}")

    result_str = execute_tool("unknown_tool", {})
    obj = json.loads(result_str)
    print(f"  ✅ unknown_tool 不崩: {obj}")
except Exception as e:
    print(f"  ❌ 失败: {e}")
    import traceback; traceback.print_exc()


# ────────────────────────────────────────────────────────────────────
# Test 5: reconstruct_chunks_for_generation — 模拟 agent log
# ────────────────────────────────────────────────────────────────────
section("Test 5: reconstruct_chunks_for_generation — 模拟还原")

try:
    # 模拟 agent 跑了 2 个工具调用
    fake_log = [
        (
            "find_relevant_papers",
            {"query": "CSR", "top_n": 2},
            {"papers": [
                {"paper_id": 1, "title": "Paper A", "authors": "X et al", "year": 2020,
                 "category": "CSR", "max_score": 0.85, "abstract": "Abc..."},
                {"paper_id": 2, "title": "Paper B", "authors": "Y et al", "year": 2021,
                 "category": "CRI", "max_score": 0.78, "abstract": "Def..."},
            ]},
        ),
        (
            "read_paper_fulltext",
            {"paper_id": 1},
            {"paper_id": 1, "title": "Paper A",
             "fulltext": "Full text of paper A...", "char_count": 100, "truncated": False},
        ),
    ]
    chunks, papers_meta = reconstruct_chunks_for_generation(fake_log)
    print(f"  ✅ 重构成功: chunks={len(chunks)}, papers={len(papers_meta)}")
    for c in chunks:
        print(f"     chunk: pid={c.paper_id} section={c.section} score={c.score} len={len(c.text)}")
    for p in papers_meta:
        print(f"     paper: pid={p['paper_id']} cited={p['cited']} title={p['title']}")
except Exception as e:
    print(f"  ❌ 失败: {e}")
    import traceback; traceback.print_exc()


print()
print("=" * 70)
print("Smoke Test 完成。如果没看到 ❌,可以推服务器了。")
print("=" * 70)
