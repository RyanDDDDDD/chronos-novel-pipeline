"""Relevant-context recall for story_sandbox: merges keyword/entity substring matches with
semantic similarity hits over previously archived event fragments, plus static world lore,
formatted for prompt injection. Keyword scanning covers both this turn's instruction and the
previous round's already-written prose (so a terse "继续" doesn't blind the keyword path even
when the prior prose is dense with named entities). Recalled items (dynamic event-log entries
and static world entries alike) are subject to a per-chapter cooldown so the same setting isn't
re-injected every single turn. Semantic hits are additionally gated on active_cast (see
cast_tracker.py) so an embedding match built on shared vocabulary alone can't drag in named
characters absent from the current scene. See
docs/superpowers/specs/2026-07-15-story-sandbox-recall-scan-scale-cooldown-design.md and
docs/superpowers/specs/2026-07-14-story-sandbox-vector-memory-recall-design.md (prior design,
covers the semantic-query half, unchanged here). recall_relevant_context's third return value
(recalled_settings) is a structured subset of the rendered text -- just the world-bible named
entries that matched this call, for the frontend to highlight separately from event history. See
docs/superpowers/specs/2026-07-25-sandbox-recalled-settings-bubble-design.md."""
from __future__ import annotations

_RECALL_HEADER = (
    "## 相关历史/设定回收\n"
    "以下是本章之外已经发生的既定事实：写到相关角色或情境时要与之保持一致，不得凭空写出矛盾内容；"
    "和当前这段无关的条目不必强行呼应。"
)
_WORLD_NAMED_LISTS = ("factions", "geography", "races", "power_system", "core_themes")
_KEYWORD_GATED_LISTS = ("power_system", "core_themes")
_BARE_MATCH_LISTS = ("factions", "geography", "races")
COOLDOWN_TURNS = 10


def _format_recall_line(e: dict) -> str:
    """Renders all four elements (event/time/location/characters) when present -- time/location
    are folded into the bracketed header alongside the chapter number, characters appended as a
    trailing parenthetical; either half degrades cleanly to nothing when the entry lacks it."""
    chapter = e.get("chapter", "?")
    time = str(e.get("time") or "").strip()
    location = str(e.get("location") or "").strip()
    summary = e.get("summary", "")
    characters = e.get("characters") or []
    header_bits = [f"第{chapter}章"]
    if time:
        header_bits.append(time)
    if location:
        header_bits.append(f"于{location}")
    line = f"- [{'，'.join(header_bits)}] {summary}"
    if characters:
        line += f"（人物：{'、'.join(characters)}）"
    return line


def _cooldown_key(kind: str, ident: str) -> str:
    """Namespaced cooldown key -- 'event:<id>' for event_log/vector entries (uuid, already
    globally unique) and 'world:<category>:<name>' for static bible entries (name alone isn't
    guaranteed unique across factions/geography/races)."""
    return f"{kind}:{ident}"


