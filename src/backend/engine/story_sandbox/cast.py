"""Character-card and cast-block rendering helpers for story-sandbox. No longer reads
plot_library stage data at all (see docs/superpowers/specs/2026-08-01-sandbox-opening-grounding-
instruction-only-design.md) -- resolve_character_cards renders persona cards for whichever
names the caller has already resolved (via cast_identify.resolve_present_roster or a
deterministic entity_index.scan_characters(instruction) scan, see graph.py's
_build_init_char_node), not from a plot-outline-derived roster.
Read-only, no writes. Everything past the opening turn free-improvises off written history."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.story_sandbox.state import SandboxState


def resolve_character_cards(chapter: int, names: list[str]) -> list[dict]:
    """Static persona cards for opening-turn grounding and direction-suggest grounding. Runtime
    5-field states are passed separately by the caller -- cards here intentionally omit
    dynamic_state."""
    from engine.author_loop.dialogue_mode.cards import render_character_card

    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return [
        {"name": name, "card": render_character_card(name, chapter, 1, include_persona=True)}
        for name in ordered
    ]


def render_dynamic_cast_block(
    active_cast: dict[str, int], *, chapter: int, exclude: set[str] | None = None,
) -> str:
    """Renders every active_cast member's full persona card (see cast_tracker.py for how
    active_cast is maintained). Chapter mode (chapter > 0) anchors at (chapter, stage=1), the
    same coordinate resolve_character_cards already uses. Free mode (chapter == 0) anchors at
    (chapter=0, stage=0) -- character_timeline.deltas_upto never matches a real chapter's
    snapshots against that coordinate (real chapters are always >= 1), so it resolves to the
    character's pure lore baseline: free mode ignores plot progression by design.

    `exclude` should be non-empty ONLY on a chapter's opening turn, to dedupe against the
    one-shot stage1 cast block prompt.py already renders that turn -- that block never
    reappears on later turns, so passing a non-empty exclude on any other turn would silently
    strip stage1 characters' cards forever, recreating the exact gap this feature closes."""
    from engine.author_loop.dialogue_mode.cards import render_character_card

    exclude = exclude or set()
    names = sorted(n for n in active_cast if n not in exclude)
    if not names:
        return ""
    stage = 1 if chapter > 0 else 0
    cards = [render_character_card(name, chapter, stage, include_persona=True) for name in names]
    return "\n\n## 在场角色档案\n" + "\n\n".join(cards)


def resolve_related_cast(
    present: set[str] | list[str], overlay: dict[str, dict] | None = None,
) -> list[str]:
    """Characters connected via a relationship-graph edge to any confidently-present character
    (relationship_graph.related_to_present) -- background/relationship context, never itself a
    claim that they're on stage. This is the relationship graph's actual intended use in
    story_sandbox: a structured from/to lookup keyed off already-resolved present names, not a
    re-scan of free text for ref_terms (that's exactly the ambiguity entity_index.py::
    scan_characters dropped -- see its docstring). See
    docs/superpowers/specs/2026-07-26-sandbox-present-vs-related-cast-design.md.

    `overlay` is the session-local relationship_overlay state field (see profile_mutate.py) --
    laid over the static base graph via relationship_graph.merge_overlay before resolving, so an
    edge this session itself proposed can surface a related character too, without ever writing
    back to relationship_edges.jsonl."""
    from engine.setup.cast.relationship_graph import load_graph, merge_overlay, related_to_present

    graph = merge_overlay(load_graph(), overlay or {})
    return sorted(related_to_present(graph, set(present)))


def render_related_cast_block(
    names: list[str], *, chapter: int, exclude: set[str] | None = None,
    anchor_names: set[str] | None = None, overlay: dict[str, dict] | None = None,
) -> str:
    """Renders distilled relationship briefs for characters related to whoever's actually
    present, under a header that explicitly forbids the model from giving them dialogue or
    actions. Distinct from render_dynamic_cast_block's "在场角色档案", which the model MAY have
    act/speak -- this block is background-only. `exclude` should be the union of everyone
    already rendered as present (active_cast ∪ opening_names), so a related character never
    double-appears under both headers. When `anchor_names` is omitted, `exclude` is reused as
    the anchor set for relationship phrases."""
    from engine.author_loop.dialogue_mode.cards import render_related_character_brief

    exclude = exclude or set()
    anchors = anchor_names if anchor_names is not None else exclude
    ordered = sorted(n for n in dict.fromkeys(names) if n not in exclude)
    if not ordered:
        return ""
    stage = 1 if chapter > 0 else 0
    cards = [
        render_related_character_brief(
            name, chapter, stage, anchor_names=anchors, overlay=overlay,
        )
        for name in ordered
    ]
    return (
        "\n\n## 相关角色档案（不在场，仅供背景/关系参考——禁止让他们说话、登场或采取任何行动）\n"
        + "\n".join(cards)
    )


def _protagonist_names() -> set[str]:
    from repositories import get_lore_repo

    names: set[str] = set()
    for c in get_lore_repo().list_raw():
        if not isinstance(c, dict):
            continue
        role = str(c.get("role") or "").strip()
        if "主角" in role or role in ("男主", "女主", "男主角", "女主角"):
            name = str(c.get("given_name") or c.get("name") or "").strip()
            if name:
                names.add(name)
    return names


