"""Static social relationship graph: equally named groups (overlapping) + directed relationship edges
between characters (master-disciple/sisters/fellow sect members/rivals...), generated during the
construction period -- **the whole book is static** (purely social, does not evolve with plot/state).

Data model (see spec 2026-06-23-relationship-graph-evolution):
- groups: {gid: {members, type, priority}} or the old list form - equal relationship; the mutual name takes the highest type of priority of the shared group.
- edges: {"from→to": {from, to, nature, relationship_anchor}} or old list - directed relationship (nature free text,
  Direction = the initiating/pointing direction of the relationship, purely descriptive).
- No group and no edge = stranger (renders as real name). The consumer side always reads the static graph through iter_* (see hooks/archive/social_relations for the state-derivation-time rendering layer).

This module is pure data: schema/verification/reading and writing + mutually derived pure functions; it does not call LLM and does not touch the engine hot path."""
from __future__ import annotations


def empty_graph() -> dict[str, dict]:
    return {"groups": {}, "edges": {}}


def iter_groups(graph: dict) -> list[dict]:
    """
normalize groups (dict key id or old list) → [{id, members, type, priority}, ...]."""
    raw = graph.get("groups")
    out: list[dict] = []
    if isinstance(raw, dict):
        for gid, g in raw.items():
            if isinstance(g, dict):
                out.append({
                    "id": str(gid),
                    "members": g.get("members") or [],
                    "type": str(g.get("type", "")),
                    "priority": g.get("priority", 0),
                })
    elif isinstance(raw, list):
        for i, g in enumerate(raw):
            if isinstance(g, dict):
                out.append({
                    "id": f"g{i}",
                    "members": g.get("members") or [],
                    "type": str(g.get("type", "")),
                    "priority": g.get("priority", 0),
                })
    return out


def clean_ref_terms(raw: object) -> list[str]:
    """Normalize an edge's from_ref_terms/to_ref_terms: non-list -> [], filters out
    non-string/blank entries -- these are LLM-authored free text, tolerate malformed input
    rather than erroring the whole graph load over a decorative optional field."""
    if not isinstance(raw, list):
        return []
    return [t.strip() for t in raw if isinstance(t, str) and t.strip()]


def iter_edges(graph: dict) -> list[dict]:
    """Normalize edges (dict key from→to or old list) →
    [{id, from, to, nature, relationship_anchor, from_ref_terms, to_ref_terms}, ...]."""
    raw = graph.get("edges")
    out: list[dict] = []
    items = raw.values() if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    for e in items:
        if not isinstance(e, dict):
            continue
        frm, to = str(e.get("from", "")).strip(), str(e.get("to", "")).strip()
        out.append({
            "id": f"{frm}→{to}",
            "from": frm,
            "to": to,
            "nature": str(e.get("nature", "")),
            "relationship_anchor": str(e.get("relationship_anchor", "")),
            "from_ref_terms": clean_ref_terms(e.get("from_ref_terms")),
            "to_ref_terms": clean_ref_terms(e.get("to_ref_terms")),
        })
    return out


def peer_label(graph: dict, a: str, b: str) -> str:
    """
The type with the highest priority among a and b belonging to equal groups; no common group → ""."""
    best_type, best_pri = "", None
    for g in iter_groups(graph):
        members = {str(m).strip() for m in g["members"]}
        if a in members and b in members:
            pri = g["priority"] if isinstance(g["priority"], int) else 0
            if best_pri is None or pri > best_pri:
                best_pri, best_type = pri, g["type"].strip()
    return best_type


def edges_for_character(graph: dict, name: str) -> list[dict]:
    """name 作为 from 或 to 出现的全部边（两个方向都收），供按角色名查图谱用。"""
    name = name.strip()
    return [e for e in iter_edges(graph) if e["from"] == name or e["to"] == name]


def related_to_present(graph: dict, present: set[str]) -> set[str]:
    """This module's actual intended consumption pattern for story_sandbox: given the
    characters already confidently known to be present, find everyone connected to them by a
    relationship edge (either direction) who ISN'T already present -- background/relationship
    context for the story, not itself a claim that they're on stage. Structured from/to lookup,
    not text scanning: sidesteps the ambiguity a ref_terms-based keyword scan runs into (see
    entity_index.py::scan_characters's docstring) since it only ever looks at already-resolved
    names, never free text."""
    related: set[str] = set()
    for e in iter_edges(graph):
        if e["from"] in present and e["to"] not in present:
            related.add(e["to"])
        elif e["to"] in present and e["from"] not in present:
            related.add(e["from"])
    return related


def merge_overlay(graph: dict, overlay: dict[str, dict]) -> dict:
    """Lays a session-local edge overlay (story_sandbox's per-turn relationship proposals, see
    profile_mutate.py) over the static base graph -- overlay entries win on a shared "from→to"
    key (this module's own edge-key format, see iter_edges), same baseline+overlay merge
    semantics character_profile already uses elsewhere in story_sandbox. Pure: never mutates
    `graph`, never touches disk -- the overlay lives only in the checkpointer, the base graph
    stays the file's own static truth (see this module's docstring)."""
    if not overlay:
        return graph
    edges = {**iter_edges_by_key(graph), **overlay}
    return {"groups": graph.get("groups") or {}, "edges": edges}


