"""GraphRAG-lite:直接读 extract_entities 产出的 kg_entities.json 建概念索引,不依赖 Neo4j。

提供:
  available()                     — 索引是否就绪(json 存在且非空)
  related_concepts(concept, k)    — 与某概念共现最多的 k 个概念
  concept_paper_ids(concept)      — 讨论某概念的论文 id
  build_kg_context(concepts)      — 给查询概念,拼"相关概念/共现"文本喂生成(kg_context)
  concept_graph(paper_ids)        — 给一组论文,出 论文↔概念 关联图(vis-network 格式)

数据由 `python -m deepcoke.knowledge_graph.extract_entities` 批处理生成(每篇 1 次 LLM,可断点续)。
json 不存在时全部优雅退化为空,不影响主链路。
"""
import json
import functools
from collections import defaultdict

from .. import config


@functools.lru_cache(maxsize=1)
def _load():
    path = config.DATA_DIR / "kg_entities.json"
    if not path.exists():
        return None
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None
    if not data:
        return None

    c2p = defaultdict(set)        # concept(lower) → {paper_id}
    p2c = defaultdict(set)        # paper_id → {concept(lower)}
    disp = {}                     # lower → 展示名
    cooc = defaultdict(lambda: defaultdict(int))  # concept → concept → 权重
    ptitle = {}

    for rec in data:
        pid = rec.get("paper_id")
        ptitle[pid] = rec.get("title", "") or ""
        ents = rec.get("entities") or {}
        terms = []
        for key in ("concepts", "methods", "materials"):
            for t in (ents.get(key) or []):
                name = t.get("name", "") if isinstance(t, dict) else t
                name = str(name).strip()
                if name:
                    terms.append(name)
        for t in (ents.get("properties") or []):
            name = t.get("name", "") if isinstance(t, dict) else t
            name = str(name).strip()
            if name:
                terms.append(name)
        terms = list(dict.fromkeys(terms))
        for t in terms:
            tl = t.lower()
            c2p[tl].add(pid)
            p2c[pid].add(tl)
            disp.setdefault(tl, t)
        # 同篇共现
        for i, a in enumerate(terms):
            for b in terms[i + 1:]:
                cooc[a.lower()][b.lower()] += 1
                cooc[b.lower()][a.lower()] += 1
        # 显式关系加权
        for rel in (ents.get("concept_relations") or []):
            if isinstance(rel, (list, tuple)) and len(rel) >= 2:
                a, b = str(rel[0]).strip().lower(), str(rel[1]).strip().lower()
                if a and b:
                    cooc[a][b] += 2
                    cooc[b][a] += 2
                    disp.setdefault(a, rel[0])
                    disp.setdefault(b, rel[1])
    return {"c2p": c2p, "p2c": p2c, "disp": disp, "cooc": cooc, "ptitle": ptitle, "n": len(data)}


def available() -> bool:
    return _load() is not None


def related_concepts(concept: str, k: int = 6):
    idx = _load()
    if not idx:
        return []
    rel = idx["cooc"].get((concept or "").lower(), {})
    return [(idx["disp"].get(c, c), n) for c, n in sorted(rel.items(), key=lambda x: -x[1])[:k]]


def concept_paper_ids(concept: str):
    idx = _load()
    return list(idx["c2p"].get((concept or "").lower(), set())) if idx else []


def build_kg_context(concepts, max_concepts: int = 4) -> str:
    """查询概念 → 相关概念/共现 文本(喂 generate 的 kg_context)。"""
    idx = _load()
    if not idx or not concepts:
        return ""
    lines = []
    for c in list(concepts)[:max_concepts]:
        rel = related_concepts(c, 5)
        if rel:
            lines.append(f"- 「{c}」在文献中常与以下概念共现:" + "、".join(d for d, _ in rel))
    return "\n".join(lines)


def concept_graph(paper_ids, top_concepts_per_paper: int = 5) -> dict:
    """给一组论文,出 论文↔概念 关联图(vis-network 节点/边)。"""
    idx = _load()
    if not idx:
        return {"nodes": [], "edges": [], "source": "kg_empty"}
    nodes, edges, seen_c = {}, [], set()
    for pid in paper_ids:
        p_id = f"P{pid}"
        nodes[p_id] = {"id": p_id, "label": (idx["ptitle"].get(pid, "") or f"Paper {pid}")[:40],
                       "group": "paper", "title": idx["ptitle"].get(pid, "")}
        concepts = list(idx["p2c"].get(pid, set()))[:top_concepts_per_paper]
        for cl in concepts:
            c_id = f"C{cl}"
            if c_id not in seen_c:
                seen_c.add(c_id)
                nodes[c_id] = {"id": c_id, "label": idx["disp"].get(cl, cl), "group": "concept"}
            edges.append({"from": p_id, "to": c_id})
    return {"nodes": list(nodes.values()), "edges": edges, "source": "kg_index"}
