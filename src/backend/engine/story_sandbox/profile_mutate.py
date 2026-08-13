"""Sparse, event-gated character-profile mutation for story-sandbox: sliders/physique/gender/
race/personality/identity_background/hobbies/verbal_tic -- fields frozen at session-open by
cast.py's static character-card resolution, given a mid-session evolution path (transformation/
curse/gender-swap/species-change/identity-reveal events). Session-local only: the result lives in
SandboxState.character_profile, persisted by the checkpointer, NEVER written to
character_timeline/archive.json. The merge into character_profile itself is deferred by one round
(see _commit_previous_round), mirroring event_log.py's _archive_previous_round, so a rewrite of
the round that produced a mutation can still supersede it before it's ever committed.

Gated on event_log's own "did anything happen this turn" determination
(event_log_entry_this_turn) -- this node only calls an LLM when that's non-empty, and even then
usually reports nothing (most events don't touch profile-level fields). Validation mirrors
write_character_archive's recipe (whitelist filter + slider shape/rubric-legality) but stays in
story_sandbox's existing "system/user -> text -> JSON parse" node style, not a bound LangChain
tool -- no other node in this module uses tool-calling and this one turn doesn't need the
reject-and-reprompt round trip a real tool call would enable.

Unlike derive_character_states/derive_scene_state (call_llm_with_retry, raises
DerivationValidationError and aborts the turn after exhausting retries), failures here are soft:
log and report no mutation this turn. This node is already conditionally skipped most turns; a
parse failure on the rare turn it does run should not hold up the whole turn.

_render_user shows present characters (active_cast) their full baseline+overlay profile, not
just the sparse session-local overlay -- see _resolve_baseline_profile's docstring for why: a
field like physique already has an established set of body-part keys in the character's real
archive, and the LLM can only report an incremental update using those SAME keys if it can see
them. Showing only the overlay (which starts empty and may never have touched physique this
session) leaves the LLM inventing its own key names instead, fragmenting the profile."""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from engine.archive.sliders import (
    character_rubrics,
    render_slider,
    valid_levels,
    valid_slider_value_shape,
)
from engine.story_sandbox.llm_json import extract_json_dict
from engine.story_sandbox.state import SandboxState

CallLLM = Callable[[str, str], Awaitable[str]]
GuardText = Callable[[str], Awaitable[str]]

_FORCE_INTERVAL = 10  # 每隔这么多轮，无视 event_log 的"没事"判断，强制跑一次本节点的判断

_ALLOWED_PROFILE_FIELDS = frozenset({
    "sliders", "physique", "gender", "race",
    "personality", "identity_background", "hobbies", "verbal_tic",
})

# Short enum/scalar fields from normalize — not free narrative text (design §3).
_SKIP_GUARD_TEXT_KEYS = frozenset({"gender", "race"})


def _recall_block_section(recall_block: str) -> str:
    """recall_block already carries its own "## 相关历史/设定回收" header (see
    memory_recall.recall.recall_relevant_context) -- just gate on emptiness and prepend a
    separating blank line, no extra header needed here."""
    text = (recall_block or "").strip()
    return f"\n\n{text}" if text else ""