def recall_relevant_context(
    text: str, *, chapter: int, origin: str, branch_id: str | None = None, max_items: int = 5,
    prior_prose: str = "", turn_index: int = 0, cooldown: dict[str, int] | None = None,
    active_cast: dict[str, int] | None = None, cooldown_turns: int = COOLDOWN_TURNS,
) -> tuple[str, dict[str, int], list[dict]]:
    from repositories import get_sandbox_vector_memory_repo
    from repositories.entities import MemoryOrigin

    from engine.memory_recall.entity_index import scan_entities
    from engine.memory_recall.event_log import entries_in_scope, load_event_log

    cooldown = cooldown or {}
    hits = set(scan_entities(text)) | set(scan_entities(prior_prose))
    onstage = hits | set(active_cast or {})

    entries = load_event_log().get("entries") or []
    scoped = entries_in_scope(entries, chapter, branch_id, origin)
    dynamic_by_id: dict[str, dict] = {
        e["id"]: e for e in scoped if hits.intersection(e.get("entities") or [])
    }

    semantic_hits = get_sandbox_vector_memory_repo().query(text, top_k=max_items)
    for hit in semantic_hits:
        if not hit.id or hit.chapter > chapter:
            continue
        if branch_id is not None and hit.branch_id not in ("", branch_id):
            continue
        if (hit.origin or MemoryOrigin.SANDBOX) != origin:
            continue
        # Embedding similarity alone can't tell "same scene, reworded" apart from "different
        # scene, same explicit vocabulary" -- a hit naming characters who are none of this turn's
        # keyword hits and none of the current active cast is almost always the latter. Entries
        # with no characters recorded make no claim to gate on, so they pass through untouched.
        if hit.characters and not onstage.intersection(hit.characters):
            continue
        dynamic_by_id.setdefault(hit.id, hit.model_dump())

    dynamic_sorted = sorted(
        dynamic_by_id.values(),
        key=lambda e: (e.get("chapter", 0), e.get("turn_index", 0)),
        reverse=True,
    )

    lines: list[str] = []
    recalled_settings: list[dict] = []
    updated_cooldown = dict(cooldown)
    for e in dynamic_sorted:
        if len(lines) >= max_items:
            break
        key = _cooldown_key("event", e["id"])
        if turn_index - cooldown.get(key, -cooldown_turns) < cooldown_turns:
            continue
        lines.append(_format_recall_line(e))
        updated_cooldown[key] = turn_index

    from repositories import get_world_repo

    try:
        bible = get_world_repo().get() or {}
    except OSError:
        bible = {}

    full_scan_text = f"{text}\n{prior_prose}"

    def _emit(category: str, name: str, desc: str) -> None:
        key = _cooldown_key("world", f"{category}:{name}")
        if turn_index - cooldown.get(key, -cooldown_turns) < cooldown_turns:
            return
        lines.append(f"- 【{name}】{desc}")
        updated_cooldown[key] = turn_index
        recalled_settings.append({"category": category, "name": name, "desc": desc})

    if hits:
        for category in _BARE_MATCH_LISTS:
            for item in bible.get(category) or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if name and name in hits:
                    _emit(category, name, str(item.get("desc", "")))

    # power_system/core_themes run unconditionally (not gated by `hits`) -- a keywords-only match
    # (e.g. "信仰丧失" recalled via "神像崩塌") must surface even when nothing else was recognized.
    for category in _KEYWORD_GATED_LISTS:
        for item in bible.get(category) or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            keywords = [str(k).strip() for k in (item.get("keywords") or []) if str(k).strip()]
            if keywords:
                # Once an entry opts into keywords, bare name alone no longer unconditionally
                # confirms -- see
                # docs/superpowers/specs/2026-08-11-power-system-core-themes-recall-automaton-v2-design.md.
                # Strong (>=3 chars) keywords confirm alone. Weak (2-char) keywords need >=2
                # distinct weak hits, or the bare name plus 1 weak hit. All three checks are
                # plain full_scan_text substring tests, deliberately NOT `hits` (the automaton
                # set) -- a weak keyword registered as an automaton alias would put `name` into
                # `hits` via its own match, letting a single weak keyword self-confirm through
                # the name+weak path.
                strong_kw = [kw for kw in keywords if len(kw) >= 3]
                weak_kw = [kw for kw in keywords if len(kw) == 2]
                weak_hits = {kw for kw in weak_kw if kw in full_scan_text}
                name_hit = name in full_scan_text
                confirmed = (
                    any(kw in full_scan_text for kw in strong_kw)
                    or len(weak_hits) >= 2
                    or (name_hit and bool(weak_hits))
                )
            elif category == "power_system":
                confirmed = name in hits  # unchanged legacy behavior
            else:
                confirmed = False  # core_themes without keywords stays excluded (safe default)
            if confirmed:
                _emit(category, name, str(item.get("desc", "")))

    if not lines:
        return "", updated_cooldown, recalled_settings
    return _RECALL_HEADER + "\n" + "\n".join(lines), updated_cooldown, recalled_settings