_FAMILY_CUES = ("一家", "家人", "家庭", "亲属", "亲人", "全家")


def resolve_instruction_grounding_names(instruction: str) -> set[str]:
    """Infer a character subset from group/social-network cues when the instruction names nobody.

    Used alongside known_roster_fallback: the full roster guardrail stays, but when the
    instruction mentions e.g. "主角一家" we also surface that group's members + their edges."""
    from engine.memory_recall.entity_index import scan_characters
    from engine.setup.cast.relationship_graph import (
        iter_edges,
        iter_groups,
        load_graph,
        related_to_present,
    )

    text = (instruction or "").strip()
    if not text:
        return set()

    graph = load_graph()
    seeds: set[str] = set(scan_characters(text))
    protagonists = _protagonist_names()

    if "主角" in text:
        seeds.update(protagonists)

    for proto in protagonists:
        if proto in text:
            seeds.add(proto)

    for g in iter_groups(graph):
        gtype = str(g.get("type") or "").strip()
        if gtype and gtype in text:
            seeds.update(str(m).strip() for m in g.get("members") or [] if str(m).strip())

    if any(cue in text for cue in _FAMILY_CUES) and ("主角" in text or protagonists & seeds):
        for g in iter_groups(graph):
            members = {str(m).strip() for m in g.get("members") or [] if str(m).strip()}
            if members & protagonists:
                seeds.update(members)

    for e in iter_edges(graph):
        for term in e.get("from_ref_terms") or []:
            if term in text:
                seeds.update({e["from"], e["to"]})
        for term in e.get("to_ref_terms") or []:
            if term in text:
                seeds.update({e["from"], e["to"]})

    if not seeds:
        return set()

    expanded = set(seeds)
    expanded.update(related_to_present(graph, seeds))
    for g in iter_groups(graph):
        members = {str(m).strip() for m in g.get("members") or [] if str(m).strip()}
        if members & seeds:
            expanded.update(members)
    return expanded


def render_instruction_grounding_blocks(
    instruction: str, *, chapter: int,
) -> tuple[str, str]:
    """Relationship subgraph + distilled briefs for instruction-only opening grounding."""
    names = sorted(resolve_instruction_grounding_names(instruction))
    if not names:
        return "", ""

    from engine.author_loop.dialogue_mode.cards import render_related_character_brief
    from engine.setup.cast.relationship_graph import load_graph, render_overview

    graph_block = render_overview(load_graph(), names)
    stage = 1 if chapter > 0 else 0
    anchor_set = set(names)
    briefs = [
        render_related_character_brief(name, chapter, stage, anchor_names=anchor_set)
        for name in names
    ]
    briefs_block = (
        "\n\n## 关联角色简卡（指令相关，仅供背景/关系参考——禁止让他们说话、登场或采取任何行动）\n"
        + "\n".join(briefs)
    )
    return graph_block, briefs_block


async def resolve_active_cast_archives(
    chapter: int, names: list[str], novel_id: str, *, state: SandboxState | None = None,
) -> list[dict]:
    """Baseline archive (lore + character_timeline at (chapter, stage)) with the sandbox
    session's own confirmed character_profile overlay (see profile_mutate.py) merged on top --
    a display-only "quick override", never written back to archive.json/character_timeline.
    `state` lets a caller that already read peek_state (e.g. resolve_related_cast_archives)
    pass it through instead of triggering a second checkpointer read."""
    if not names:
        return []

    from engine.archive.archive_view import render_character_profile
    from engine.author_loop.dialogue_mode.chapter_state import resolve_card_state
    from engine.story_sandbox.graph import peek_state
    from engine.story_sandbox.profile_mutate import merge_profile_fields

    if state is None:
        state = await peek_state(novel_id, chapter)
    overlay = state.get("character_profile") or {}
    stage = 1 if chapter > 0 else 0
    out: list[dict] = []
    for name in sorted(names):
        arc = resolve_card_state(name, chapter, stage)
        if not arc:
            continue
        fields = overlay.get(name)
        if fields:
            arc = merge_profile_fields(arc, fields)
        out.append(render_character_profile(name, arc))
    return out


async def resolve_related_cast_archives(
    chapter: int, present: list[str], novel_id: str,
) -> list[dict]:
    """相关角色面板 tab 用：relationship_graph 边关联到 present 里任一在场角色、但自己不在
    present 里的背景角色的 CharacterArchive 形状卡片，供沙盒右侧面板只读展示。present 为空
    （尚未有人登场）时直接返回空列表，不解析关系图。overlay 复用与 render_related_cast_block
    相同的 relationship_overlay 会话态（见 resolve_related_cast 文档），保证面板展示和 LLM
    prompt 看到的"相关角色"是同一份名单。"""
    if not present:
        return []
    from engine.story_sandbox.graph import peek_state

    state = await peek_state(novel_id, chapter)
    overlay = state.get("relationship_overlay") or {}
    related = resolve_related_cast(set(present), overlay)
    return await resolve_active_cast_archives(chapter, related, novel_id, state=state)