_MUTATE_SYS = (
    "根据这段新写的正文，判断是否有角色的档案资料发生了实质性变化（不是心理/体态/着装/动作/神态这类"
    "每轮都可能变的状态，而是更底层的：性格 personality／身份背景 identity_background（含年龄，尤其是"
    "较大幅度时间跳跃导致的年龄增长）／种族 race／性别 gender／体貌异化 physique／关系进展 sliders／"
    "爱好 hobbies／口癖 verbal_tic）。"
    "user 消息里会给出每个角色目前已确认的档案信息（可能为空）——只有这段新正文相比这份已确认信息"
    "进一步发生变化时才算数，正文只是重申/呼应已确认信息里已经写明的设定，不算变化。"
    "绝大多数情况下都不会有——只有真正发生了变身/诅咒/身份揭露/种族转换/人格剧变这类重大事件，或者"
    "已确认信息里写明过角色年龄、新正文又明确交代了时间跨度（如“十年后”“又过了三年”）导致实际年龄"
    "变化时，才报告。若已确认信息里从未写明过年龄，这段正文才提到年龄，也可以据此把年龄补进"
    "identity_background；年龄变化按新年龄改写 identity_background 里的年龄表述，其余内容尽量保持不变。"
    "只输出这段正文里确实发生了这类变化的角色，每个角色只列出真正变了的字段，没变的字段和没变的角色"
    "完全不要提及。没有任何角色发生这类变化时，输出空对象 {}。"
    '只输出 JSON，形如 {"角色名": {"physique": {...}, "sliders": {...}, ...}}，'
    "sliders 每轴须给 {level: 合法档位号, text: 贴合此刻的一句叙述}。"
    "输出的角色名必须且只能来自 user 消息里给出的「这轮在场正式角色」列表——不得输出路人、背景角色"
    "或设定卡外的任何名字。\n\n"
    "另外，user 消息里也会给出在场正式角色之间已知的关系（可能为空）——如果这段正文明确揭示了在场"
    "正式角色之间一条全新的社交关系事实，或让已有一条关系发生了实质性变化（比如从疏远盟友变成反目、"
    "从陌生人变成结拜），就在同一个 JSON 对象里额外加一个 \"$relationships\" 键，值是边数组，每条边"
    '形如 {"from": "...", "to": "...", "nature": "...", "relationship_anchor": "...", '
    '"from_ref_terms": [], "to_ref_terms": []}——from/to 必须都是这轮在场正式角色列表里的名字，'
    "不能是路人/背景角色或其他人；nature 写关系性质，不能为空；relationship_anchor 写 from 对 to 的情结短句，无则空串；"
    "from_ref_terms/to_ref_terms 是这段关系里区别于本名的第三人称称呼，没有就留空数组。只是重申/呼应"
    "已知关系不算变化，绝大多数情况下都没有变化，没有就不要输出这个键。"
    "不要输出任何 JSON 以外的文字。"
)

_FEEDBACK_SYS_SUFFIX = (
    "若用户给出了【对于本次档案突变/关系变更的明确指导意见】：{feedback}，"
    "请在当前已确认突变的基础上结合这项指导进行针对性修订，并将其体现在输出的 JSON 结果中。"
)

_DIRECTED_REWRITE_SYS_SUFFIX = (
    "这是一次对「本轮已产出档案/关系突变」的定向重写，不是从正文首次推断。"
    "user 消息里会附带「本轮当前已确认的档案突变」与「关系突变」——请以此为底稿进行修订，"
    "输出修订后的完整 JSON（角色字段 + 可选 $relationships），不要只输出 diff。"
    "若用户要求删除某条突变，从结果中 omit；若用户要求修改，覆盖对应字段。"
)


def _mutate_sys(feedback: str | None = None, *, directed_rewrite: bool = False) -> str:
    parts = [_MUTATE_SYS]
    if directed_rewrite:
        parts.append(_DIRECTED_REWRITE_SYS_SUFFIX)
    if feedback:
        parts.append(_FEEDBACK_SYS_SUFFIX.format(feedback=feedback))
    return "\n\n".join(parts)


def _format_relationship_mutation_for_llm(rel: dict[str, dict] | None) -> list[dict]:
    if not rel:
        return []
    return [dict(edge) for edge in rel.values()]


def _render_rewrite_source_block(state: SandboxState) -> str:
    """Current round's profile/relationship mutation -- shown only on directed rewrite so the
    LLM revises an existing result instead of inferring from scratch."""
    if not state.get("profile_mutate_directed_rewrite"):
        return ""
    turns = state.get("turns") or []
    if not turns:
        return ""
    last = turns[-1]
    profile = last.get("profile_mutation") or {}
    relationships = _format_relationship_mutation_for_llm(last.get("relationship_mutation"))
    return (
        f"\n\n本轮当前已确认的档案突变：{json.dumps(profile, ensure_ascii=False)}"
        f"\n\n本轮当前已确认的关系突变：{json.dumps(relationships, ensure_ascii=False)}"
    )


