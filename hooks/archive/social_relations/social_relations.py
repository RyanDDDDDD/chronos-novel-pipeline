"""静态社交关系渲染——从 relationship_graph.json 读师徒/姐妹/长幼等静态社交边与组，
渲染成 state 推演 prompt 里的"## 角色关系"文本段。纯派生、零存储：图谱数据本身由
engine.setup.cast.incremental_relationship（LLM 推断）在角色创建时写入，这里只读取+
按本章在场名单过滤+渲染。"""
from __future__ import annotations

from engine.setup.cast.relationship_graph import iter_edges, iter_groups, load_graph


def relations_for_character(name: str, present_names: list[str]) -> str:
    """
关系块文本（建档/architect grounding）。无任何关系 → ""（消费侧维持"陌生人走本名"）。"""

    if not name:
        return ""
    present = set(present_names)
    pairs: list[tuple[str, str]] = []

    graph = load_graph()
    for e in iter_edges(graph):
        frm, to = e["from"], e["to"]
        if name == frm and to in present:
            pairs.append((to, f"社交·你→ta（{e['nature']}）"))
        elif name == to and frm in present:
            pairs.append((frm, f"社交·ta→你（{e['nature']}）"))
    for g in iter_groups(graph):
        members = [str(m).strip() for m in g["members"]]
        if name in members:
            for m in members:
                if m != name and m in present:
                    pairs.append((m, f"社交平等·同属「{g['type']}」"))

    if not pairs:
        return ""
    lines = [f"- {desc}：「{target}」" for target, desc in pairs]
    return (
        "## 角色关系（真值，称呼/自称严格据此派生，**勿自行脑补关系或称呼**）\n"
        + "\n".join(lines)
    )
