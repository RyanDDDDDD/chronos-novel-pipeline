"""Character card: macro file + runtime dynamic_state → card to feed the character agent."""
from __future__ import annotations

from context.content_packs import render_custom_fields_block
from context.dialogue.scene_aware import as_target_pool_map
from context.personality import resolved_personality

from engine.author_loop.dialogue_mode.chapter_state import resolve_card_state
from engine.setup.cast.clothing_dna import render_clothing_dna_lines


def render_character_card(
    name: str, chapter: int, stage: int, *,
    include_persona: bool = True, dynamic_state: dict | None = None,
) -> str:
    """The character card of this character in this chapter and stage: persona + current
    dynamic state/self-proclaimed (missing -> simplest card).

    dynamic_state carries the runtime-derived 5-field state (psychology/posture/clothing/
    action/demeanor) -- resolved separately by the caller (see react_graph.py), not read from
    archive here (archive only holds static/rolling fields going forward).

    include_persona=False: Remove the two lines of personality/self-proclaimed - for agents (such
    as directors) who only set up the scene."""

    resolved = resolve_card_state(name, chapter, stage)
    if not resolved:
        return f"角色：{name}（无档案，按名字最简扮演）"
    dyn = dynamic_state or {}
    self_ref_raw = resolved.get("self_ref")
    self_ref = (
        as_target_pool_map(self_ref_raw, legacy_default_key="_default")
        if self_ref_raw else {}
    )
    lines = [f"角色：{name}"]
    anchors = resolved.get("causal_anchors")
    if isinstance(anchors, dict) and anchors:
        lines.append("因果锚点：")
        lines.extend(
            f"  - {k}：{v}" for k, v in anchors.items()
            if isinstance(v, str) and v.strip()
        )
    if dyn.get("psychology"):
        lines.append(f"当前心理：{dyn['psychology']}")
    if dyn.get("posture"):
        lines.append(f"当前体态：{dyn['posture']}")
    physique = resolved.get("physique")
    if isinstance(physique, dict) and physique:
        lines.append("体貌：")
        lines.extend(f"  - {slot}：{desc}" for slot, desc in physique.items() if desc)
    if include_persona:
        personality = resolved_personality(resolved)
        if personality:
            lines.append(f"人格：{personality}")
    if include_persona:
        default_self = self_ref.get("_default") or []
        if default_self:
            lines.append(f"自称：{'／'.join(default_self)}")
        verbal_tic = str(resolved.get("verbal_tic") or "").strip()
        if verbal_tic:
            lines.append(f"口癖：{verbal_tic}")
        identity_background = str(resolved.get("identity_background") or "").strip()
        if identity_background:
            lines.append(f"身份背景：{identity_background}")
        hobbies = resolved.get("hobbies") or []
        if hobbies:
            lines.append(f"爱好：{'、'.join(hobbies)}")
        dna = resolved.get("clothing_dna") or {}
        if isinstance(dna, dict) and dna:
            lines.extend(render_clothing_dna_lines(dna))
        lines.extend(render_custom_fields_block(resolved))
    if dyn.get("clothing"):
        lines.append(f"当前着装：{dyn['clothing']}")
    if dyn.get("action"):
        lines.append(f"当前动作：{dyn['action']}")
    if dyn.get("demeanor"):
        lines.append(f"当前神态：{dyn['demeanor']}")
    return "\n".join(lines)


def _identity_tag(resolved: dict) -> str:
    """First clause of identity_background, or role -- one short label for brief cards."""
    bg = str(resolved.get("identity_background") or "").strip()
    if bg:
        for sep in ("，", ",", "；", ";", "。", "."):
            if sep in bg:
                clause = bg.split(sep, 1)[0].strip()
                if clause:
                    return clause
        return bg if len(bg) <= 48 else bg[:48] + "…"
    return str(resolved.get("role") or "").strip()


def _relationship_link(
    name: str, anchor_names: set[str], graph: dict,
) -> tuple[str, str]:
    """Best (relationship_phrase, bond_anchor) linking `name` to someone in anchor_names."""
    from engine.setup.cast.relationship_graph import iter_edges

    for anchor in sorted(anchor_names):
        if anchor == name:
            continue
        for e in iter_edges(graph):
            if e["from"] == anchor and e["to"] == name:
                terms = e.get("to_ref_terms") or []
                phrase = f"{anchor}的{terms[0]}" if terms else f"{anchor}的{e['nature']}"
                bond = str(e.get("relationship_anchor") or "").strip()
                return phrase, bond
            if e["to"] == anchor and e["from"] == name:
                terms = e.get("from_ref_terms") or []
                phrase = f"{anchor}的{terms[0]}" if terms else f"{anchor}的{e['nature']}"
                bond = str(e.get("relationship_anchor") or "").strip()
                return phrase, bond
    return "", ""


def render_related_character_brief(
    name: str, chapter: int, stage: int, *,
    anchor_names: set[str] | None = None,
    overlay: dict[str, dict] | None = None,
) -> str:
    """Minimal off-stage card: name + identity tag + relationship to an anchor + bond phrase."""
    resolved = resolve_card_state(name, chapter, stage)
    if not resolved:
        return f"【{name}】（无档案，按名字最简扮演）"

    segments: list[str] = []
    identity = _identity_tag(resolved)
    if identity:
        segments.append(identity)

    anchors = anchor_names or set()
    if anchors:
        from engine.setup.cast.relationship_graph import load_graph, merge_overlay

        graph = merge_overlay(load_graph(), overlay or {})
        rel_phrase, bond = _relationship_link(name, anchors, graph)
        if rel_phrase:
            segments.append(rel_phrase)
        if bond:
            segments.append(f"羁绊：{bond}")

    body = "，".join(segments)
    return f"【{name}】{body}" if body else f"【{name}】"