def _resolve_baseline_profile(name: str, chapter: int) -> dict[str, Any]:
    """Session-open baseline for one character: lore + archive folded at (chapter, stage=1) --
    the same coordinate cast.py's static character-card resolution uses. Filtered to
    _ALLOWED_PROFILE_FIELDS and normalized to profile_mutate's own {level, text} slider shape,
    purely as read-only comparison context for the LLM -- never written back (character_profile
    stays the only persisted overlay). Empty dict when the character has no lore record at all.

    Showing this baseline (not just the session-local overlay) is what lets the LLM report an
    incremental change using the ALREADY-ESTABLISHED field names -- e.g. physique's existing
    body-part keys (体型/肌肤/面部/...) -- instead of inventing its own naming scheme for
    whatever it wants to update, which produces a fragmented profile that doesn't match the
    character's real archive format."""
    from context.personality import resolved_personality

    from engine.author_loop.dialogue_mode.chapter_state import resolve_card_state

    resolved = resolve_card_state(name, chapter, 1)
    if not resolved:
        return {}
    out: dict[str, Any] = {}
    personality = resolved_personality(resolved)
    if personality:
        out["personality"] = personality
    for key in ("gender", "race", "identity_background", "verbal_tic"):
        val = str(resolved.get(key) or "").strip()
        if val:
            out[key] = val
    physique = resolved.get("physique")
    if isinstance(physique, dict) and physique:
        out["physique"] = physique
    hobbies = resolved.get("hobbies")
    if isinstance(hobbies, list) and hobbies:
        out["hobbies"] = list(hobbies)
    sliders = resolved.get("sliders")
    if isinstance(sliders, dict) and sliders:
        rubrics = character_rubrics(name)
        rendered: dict[str, Any] = {}
        for axis, val in sliders.items():
            if isinstance(val, dict) and "level" in val and "text" in val:
                rendered[axis] = {"level": val["level"], "text": str(val["text"])}
            elif isinstance(val, int):
                rendered[axis] = {"level": val, "text": render_slider(rubrics, axis, val)}
        if rendered:
            out["sliders"] = rendered
    return out


def _present_formal_cast(state: SandboxState) -> set[str]:
    """active_cast members that are lore-registered formal characters (not passerby)."""
    active = set(state.get("active_cast") or {})
    passerby = set(state.get("passerby_names") or [])
    return active - passerby


def _render_relationship_context(state: SandboxState, present: list[str]) -> str:
    """Current relationship-graph truth among this turn's present characters (static base graph
    + this session's own already-committed relationship_overlay, see relationship_graph.
    merge_overlay) -- shown so the LLM can tell "reaffirms a known relationship" (not a change)
    apart from a genuinely new/changed one, same rationale as _resolve_baseline_profile showing
    the profile baseline. "" when nothing's known among present characters -- never an LLM call
    on its own, purely local graph rendering."""
    from engine.setup.cast.relationship_graph import load_graph, merge_overlay, render_overview

    graph = merge_overlay(load_graph(), state.get("relationship_overlay") or {})
    overview = render_overview(graph, present)
    return f"\n\n{overview}" if overview else ""