def iter_edges_by_key(graph: dict) -> dict[str, dict]:
    """Same normalization as iter_edges, but keyed by "from→to" instead of a list -- the shape
    merge_overlay needs to let overlay entries override same-key base edges."""
    raw = graph.get("edges")
    out: dict[str, dict] = {}
    items = raw.values() if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    for e in items:
        if not isinstance(e, dict):
            continue
        frm, to = str(e.get("from", "")).strip(), str(e.get("to", "")).strip()
        if frm and to:
            out[f"{frm}→{to}"] = e
    return out


def directed_edge(graph: dict, frm: str, to: str) -> dict | None:
    """Take the master-detail edge of frm→to; None → None."""
    for e in iter_edges(graph):
        if e["from"] == frm and e["to"] == to:
            return {
                "from": e["from"],
                "to": e["to"],
                "nature": e["nature"],
                "relationship_anchor": e["relationship_anchor"],
            }
    return None


def render_overview(graph: dict, names: list[str] | None = None) -> str:
    """
A human-readable overview of the whole picture (injecting the architect skeleton as a relationship framework anchor to prevent the master and slave from being written as equals).

    When names is non-empty, only relations involving these roles will be rendered (presence filtering in this chapter). Empty graph/no correlation → ""."""

    keep = {str(n).strip() for n in names} if names else None
    lines: list[str] = []
    for e in iter_edges(graph):
        frm, to = e["from"], e["to"]
        if keep is not None and (frm not in keep or to not in keep):
            continue
        s = f"- 主从：「{frm}」主导 →「{to}」（{e['nature']}）"
        if e["relationship_anchor"]:
            s += f"；{frm} 对 {to} 的执念：{e['relationship_anchor']}"
        lines.append(s)
    for g in iter_groups(graph):
        members = [str(m).strip() for m in g["members"]]
        if keep is not None:
            members = [m for m in members if m in keep]
        if len(members) >= 2:
            lines.append(f"- 平等：「{'、'.join(members)}」同属「{g['type']}」")
    if not lines:
        return ""
    return "## 角色关系（图谱真值，据此定角色互动的关系框架，勿写成与之相悖的关系）\n" + "\n".join(lines)


def append_edge(edge: dict, path: str | None = None) -> None:
    """Append one edge row to relationship_edges (append-only log). Does not read existing
    rows -- each call only inserts its own row, same concurrency posture as the old jsonl log."""
    import json
    import os

    from repositories.sqlite_store import get_connection
    from utils.paths import active_novel_id, novel_dir

    db_path = path or os.path.join(novel_dir(active_novel_id()), "chronos.sqlite3")
    conn = get_connection(db_path)
    frm, to = str(edge.get("from", "")).strip(), str(edge.get("to", "")).strip()
    conn.execute(
        "INSERT INTO relationship_edges (from_name, to_name, nature, relationship_anchor,"
        " from_ref_terms_json, to_ref_terms_json, deleted) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            frm,
            to,
            str(edge.get("nature", "")),
            str(edge.get("relationship_anchor", "")),
            json.dumps(clean_ref_terms(edge.get("from_ref_terms"))),
            json.dumps(clean_ref_terms(edge.get("to_ref_terms"))),
            1 if edge.get("deleted") else 0,
        ),
    )
    conn.commit()


def load_graph(path: str | None = None) -> dict:
    """Read relationship_edges rows, fold by "{from}→{to}" into {"groups": {}, "edges": {...}}.
    Later rows override earlier ones for the same key; deleted=1 tombstones drop the key.
    Missing db file → empty graph via get_connection auto-create; sqlite3.Error → empty graph."""
    import json
    import os
    import sqlite3

    from repositories.sqlite_store import get_connection
    from utils.paths import active_novel_id, novel_dir

    db_path = path or os.path.join(novel_dir(active_novel_id()), "chronos.sqlite3")
    try:
        conn = get_connection(db_path)
        rows = conn.execute(
            "SELECT from_name, to_name, nature, relationship_anchor, from_ref_terms_json,"
            " to_ref_terms_json, deleted FROM relationship_edges ORDER BY id",
        ).fetchall()
    except sqlite3.Error:
        return empty_graph()
    edges: dict[str, dict] = {}
    for frm, to, nature, anchor, from_terms, to_terms, deleted in rows:
        key = f"{frm}→{to}"
        if deleted:
            edges.pop(key, None)
        else:
            edges[key] = {
                "from": frm,
                "to": to,
                "nature": nature,
                "relationship_anchor": anchor,
                "from_ref_terms": json.loads(from_terms),
                "to_ref_terms": json.loads(to_terms),
            }
    return {"groups": {}, "edges": edges}


def remove_edge(frm: str, to: str, path: str | None = None) -> None:
    """逻辑删除 frm→to 这条边：不重写文件，只追加一条 `{"deleted": true}` 墓碑
    （跟 append_edge 一样是纯 append，并发安全）。load_graph 折叠时据此把该 key 从结果里摘除。"""
    append_edge({"from": frm, "to": to, "deleted": True}, path=path)


def validate_edge(edge: dict, names: set[str]) -> list[str]:
    """单条边的最小校验（增量生成场景用，不是整图批量校验）：from/to 必须是花名册里的真实
    given_name、二者不同、nature 非空。"""
    errors: list[str] = []
    frm = str(edge.get("from", "")).strip()
    to = str(edge.get("to", "")).strip()
    if frm not in names:
        errors.append(f"from「{frm}」不在花名册内")
    if to not in names:
        errors.append(f"to「{to}」不在花名册内")
    if frm == to:
        errors.append("from 与 to 不能相同")
    if not str(edge.get("nature", "")).strip():
        errors.append("nature 不能为空")
    return errors