def _render_user(state: SandboxState, chapter: int) -> str:
    """Formal present cast (_present_formal_cast: active_cast minus passerby_names) drives
    whether the LLM sees each character's full baseline+overlay profile and the roster hint --
    see _resolve_baseline_profile's docstring for why the baseline matters. Falls back to
    overlay-only when no formal characters are on stage (including when active_cast is empty
    or contains only passerby); relationship context is skipped in those fallback cases since
    edge from/to are validated against the same formal-present set in build_profile_mutate_node."""
    overlay = state.get("character_profile") or {}
    formal_present = sorted(_present_formal_cast(state))
    if formal_present:
        merged: dict[str, dict] = {}
        for name in formal_present:
            view = {**_resolve_baseline_profile(name, chapter), **(overlay.get(name) or {})}
            if view:
                merged[name] = view
        profile_block = (
            json.dumps(merged, ensure_ascii=False) if merged else "（暂无档案信息）"
        )
        roster_hint = (
            f"这轮在场正式角色（档案突变只允许这些角色，角色名请严格用这个写法）："
            f"{'、'.join(formal_present)}\n\n"
        )
        label = "角色现在的完整档案（基线设定 + 此前已确认的演变）"
        relationship_block = _render_relationship_context(state, formal_present)
    else:
        active = state.get("active_cast") or {}
        if active:
            roster_hint = (
                "这轮在场正式角色：无（仅有路人/背景角色在场，不得输出任何角色档案突变或关系突变）\n\n"
            )
            profile_block = "（暂无正式角色档案信息）"
            label = "角色档案"
            relationship_block = ""
        else:
            profile_block = (
                json.dumps(overlay, ensure_ascii=False) if overlay else "（暂无既有突变记录）"
            )
            roster_hint = ""
            label = "角色此前的档案突变记录"
            relationship_block = ""
    feedback = (state.get("profile_mutate_feedback") or "").strip()
    feedback_block = (
        f"\n\n【用户指导意见】：{feedback}" if feedback else ""
    )
    rewrite_source_block = _render_rewrite_source_block(state)
    recall_block = _recall_block_section(state.get("recall_context_this_turn") or "")
    return (
        f"{roster_hint}{label}：{profile_block}{relationship_block}"
        f"{rewrite_source_block}{feedback_block}{recall_block}\n\n新正文：{state['final_text']}"
    )


def _normalize_profile_delta(name: str, fields: dict[str, Any], rubrics: dict) -> dict[str, Any]:
    """Whitelist-filters one character's reported fields; sliders get shape + per-axis rubric-
    legality checks (illegal axis dropped individually, not the whole field). Mirrors
    setup_chat/tools.py::_normalize_delta's recipe, kept as an independent copy since sandbox's
    field set and failure posture (soft-skip, no reject-and-reprompt) differ from that tool's."""
    out: dict[str, Any] = {}
    for key, val in fields.items():
        if key not in _ALLOWED_PROFILE_FIELDS:
            continue
        if key == "sliders":
            if not valid_slider_value_shape(val):
                continue
            kept = {}
            for axis, axis_val in val.items():
                if rubrics:
                    if axis not in rubrics:
                        continue
                    legal = valid_levels(rubrics, axis)
                    level = axis_val.get("level")
                    if legal and level is not None and int(level) not in legal:
                        continue
                kept[axis] = axis_val
            if kept:
                out["sliders"] = kept
        elif key == "hobbies":
            if isinstance(val, list):
                cleaned = [str(x).strip() for x in val if str(x).strip()]
                if cleaned:
                    out["hobbies"] = cleaned
        else:
            out[key] = val
    return out


async def _guard_profile_fields(fields: dict[str, Any], guard_text: GuardText) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in fields.items():
        if key == "sliders" and isinstance(val, dict):
            out[key] = {
                axis: {**axis_val, "text": await guard_text(axis_val["text"])}
                if isinstance(axis_val, dict) and isinstance(axis_val.get("text"), str) and axis_val["text"]
                else axis_val
                for axis, axis_val in val.items()
            }
        elif key == "hobbies" and isinstance(val, list):
            out[key] = [
                await guard_text(item) if isinstance(item, str) and item else item for item in val
            ]
        elif key == "physique" and isinstance(val, dict):
            out[key] = {
                slot: await guard_text(slot_val) if isinstance(slot_val, str) and slot_val else slot_val
                for slot, slot_val in val.items()
            }
        elif key in _SKIP_GUARD_TEXT_KEYS:
            out[key] = val
        elif isinstance(val, str) and val:
            out[key] = await guard_text(val)
        else:
            out[key] = val
    return out


def merge_profile_fields(base: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    """Layers one profile_mutate delta onto an existing profile dict: sliders/physique merge
    per sub-key (axis/slot), hobbies merges as a de-duplicated union of items, so a delta
    touching only SOME axes/slots/hobbies doesn't blow away others already accumulated there;
    every other (scalar) field replaces wholesale (a reported field is always the character's
    full new value for that field, per profile_mutate.py's write-time contract). Shared by
    _commit_previous_round (accumulating across rounds into character_profile) and
    cast.py::resolve_active_cast_archives (laying the accumulated overlay onto a resolved
    baseline archive for display) -- both need the identical sub-item-aware semantics, since a
    flat top-level merge would silently drop earlier axes/slots/hobbies the moment a later delta
    re-touches the same field without repeating them (profile_mutate's prompt only asks the LLM
    for what actually changed, not a full restatement of everything already known)."""
    merged = dict(base)
    for key, val in fields.items():
        if key in ("sliders", "physique") and isinstance(val, dict):
            merged[key] = {**(merged.get(key) or {}), **val}
        elif key == "hobbies" and isinstance(val, list):
            existing = merged.get(key) or []
            merged[key] = list(existing) + [item for item in val if item not in existing]
        else:
            merged[key] = val
    return merged


def _commit_previous_round(state: SandboxState) -> dict[str, dict] | None:
    """Merges the PREVIOUS round's profile_mutation into the confirmed character_profile
    overlay -- deferred until now (this, a fresh non-rewrite turn) rather than at the moment
    that round was created, mirroring event_log.py::_archive_previous_round: rewrite_last_round
    can only ever rewrite turns[-1], so by the time a fresh turn's profile_mutate node is
    running, the previous round has already been superseded and can never be rewritten again --
    its own profile_mutation (whatever a rewrite may have last replaced it with) is now
    permanently safe to fold into the confirmed overlay. Returns None (no state update) when
    there's no previous round or it produced no mutation, so the caller can skip touching
    character_profile at all on the common no-op path."""
    turns = state.get("turns") or []
    if not turns:
        return None
    prev_mutation = turns[-1].get("profile_mutation")
    if not prev_mutation:
        return None
    merged = dict(state.get("character_profile") or {})
    for name, fields in prev_mutation.items():
        merged[name] = merge_profile_fields(merged.get(name, {}), fields)
    return merged


def _commit_previous_round_relationships(state: SandboxState) -> dict[str, dict] | None:
    """relationship_overlay's sibling of _commit_previous_round -- same deferred-by-one-round
    lifecycle (a rewrite of the round that produced a relationship_mutation can still supersede
    it before it's ever folded into the confirmed overlay), same "None -> caller skips touching
    the key at all" contract."""
    turns = state.get("turns") or []
    if not turns:
        return None
    prev_mutation = turns[-1].get("relationship_mutation")
    if not prev_mutation:
        return None
    merged = dict(state.get("relationship_overlay") or {})
    merged.update(prev_mutation)
    return merged


def _extract_relationship_edges(parsed: dict[str, Any], present: set[str]) -> dict[str, dict]:
    """Pops the reserved "$relationships" key out of profile_mutate's flat per-character-name
    response dict (kept alongside those keys, not nested, so an unparsed/older response with no
    relationships at all is still a plain {"角色名": {...}} dict -- no wrapper-shape migration
    needed for the existing profile-mutation contract). Each candidate edge is validated via
    relationship_graph.validate_edge against `present` (this turn's active_cast) -- from/to must
    both be present characters, never a name resolve_related_cast's scope-guard would otherwise
    have to filter back out later (see the present-vs-related cast redesign this mirrors).
    Returns {"from→to": edge}, ready to merge into relationship_mutation_this_turn / overlay."""
    from engine.setup.cast.relationship_graph import clean_ref_terms, validate_edge

    raw = parsed.pop("$relationships", None)
    if not isinstance(raw, list):
        return {}
    out: dict[str, dict] = {}
    for edge in raw:
        if not isinstance(edge, dict):
            continue
        errs = validate_edge(edge, present)
        if errs:
            logger.warning(
                "[story_sandbox] profile_mutate 关系边校验未过，丢弃：{}", "；".join(errs),
            )
            continue
        frm = str(edge.get("from", "")).strip()
        to = str(edge.get("to", "")).strip()
        out[f"{frm}→{to}"] = {
            "from": frm, "to": to,
            "nature": str(edge.get("nature", "")).strip(),
            "relationship_anchor": str(edge.get("relationship_anchor", "")).strip(),
            "from_ref_terms": clean_ref_terms(edge.get("from_ref_terms")),
            "to_ref_terms": clean_ref_terms(edge.get("to_ref_terms")),
        }
    return out


async def _guard_relationship_edges(
    edges: dict[str, dict], guard_text: GuardText,
) -> dict[str, dict]:
    """Same soft style-guard treatment _guard_profile_fields gives free narrative text --
    relationship_anchor is the only free-prose field here (nature is a short label, ref_terms are
    bare address words, neither is narrative text worth guarding)."""
    out: dict[str, dict] = {}
    for key, edge in edges.items():
        anchor = edge.get("relationship_anchor")
        out[key] = (
            {**edge, "relationship_anchor": await guard_text(anchor)} if anchor else edge
        )
    return out


def build_profile_mutate_node(
    chapter: int,
    call_llm_profile_mutate: CallLLM,
    guard_text: GuardText,
    *,
    is_rewrite: bool = False,
):
    """LangGraph node factory: downstream of event_log (not a fan-out sibling) -- only runs its
    LLM call when event_log_entry_this_turn is non-empty, EXCEPT every _FORCE_INTERVAL-th round,
    which forces the call regardless. event_log_entry_this_turn comes from a separate upstream
    LLM judgment ("did anything event-worthy happen this round") -- a wrong "nothing happened"
    there silently starves this node of any chance to look at the round's text at all, so the
    periodic override exists purely to bypass that upstream gate on a fixed cadence; it reuses
    the exact same narrow per-round prompt/judgment below, not a wider retrospective look.
    is_rewrite mirrors _build_derive_char_node's own flag: a rewrite replaces turns[-1] in place
    rather than appending a new round, so its round number is len(turns), not len(turns) + 1."""
    async def _n(state: SandboxState) -> dict:
        commit: dict[str, Any] = {}
        if not is_rewrite:
            committed = _commit_previous_round(state)
            if committed is not None:
                commit["character_profile"] = committed
            committed_relationships = _commit_previous_round_relationships(state)
            if committed_relationships is not None:
                commit["relationship_overlay"] = committed_relationships

        turns_len = len(state.get("turns") or [])
        round_number = (turns_len - 1 if is_rewrite else turns_len) + 1
        forced = round_number % _FORCE_INTERVAL == 0
        feedback = (state.get("profile_mutate_feedback") or "").strip()
        directed = state.get("profile_mutate_directed_rewrite")
        if not forced and not feedback and not directed and not state.get("event_log_entries_this_turn"):
            return {**commit, "profile_mutation_this_turn": None, "relationship_mutation_this_turn": None}
        raw = await call_llm_profile_mutate(
            _mutate_sys(feedback or None, directed_rewrite=bool(directed)),
            _render_user(state, chapter),
        )
        parsed = extract_json_dict(raw)
        if parsed is None:
            logger.warning("[story_sandbox] profile_mutate unparseable, raw={!r}", raw[:300])
            return {**commit, "profile_mutation_this_turn": None, "relationship_mutation_this_turn": None}

        eligible = _present_formal_cast(state)
        edges = _extract_relationship_edges(parsed, eligible)
        relationship_mutation = (
            await _guard_relationship_edges(edges, guard_text) if edges else None
        )

        mutated: dict[str, dict] = {}
        for name, fields in parsed.items():
            if not isinstance(fields, dict):
                continue
            if name not in eligible:
                logger.warning(
                    "[story_sandbox] profile_mutate 丢弃非在场正式角色的档案突变：{}", name,
                )
                continue
            rubrics = character_rubrics(str(name))
            normalized = _normalize_profile_delta(str(name), fields, rubrics)
            if normalized:
                mutated[str(name)] = normalized

        if not mutated:
            return {
                **commit, "profile_mutation_this_turn": None,
                "relationship_mutation_this_turn": relationship_mutation,
            }

        guarded: dict[str, dict] = {}
        for name, fields in mutated.items():
            guarded[name] = await _guard_profile_fields(fields, guard_text)
        mutated = guarded

        return {
            **commit, "profile_mutation_this_turn": mutated,
            "relationship_mutation_this_turn": relationship_mutation,
        }
    return _n
