"""Story-sandbox turn graph: a linear per-turn chain (prose -> derive_state -> suggest) that
composes the dynamic packet, writes prose, guards it, derives character-state updates, and
folds the aged-out round into the rolling summary. LangGraph's StateGraph is used for
checkpointed-state persistence and per-node streaming via astream(stream_mode="updates") --
there is no branching/loop behavior here.

The graph never imports an LLM client or touches a websocket: write_turn/call_llm are injected
Protocol-typed callables, mirroring author_loop's AuthorTurns/CallLLM protocol split. The real
implementations (streaming + broadcasting, and a plain non-streaming call respectively) live in
message_hub.py, exactly where author_loop's equivalent streaming code lives today."""
from __future__ import annotations

import asyncio
import os
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Protocol, cast

from langgraph.graph import END, START, StateGraph
from repositories import get_sandbox_vector_memory_repo
from repositories.entities import MemoryOrigin
from utils.timer import sandbox_step_timer

from engine.memory_recall.event_log import (
    build_event_extract_node,
    build_event_extract_rewrite_node,
    build_summary_fold_node,
    build_summary_fold_rewrite_node,
    delete_entries_for_chapter,
    round_event_log_entries,
)
from engine.story_sandbox.direction_suggest import suggest_directions
from engine.story_sandbox.profile_mutate import build_profile_mutate_node
from engine.story_sandbox.scene_derive import derive_initial_scene_state, derive_scene_state
from engine.story_sandbox.skill_suggest import RunSkillAgent, parse_skill_hint, run_skill_suggestion
from engine.story_sandbox.state import (
    LEGACY_BRANCH_ID,
    CharacterState,
    Round,
    SandboxState,
    SandboxStepType,
    SceneState,
)
from engine.story_sandbox.state_derive import derive_character_states, derive_initial_states
from engine.story_sandbox.turn_packet import render_turn_packet

_checkpointers: dict[str, Any] = {}  # novel_id -> AsyncSqliteSaver connection, lazy-opened
_checkpointers_building: dict[str, Any] = {}  # novel_id -> asyncio.Task, in-flight build guard
_pending_cleanup_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]


def _thread_id(novel_id: str, chapter: int, branch_id: str) -> str:
    """LangGraph thread id for one story line. LEGACY_BRANCH_ID resolves to the old two-segment
    key so a chapter's pre-existing (pre-branching) conversation keeps pointing at the same
    checkpoint rows with zero data migration; every other branch gets its own three-segment key."""
    if branch_id == LEGACY_BRANCH_ID:
        return f"{novel_id}:{chapter}"
    return f"{novel_id}:{chapter}:{branch_id}"


class WriteTurn(Protocol):
    """Real streaming implementation lives in message_hub.py: does the actual LLM astream call,
    broadcasts each token as a side effect, returns the fully assembled raw text once done."""

    async def __call__(self, system: str, packet: str) -> str: ...


CallLLM = Callable[[str, str], Awaitable[str]]
GuardText = Callable[[str], Awaitable[str]]


def _locate_fragment(prose: str, original_text: str, anchor_offset: int) -> tuple[int, int]:
    """Find `original_text` inside `prose`. When it occurs more than once, pick the occurrence
    whose start index is closest to `anchor_offset` (the frontend's DOM-derived selection
    offset) to disambiguate. Raises ValueError when `original_text` is empty or doesn't occur
    at all in `prose`."""
    if not original_text:
        raise ValueError("选中内容为空")
    starts: list[int] = []
    idx = prose.find(original_text)
    while idx != -1:
        starts.append(idx)
        idx = prose.find(original_text, idx + 1)
    if not starts:
        raise ValueError("选中的文字未能在正文中定位，请重新选择")
    best = min(starts, key=lambda s: abs(s - anchor_offset))
    return best, best + len(original_text)


_SELECTION_REWRITE_MARKER_RE = re.compile(r"【修改后的片段】[：:]\s*")


def _build_selection_rewrite_prompt(
    style_card: str, full_prose: str, original_text: str, feedback: str,
) -> tuple[str, str]:
    """System/user pair for a single non-streaming call that rewrites ONLY the director-selected
    fragment. `full_prose` is given purely so the model keeps pronouns/context consistent --
    it must not repeat it in the output. Output-format marker mirrors prompt.py's
    `【正文】：` contract (see that module) so the model has one consistent marker convention
    across the whole sandbox; `_extract_rewritten_fragment` below is the code-side enforcement,
    same split as prose_format.py's strip_prose_preamble -- prompt asks nicely, code discards
    anything before the marker (out-of-character acknowledgements like "好的，这是重写后的片段"
    survive the instruction alone)."""
    system = (
        "你是这部小说正文的润色师。导演会选中正文里的一小段文字，你只需要把这一小段重写得更好，"
        "不改变其余正文、不改变场景事实和情节。\n"
        "输出格式：回复必须以「【修改后的片段】：」开头，后面直接接改写后的片段内容——开头前不能有"
        "任何寒暄/确认/元评论（例如「好的」「以下是重写后的片段」之类），片段写完也不要再追加"
        "解释、引号或其余正文内容。"
    )
    if style_card.strip():
        system += f"\n\n本书文风要求：\n{style_card}"
    feedback_text = feedback.strip() or "（未填写，按你的判断改一版）"
    user = (
        f"完整正文（仅供你理解上下文，不要重复输出）：\n{full_prose}\n\n"
        f"待重写的片段：\n{original_text}\n\n"
        f"导演对这次重写的反馈：{feedback_text}"
    )
    return system, user


def _extract_rewritten_fragment(raw: str) -> str:
    """Discard everything up to and including the `【修改后的片段】：` marker; fails open (returns
    the stripped raw text unchanged) if the model dropped the marker entirely."""
    text = raw.strip()
    m = _SELECTION_REWRITE_MARKER_RE.search(text)
    return text[m.end():].strip() if m else text


async def _guard_state_dict(
    states: dict[str, CharacterState], guard_text: GuardText,
) -> dict[str, CharacterState]:
    from context.content_packs import state_derive_fields

    scored_keys = {f.key for f in state_derive_fields() if f.kind == "scored_desc"}
    result: dict[str, CharacterState] = {}
    for name, fields in states.items():
        guarded: CharacterState = {}
        for k, v in fields.items():
            if k in scored_keys and isinstance(v, dict):
                desc = v.get("desc")
                if isinstance(desc, str) and desc:
                    guarded[k] = {**v, "desc": await guard_text(desc)}
                else:
                    guarded[k] = v
            elif isinstance(v, str) and v:
                guarded[k] = await guard_text(v)
            else:
                guarded[k] = v
        result[name] = guarded
    return result


async def _guard_scene_dict(scene: SceneState, guard_text: GuardText) -> SceneState:
    return {
        k: (await guard_text(v) if isinstance(v, str) and v else v)
        for k, v in scene.items()
    }


async def _guard_list(items: list[str], guard_text: GuardText) -> list[str]:
    return [await guard_text(s) if s else s for s in items]


async def _open_checkpointer(novel_id: str):
    """Actual connection-opening work, split out of ensure_checkpointer so it can run as its
    own awaitable Task (the in-flight-build guard below awaits this same Task from any number
    of concurrent callers instead of starting a second connection). story_sandbox_checkpoint_path
    resolves via ambient active_novel_id() -- wrapped in use_novel(novel_id) so this always opens
    the requested novel's own file regardless of whatever the process-wide active-novel pointer
    currently says."""
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from utils.paths import story_sandbox_checkpoint_path, use_novel

    with use_novel(novel_id):
        cp_path = story_sandbox_checkpoint_path()
    os.makedirs(os.path.dirname(cp_path), exist_ok=True)
    conn = await aiosqlite.connect(cp_path)
    checkpointer = AsyncSqliteSaver(conn)
    await checkpointer.setup()
    return checkpointer


async def ensure_checkpointer(novel_id: str):
    """This novel's aiosqlite connection, lazily opened and cached -- thread_id carries
    per-chapter isolation within a novel, this dict's novel_id key carries per-novel isolation;
    one file per novel, opened once, never reopened per turn. Guarded against concurrent
    double-build for the SAME novel_id (e.g. a startup warm-up task racing a user's first real
    request) via the in-flight-build Task stashed per novel_id -- different novel_ids build
    fully independently. The in-flight entry is always popped in a finally block: if the build
    fails or is cancelled (e.g. the caller's own task got cancelled, or interpreter/test
    teardown), a later caller must get a fresh build attempt, not hang awaiting a Task tied to
    an event loop that no longer exists."""
    import asyncio

    if novel_id in _checkpointers:
        return _checkpointers[novel_id]
    building = _checkpointers_building.get(novel_id)
    if building is None:
        building = asyncio.create_task(_open_checkpointer(novel_id))
        _checkpointers_building[novel_id] = building
    try:
        cp = await building
    finally:
        _checkpointers_building.pop(novel_id, None)
    _checkpointers[novel_id] = cp
    return cp


async def close_checkpointer(novel_id: str | None = None) -> None:
    """Novel-delete/shutdown teardown: discard cached connection(s) so a later ensure_checkpointer
    reopens fresh. novel_id=None closes every novel's connection (full shutdown); a specific
    novel_id closes only that one (e.g. novel deletion, before its directory is trashed)."""
    if novel_id is None:
        for nid in list(_checkpointers):
            await close_checkpointer(nid)
        return
    cp = _checkpointers.pop(novel_id, None)
    if cp is not None:
        try:
            await cp.conn.close()
        except Exception:  # noqa: BLE001 - best-effort close, failure here is not fatal
            pass


def _build_resolve_cast_opening_node(chapter: int, instruction: str):
    """Opening-turn variant: active_cast also folds in this turn's initial_states_this_turn
    (init_char's resolved opening roster -- no prior prose yet on a brand-new thread). Fan-in
    sibling of nothing else -- this is now the SOLE upstream for both dialogue_draft_opening
    and recall_opening (see _compile_opening_graph's edge comment for why this node must wait
    on BOTH init_char and init_scene, not just init_char)."""
    async def _n(state: SandboxState) -> dict:
        async with sandbox_step_timer("resolve_cast", {"chapter": chapter}):
            from engine.memory_recall.entity_index import scan_characters
            from engine.story_sandbox.cast import resolve_related_cast
            from engine.story_sandbox.cast_tracker import update_active_cast

            current_states = state.get("initial_states_this_turn") or {}
            prior_prose = state["turns"][-1]["prose"] if state.get("turns") else ""
            turn_index = len(state.get("turns") or [])
            character_hits = (
                set(scan_characters(instruction)) | set(scan_characters(prior_prose))
            ) | set(current_states)
            active_cast = update_active_cast(state.get("active_cast") or {}, character_hits, turn_index)
            related_names = [
                n for n in resolve_related_cast(set(active_cast), state.get("relationship_overlay") or {})
                if n not in active_cast
            ]
            return {"active_cast": active_cast, "related_cast_this_turn": related_names}
    return _n


def _build_dialogue_draft_opening_node(
    chapter: int, instruction: str, call_llm_dialogue_draft: CallLLM | None,
):
    """Opening-turn variant: roster comes from resolve_cast's active_cast (init_char's resolved
    initial_states_this_turn folded in upstream) -- fan-in sibling of recall, downstream of
    resolve_cast (see _compile_opening_graph)."""
    async def _n(state: SandboxState) -> dict:
        async with sandbox_step_timer("dialogue_draft", {"chapter": chapter}):
            from api.services.novels import get_sandbox_dialogue_turn_count
            from utils.paths import active_novel_id

            from engine.story_sandbox.cast import resolve_character_cards
            from engine.story_sandbox.dialogue_draft import draft_dialogue

            if call_llm_dialogue_draft is None:
                return {"dialogue_draft_this_turn": ""}
            current_states = state.get("initial_states_this_turn") or {}
            present_names = sorted(state["active_cast"])
            if not present_names:
                return {"dialogue_draft_this_turn": ""}
            configured = get_sandbox_dialogue_turn_count(active_novel_id())
            turn_count = configured if configured is not None else len(present_names) + 1
            related_names = state.get("related_cast_this_turn") or []
            present_cards = resolve_character_cards(chapter, present_names)
            related_cards = resolve_character_cards(chapter, related_names)
            present_states = {k: v for k, v in current_states.items() if k in present_names}
            draft = await draft_dialogue(
                instruction, [], present_states, present_cards, related_cards, call_llm_dialogue_draft,
                turn_count=turn_count,
            )
            return {"dialogue_draft_this_turn": draft}
    return _n


def _build_recall_opening_node(chapter: int, branch_id: str, instruction: str):
    """Opening-turn recall: active_cast is computed by the upstream resolve_cast_opening node
    and read back from state."""
    async def _n(state: SandboxState) -> dict:
        async with sandbox_step_timer("recall", {"chapter": chapter}):
            from engine.memory_recall.recall import recall_relevant_context

            prior_prose = state["turns"][-1]["prose"] if state.get("turns") else ""
            turn_index = len(state.get("turns") or [])
            active_cast = state["active_cast"]
            recall_block, updated_cooldown, recalled_settings = await asyncio.to_thread(
                recall_relevant_context,
                instruction, chapter=chapter, origin=MemoryOrigin.SANDBOX, branch_id=branch_id,
                prior_prose=prior_prose, turn_index=turn_index, cooldown=state.get("recall_cooldown"),
                active_cast=active_cast,
            )
            return {
                "recall_context_this_turn": recall_block,
                "recalled_settings_this_turn": recalled_settings,
                "recall_cooldown": updated_cooldown,
            }
    return _n


def _build_prose_opening_node(
    chapter: int, branch_id: str, instruction: str, write_turn: WriteTurn,
):
    """Opening-turn prose: baseline states come from init_char/init_scene in a prior superstep."""
    async def _n(state: SandboxState) -> dict:
        from engine.story_sandbox.cast import (
            render_dynamic_cast_block,
            render_related_cast_block,
        )
        from engine.story_sandbox.prompt import build_sandbox_system_prompt

        current_states = state.get("initial_states_this_turn") or {}
        current_scene_state = state.get("initial_scene_state_this_turn") or {}
        active_cast = state.get("active_cast") or {}
        recall_block = state.get("recall_context_this_turn") or ""
        system, opening_names = build_sandbox_system_prompt(
            chapter, is_opening=True,
            rolling_summary=state["rolling_summary"], turns=state["turns"],
            character_states=current_states, scene_state=current_scene_state,
            character_profile=state.get("character_profile", {}),
            dialogue_draft=state.get("dialogue_draft_this_turn") or "",
            known_roster_fallback=state.get("known_roster_fallback_this_turn") or [],
            instruction_grounding_graph=state.get("instruction_grounding_graph_this_turn") or "",
            instruction_grounding_briefs=state.get("instruction_grounding_briefs_this_turn") or "",
        )
        cast_block = render_dynamic_cast_block(active_cast, chapter=chapter, exclude=opening_names)
        related_names = state.get("related_cast_this_turn") or []
        related_cast_block = render_related_cast_block(
            related_names, chapter=chapter, exclude=set(active_cast) | opening_names,
        )
        packet = render_turn_packet(
            instruction=instruction, cast_block=cast_block,
            related_cast_block=related_cast_block, recall_block=recall_block,
        )
        final_text = await write_turn(system, packet)
        return {
            "final_text": final_text,
            "baseline_states": current_states, "baseline_scene_state": current_scene_state,
            "instruction_this_turn": instruction,
        }
    return _n


def _build_resolve_cast_node(chapter: int):
    """Non-opening turns: active_cast is carried forward exactly as derive_char left it last
    turn -- resolve_cast no longer scans or predicts. related_cast_this_turn is still
    recomputed every turn (relationship_overlay itself can change), folding in background_cast
    (last turn's scan-hit-but-not-confirmed names) so a background-mentioned character can
    still surface as a related-cast reference in this turn's prompt."""
    async def _n(state: SandboxState) -> dict:
        async with sandbox_step_timer("resolve_cast", {"chapter": chapter}):
            from engine.story_sandbox.cast import resolve_related_cast

            active_cast = state.get("active_cast") or {}
            graph_related = resolve_related_cast(set(active_cast), state.get("relationship_overlay") or {})
            background_related = state.get("background_cast") or []
            related_names = sorted(
                {n for n in [*graph_related, *background_related] if n not in active_cast},
            )
            return {"active_cast": active_cast, "related_cast_this_turn": related_names}
    return _n


def _build_dialogue_draft_node(chapter: int, instruction: str, call_llm_dialogue_draft: CallLLM | None):
    """Joint dialogue draft for non-opening turns, run after resolve_cast so it can read this
    turn's already-resolved active_cast/related_cast instead of approximating its own."""
    async def _n(state: SandboxState) -> dict:
        async with sandbox_step_timer("dialogue_draft", {"chapter": chapter}):
            from api.services.novels import get_sandbox_dialogue_turn_count
            from utils.paths import active_novel_id

            from engine.story_sandbox.cast import resolve_character_cards
            from engine.story_sandbox.dialogue_draft import draft_dialogue

            if call_llm_dialogue_draft is None:
                return {"dialogue_draft_this_turn": ""}
            present_names = sorted(state["active_cast"])
            if not present_names:
                return {"dialogue_draft_this_turn": ""}
            configured = get_sandbox_dialogue_turn_count(active_novel_id())
            turn_count = configured if configured is not None else len(present_names) + 1
            related_names = state.get("related_cast_this_turn") or []
            present_cards = resolve_character_cards(chapter, present_names)
            related_cards = resolve_character_cards(chapter, related_names)
            present_states = {
                k: v for k, v in (state.get("character_states") or {}).items() if k in present_names
            }
            draft = await draft_dialogue(
                instruction, state.get("turns") or [], present_states,
                present_cards, related_cards, call_llm_dialogue_draft, turn_count=turn_count,
            )
            return {"dialogue_draft_this_turn": draft}
    return _n


def _build_recall_node(chapter: int, branch_id: str, instruction: str):
    """Normal-turn recall: active_cast is computed by the upstream resolve_cast node and read
    back from state -- recall no longer computes or returns it."""
    async def _n(state: SandboxState) -> dict:
        async with sandbox_step_timer("recall", {"chapter": chapter}):
            from engine.memory_recall.recall import recall_relevant_context

            prior_prose = state["turns"][-1]["prose"] if state.get("turns") else ""
            turn_index = len(state.get("turns") or [])
            active_cast = state["active_cast"]
            recall_block, updated_cooldown, recalled_settings = await asyncio.to_thread(
                recall_relevant_context,
                instruction, chapter=chapter, origin=MemoryOrigin.SANDBOX, branch_id=branch_id,
                prior_prose=prior_prose, turn_index=turn_index, cooldown=state.get("recall_cooldown"),
                active_cast=active_cast,
            )
            return {
                "recall_context_this_turn": recall_block,
                "recalled_settings_this_turn": recalled_settings,
                "recall_cooldown": updated_cooldown,
            }
    return _n


def _build_prose_node(
    chapter: int, branch_id: str, instruction: str, write_turn: WriteTurn,
):
    """Write prose + guard for non-opening turns."""
    async def _n(state: SandboxState) -> dict:
        from engine.story_sandbox.cast import (
            render_dynamic_cast_block,
            render_related_cast_block,
        )
        from engine.story_sandbox.prompt import build_sandbox_system_prompt

        active_cast = state.get("active_cast") or {}
        recall_block = state.get("recall_context_this_turn") or ""
        # Only inject PRESENT characters' dynamic state into the prompt -- state.character_states
        # itself stays the full, unfiltered accumulator (baseline_states below needs it whole for
        # derive_char's next-turn merge), this filter is purely about what the model gets shown.
        present_states = {k: v for k, v in state["character_states"].items() if k in active_cast}
        system, opening_names = build_sandbox_system_prompt(
            chapter, is_opening=False,
            rolling_summary=state["rolling_summary"], turns=state["turns"],
            character_states=present_states, scene_state=state["scene_state"],
            character_profile=state.get("character_profile", {}),
            dialogue_draft=state.get("dialogue_draft_this_turn") or "",
        )
        cast_block = render_dynamic_cast_block(active_cast, chapter=chapter, exclude=opening_names)
        related_names = state.get("related_cast_this_turn") or []
        related_cast_block = render_related_cast_block(
            related_names, chapter=chapter, exclude=set(active_cast) | opening_names,
        )
        packet = render_turn_packet(
            instruction=instruction, cast_block=cast_block,
            related_cast_block=related_cast_block, recall_block=recall_block,
        )
        final_text = await write_turn(system, packet)
        update: dict[str, Any] = {
            "final_text": final_text,
            "baseline_states": state["character_states"], "baseline_scene_state": state["scene_state"],
            "initial_states_this_turn": None, "initial_scene_state_this_turn": None,
            "instruction_this_turn": instruction,
        }
        return update
    return _n


def _rewrite_round_context(state: SandboxState) -> tuple[str, dict[str, CharacterState], bool]:
    """Shared by the rewrite path's dialogue_draft and prose_rewrite nodes: the original
    instruction of the round being rewritten, the baseline character_states to derive from, and
    whether this rewrite targets the chapter's opening round."""
    last_round = state["turns"][-1]
    is_opening = len(state["turns"]) == 1
    baseline_states = (
        (last_round["initial_states"] or last_round["character_states"])
        if is_opening else state["turns"][-2]["character_states"]
    )
    return last_round["instruction"], baseline_states, is_opening


def _recall_scan_text_for_round_rewrite(
    state: SandboxState, *, extra_scan_text: str = "", include_current_prose: bool = False,
) -> str:
    """Keyword/entity scan input for same-round rewrite entry points. Mirrors
    _build_recall_rewrite_node's instruction sourcing; optional steering text (feedback/hint)
    and the current round's finalized prose can be folded in when the caller needs recall to
    react to user edits without re-running the full prose-rewrite graph."""
    instruction, _, _ = _rewrite_round_context(state)
    parts = [instruction]
    if extra_scan_text.strip():
        parts.append(extra_scan_text.strip())
    if include_current_prose:
        prose = (state["turns"][-1].get("prose") or "").strip()
        if prose:
            parts.append(prose)
    return "\n".join(parts)


async def _recall_for_round_rewrite(
    state: SandboxState, chapter: int, branch_id: str, *, extra_scan_text: str = "",
    include_current_prose: bool = False,
) -> tuple[str, list[dict], dict[str, int]]:
    """Fresh recall for standalone same-round entry points (suggestions regenerate, profile
    mutation rewrite) -- same turn_index/cooldown/active_cast contract as
    _build_recall_rewrite_node."""
    from engine.memory_recall.recall import recall_relevant_context

    prior_prose = state["turns"][-2]["prose"] if len(state["turns"]) >= 2 else ""
    turn_index = len(state["turns"]) - 1
    active_cast = state.get("active_cast") or {}
    raw_cooldown = state.get("recall_cooldown") or {}
    cooldown_for_rewrite = {k: v for k, v in raw_cooldown.items() if v != turn_index}
    scan_text = _recall_scan_text_for_round_rewrite(
        state, extra_scan_text=extra_scan_text, include_current_prose=include_current_prose,
    )
    recall_block, recalled_cooldown, recalled_settings = await asyncio.to_thread(
        recall_relevant_context,
        scan_text, chapter=chapter, origin=MemoryOrigin.SANDBOX,
        branch_id=branch_id, prior_prose=prior_prose,
        turn_index=turn_index, cooldown=cooldown_for_rewrite, active_cast=active_cast,
    )
    updated_cooldown = {**raw_cooldown, **recalled_cooldown}
    return recall_block, recalled_settings, updated_cooldown


def _build_resolve_cast_rewrite_node(chapter: int):
    """Rewrite-turn variant: same carry-forward contract as _build_resolve_cast_node -- no
    longer reads the round-being-rewritten's instruction/prior prose at all."""
    async def _n(state: SandboxState) -> dict:
        async with sandbox_step_timer("resolve_cast", {"chapter": chapter}):
            from engine.story_sandbox.cast import resolve_related_cast

            active_cast = state.get("active_cast") or {}
            graph_related = resolve_related_cast(set(active_cast), state.get("relationship_overlay") or {})
            background_related = state.get("background_cast") or []
            related_names = sorted(
                {n for n in [*graph_related, *background_related] if n not in active_cast},
            )
            return {"active_cast": active_cast, "related_cast_this_turn": related_names}
    return _n


def _build_dialogue_draft_rewrite_node(chapter: int, call_llm_dialogue_draft: CallLLM | None):
    """Rewrite-turn variant: the instruction being rewritten and its baseline states aren't
    graph-compile-time constants (unlike the non-opening/opening variants) -- both come from
    state via _rewrite_round_context, the same helper prose_rewrite itself uses."""
    async def _n(state: SandboxState) -> dict:
        async with sandbox_step_timer("dialogue_draft", {"chapter": chapter}):
            from api.services.novels import get_sandbox_dialogue_turn_count
            from utils.paths import active_novel_id

            from engine.story_sandbox.cast import resolve_character_cards
            from engine.story_sandbox.dialogue_draft import draft_dialogue

            if call_llm_dialogue_draft is None:
                return {"dialogue_draft_this_turn": ""}
            instruction, baseline_states, _ = _rewrite_round_context(state)
            present_names = sorted(state["active_cast"])
            if not present_names:
                return {"dialogue_draft_this_turn": ""}
            configured = get_sandbox_dialogue_turn_count(active_novel_id())
            turn_count = configured if configured is not None else len(present_names) + 1
            related_names = state.get("related_cast_this_turn") or []
            present_cards = resolve_character_cards(chapter, present_names)
            related_cards = resolve_character_cards(chapter, related_names)
            present_states = {k: v for k, v in baseline_states.items() if k in present_names}
            draft = await draft_dialogue(
                instruction, state["turns"][:-1], present_states,
                present_cards, related_cards, call_llm_dialogue_draft, turn_count=turn_count,
            )
            return {"dialogue_draft_this_turn": draft}
    return _n


def _build_recall_rewrite_node(chapter: int, branch_id: str):
    """Rewrite-turn recall: active_cast is computed by the upstream resolve_cast_rewrite node
    and read back from state."""
    async def _n(state: SandboxState) -> dict:
        async with sandbox_step_timer("recall", {"chapter": chapter}):
            from engine.memory_recall.recall import recall_relevant_context

            instruction, _, _ = _rewrite_round_context(state)
            prior_prose = state["turns"][-2]["prose"] if len(state["turns"]) >= 2 else ""
            turn_index = len(state["turns"]) - 1
            active_cast = state["active_cast"]
            raw_cooldown = state.get("recall_cooldown") or {}
            cooldown_for_rewrite = {k: v for k, v in raw_cooldown.items() if v != turn_index}
            recall_block, recalled_cooldown, recalled_settings = await asyncio.to_thread(
                recall_relevant_context,
                instruction, chapter=chapter, origin=MemoryOrigin.SANDBOX,
                branch_id=branch_id, prior_prose=prior_prose,
                turn_index=turn_index, cooldown=cooldown_for_rewrite, active_cast=active_cast,
            )
            updated_cooldown = {**raw_cooldown, **recalled_cooldown}
            return {
                "recall_context_this_turn": recall_block,
                "recalled_settings_this_turn": recalled_settings,
                "recall_cooldown": updated_cooldown,
            }
    return _n


def _build_prose_rewrite_node(chapter: int, branch_id: str, feedback: str, write_turn: WriteTurn):
    """Rewrite prose node: baseline from the round's opening initial_states or prior round."""
    async def _n(state: SandboxState) -> dict:
        from engine.story_sandbox.cast import (
            render_dynamic_cast_block,
            render_related_cast_block,
        )
        from engine.story_sandbox.prompt import build_sandbox_system_prompt

        last_round = state["turns"][-1]
        _, baseline_states, is_opening = _rewrite_round_context(state)
        baseline_scene_state = (
            (last_round["initial_scene_state"] or last_round["scene_state"])
            if is_opening else state["turns"][-2]["scene_state"]
        )
        active_cast = state.get("active_cast") or {}
        recall_block = state.get("recall_context_this_turn") or ""

        present_states = {k: v for k, v in baseline_states.items() if k in active_cast}
        system, opening_names = build_sandbox_system_prompt(
            chapter, is_opening=is_opening,
            rolling_summary=state["rolling_summary"], turns=state["turns"][:-1],
            character_states=present_states, scene_state=baseline_scene_state,
            character_profile=state.get("character_profile", {}),
            dialogue_draft=state.get("dialogue_draft_this_turn") or "",
        )
        cast_block = render_dynamic_cast_block(active_cast, chapter=chapter, exclude=opening_names)
        related_names = state.get("related_cast_this_turn") or []
        related_cast_block = render_related_cast_block(
            related_names, chapter=chapter, exclude=set(active_cast) | opening_names,
        )
        packet = render_turn_packet(
            instruction=last_round["instruction"], cast_block=cast_block,
            related_cast_block=related_cast_block, recall_block=recall_block,
            rewrite_note={"previous_prose": last_round["prose"], "feedback": feedback},
        )
        final_text = await write_turn(system, packet)
        return {
            "final_text": final_text, "baseline_states": baseline_states,
            "baseline_scene_state": baseline_scene_state,
            "instruction_this_turn": last_round["instruction"],
        }
    return _n


def _build_init_char_node(
    chapter: int, instruction: str, call_llm_derive_char: CallLLM,
    call_llm_identify: CallLLM | None, guard_text: GuardText,
):
    """Opening-turn only -- fan-in sibling of init_scene, both fed directly from START. Chapter
    and free mode share the exact same resolution now: when call_llm_identify is given, runs
    cast_identify.resolve_present_roster against `instruction` (the sole grounding text -- the
    frontend prefills chapter mode's composer from the plot outline on a fresh chapter, but
    whatever the director actually sends is what this reads) with the full novel roster as the
    closed set, then renders persona cards for whichever names resolved via
    cast.resolve_character_cards. An empty (not None) identify result -- the instruction named
    nobody -- populates known_roster_fallback_this_turn with the full roster instead, for
    prose_opening to render as a plain name-list guardrail (see prompt.py's
    _known_roster_fallback_block).

    Degrades to a deterministic entity_index.scan_characters(instruction) scan when
    call_llm_identify is None or the novel's roster is empty (resolve_present_roster returns
    None per its own docstring) -- no LLM call, no known_roster_fallback (that guardrail only
    makes sense when the identify layer actively looked and found nobody, not when the whole
    layer was skipped)."""
    async def _n(_state: SandboxState) -> dict:
        from engine.memory_recall.entity_index import build_character_vocab, scan_characters
        from engine.story_sandbox.cast import resolve_character_cards
        from engine.story_sandbox.cast_identify import remap_state_keys, resolve_present_roster

        roster: list[str] = []
        known_roster_fallback: list[str] = []
        instruction_grounding_graph = ""
        instruction_grounding_briefs = ""
        passerby_present: list[str] = []
        if call_llm_identify is not None:
            roster = list(build_character_vocab())
            resolved = await resolve_present_roster(instruction, roster, call_llm_identify)
            if resolved is None:
                present = sorted(set(scan_characters(instruction)))
            else:
                present, passerby_present = resolved
                if not present and not passerby_present and roster:
                    known_roster_fallback = roster
                    from engine.story_sandbox.cast import render_instruction_grounding_blocks

                    instruction_grounding_graph, instruction_grounding_briefs = (
                        render_instruction_grounding_blocks(instruction, chapter=chapter)
                    )
        else:
            present = sorted(set(scan_characters(instruction)))
        all_present = [*present, *passerby_present]
        cards = resolve_character_cards(chapter, all_present) if all_present else []
        states = await derive_initial_states(cards, instruction, call_llm_derive_char)
        if roster:
            # remap_state_keys only resolves against `roster` (cast names) -- passerby aren't on
            # it, so their derived keys would all get dropped as "unresolvable" by its own
            # closed-set logic. Split the derived dict, remap only the cast slice, keep passerby
            # entries whose key matches (case-sensitive, no fuzzy resolution -- passerby names
            # aren't expected to have shortened-form ambiguity the way registered characters do)
            # one of the names we actually asked for.
            passerby_set = set(passerby_present)
            cast_states = {k: v for k, v in states.items() if k not in passerby_set}
            passerby_states = {k: v for k, v in states.items() if k in passerby_set}
            states = {**remap_state_keys(cast_states, roster), **passerby_states}
        else:
            # identify inactive (no call_llm_identify, or novel's lore roster empty) --
            # derive_initial_states isn't itself constrained to the cards it was given, so a
            # model that free-associates a name outside the grounding it was handed must not get
            # that name into initial_states_this_turn: this flows straight into active_cast (see
            # _build_resolve_cast_opening_node's character_hits, which ORs in every current_states
            # key unconditionally) and would earn a full persona card rendered every subsequent
            # turn.
            card_names = {c["name"] for c in cards}
            states = {k: v for k, v in states.items() if k in card_names}
        guarded = await _guard_state_dict(states, guard_text)
        return {
            "initial_states_this_turn": guarded,
            "known_roster_fallback_this_turn": known_roster_fallback,
            "instruction_grounding_graph_this_turn": instruction_grounding_graph,
            "instruction_grounding_briefs_this_turn": instruction_grounding_briefs,
            "passerby_names": sorted(passerby_present),
        }
    return _n


def _build_init_scene_node(
    chapter: int, instruction: str, call_llm_derive_scene: CallLLM, guard_text: GuardText,
):
    """Opening-turn only -- fan-in sibling of init_char, both fed directly from START. Grounds
    solely on this turn's instruction (chapter mode's frontend prefills the composer with
    plot-outline location/description on a fresh chapter, but whatever the director actually
    sends is what this reads) plus the novel's world summary -- same source in both modes, no
    per-chapter branching. Free mode only (chapter == 0) additionally passes the world bible's
    geography names as derive_initial_scene_state's known_locations guardrail -- chapter mode
    already has plot-outline location grounding indirectly via the frontend's prefilled
    instruction, so it's left at []."""
    async def _n(_state: SandboxState) -> dict:
        from repositories import get_world_repo

        from engine.setup.chat_summary import geography_names, render_world_chat

        wb = get_world_repo().get()
        world_summary = render_world_chat(wb)
        known_locations = geography_names(wb) if chapter == 0 else []
        scene = await derive_initial_scene_state(
            instruction, world_summary, known_locations, call_llm_derive_scene,
        )
        guarded = await _guard_scene_dict(scene, guard_text)
        return {"initial_scene_state_this_turn": guarded}
    return _n


def _build_derive_char_node(
    chapter: int, call_llm_derive_char: CallLLM, call_llm_identify: CallLLM | None,
    guard_text: GuardText, *, is_rewrite: bool = False,
):
    """Fan-in sibling of derive_scene -- sole identify+derive stage for non-opening turns
    (resolve_cast no longer scans/predicts). Two candidate signals run in parallel:
    scan_characters(final_text) (deterministic) and the identify LLM call (precision-oriented).
    Combining them: 在场 = identify's 角色; 路人 = identify's 路人; background_cast = scan hits
    identify did NOT confirm present. State derivation splits by baseline existence: has-baseline
    -> closed-set update (silent carry-forward on miss); no-baseline -> cold-start init with one
    narrow retry on miss."""
    async def _n(state: SandboxState) -> dict:
        async with sandbox_step_timer("derive_char", {"chapter": chapter}):
            from engine.memory_recall.entity_index import build_character_vocab, scan_characters
            from engine.story_sandbox.cast import resolve_character_cards
            from engine.story_sandbox.cast_identify import (
                remap_state_keys,
                resolve_present_roster_in_prose,
            )
            from engine.story_sandbox.cast_tracker import update_active_cast
            from engine.story_sandbox.state_derive import derive_initial_states_from_prose

            final_text = state["final_text"]
            roster = list(build_character_vocab())
            ac_hits = set(scan_characters(final_text))

            resolved = None
            if call_llm_identify is not None and roster:
                resolved = await resolve_present_roster_in_prose(final_text, roster, call_llm_identify)
            if resolved is None:
                present: list[str] = sorted(ac_hits)
                passerby_present: list[str] = []
            else:
                present, passerby_present = resolved
            background_cast = sorted(ac_hits - set(present))

            baseline_states = state["baseline_states"]
            all_present = [*present, *passerby_present]
            with_baseline = [n for n in all_present if n in baseline_states]
            without_baseline = [n for n in all_present if n not in baseline_states]

            derived: dict[str, CharacterState] = {}
            if with_baseline:
                prior = {n: baseline_states[n] for n in with_baseline}
                derived_update = await derive_character_states(
                    prior, final_text, call_llm_derive_char, present=with_baseline,
                )
                for name in with_baseline:
                    derived[name] = derived_update.get(name, baseline_states[name])

            if without_baseline:
                cards = resolve_character_cards(chapter, without_baseline)
                init_result = await derive_initial_states_from_prose(
                    cards, final_text, call_llm_derive_char,
                )
                missing_init = [n for n in without_baseline if n not in init_result]
                if missing_init:
                    retry_cards = resolve_character_cards(chapter, missing_init)
                    retry_result = await derive_initial_states_from_prose(
                        retry_cards, final_text, call_llm_derive_char,
                    )
                    init_result = {**init_result, **retry_result}
                derived.update(init_result)

            guarded_derived = await _guard_state_dict(derived, guard_text)
            if roster:
                passerby_set = set(passerby_present)
                cast_slice = {k: v for k, v in guarded_derived.items() if k not in passerby_set}
                passerby_slice = {k: v for k, v in guarded_derived.items() if k in passerby_set}
                guarded_derived = {**remap_state_keys(cast_slice, roster), **passerby_slice}

            turns_len = len(state.get("turns") or [])
            turn_index = turns_len - 1 if is_rewrite else turns_len
            confirmed = set(present) | set(passerby_present)
            active_cast = update_active_cast(state.get("active_cast") or {}, confirmed, turn_index)

            merged_states = {**baseline_states, **guarded_derived}
            character_states = {k: v for k, v in merged_states.items() if k in active_cast}
            passerby_names = sorted(set(passerby_present) & set(active_cast))

            return {
                "character_states": character_states,
                "active_cast": active_cast,
                "passerby_names": passerby_names,
                "background_cast": background_cast,
            }
    return _n


def _build_derive_scene_node(call_llm_derive_scene: CallLLM, guard_text: GuardText):
    """Fan-in sibling of derive_char -- reads (final_text, baseline_scene_state), writes scene_state."""
    async def _n(state: SandboxState) -> dict:
        async with sandbox_step_timer("derive_scene", {}):
            derived_scene = await derive_scene_state(
                state["baseline_scene_state"], state["final_text"], call_llm_derive_scene,
            )
            guarded_derived = await _guard_scene_dict(derived_scene, guard_text)
            return {"scene_state": {**state["baseline_scene_state"], **guarded_derived}}
    return _n


def _mark_prior_submitted(turns: list[Round], submitted_directions: list[str] | None) -> list[Round]:
    """Tag the last round with which of its own suggestions the next instruction picked."""
    if not submitted_directions or not turns:
        return turns
    last = turns[-1]
    picked = [d for d in submitted_directions if d in last["suggestions"]]
    if not picked:
        return turns
    marked: Round = {**last, "submitted_directions": picked}
    return [*turns[:-1], marked]


def _build_suggest_node(
    chapter: int, instruction: str, call_llm_suggest: CallLLM, core_xp: list[str],
    guard_text: GuardText,
):
    """Normal turn finish: append round. `turns` itself is never trimmed -- it's the full round
    history the history endpoint reconstructs the timeline from (see
    message_hub.py::story_sandbox_history); only the LLM-facing packet windows to the last
    KEEP_FULL_TURNS via prompt.py::recent_turns_block. Rolling-summary folding and event-log
    extraction happen in the parallel event_log node (event_log.py) -- this node writes that
    node's output directly onto the new round."""
    async def _n(state: SandboxState) -> dict:
        async with sandbox_step_timer("suggest", {"chapter": chapter}):
            from engine.story_sandbox.cast import resolve_character_cards, resolve_related_cast

            present_names = set(state.get("active_cast") or {})
            present_states = {k: v for k, v in state["character_states"].items() if k in present_names}
            cards = resolve_character_cards(chapter, sorted(present_states))
            related_names = [n for n in resolve_related_cast(present_names, state.get("relationship_overlay") or {}) if n not in present_names]
            related_cards = resolve_character_cards(chapter, related_names)
            recall_block = state.get("recall_context_this_turn", "")
            suggestions = await suggest_directions(
                state["final_text"], present_states, call_llm_suggest,
                core_xp=core_xp, cards=cards, related_cards=related_cards, recall_block=recall_block,
            )
            guarded_suggestions = await _guard_list(suggestions, guard_text)
            new_round: Round = {
                "id": uuid.uuid4().hex,
                "instruction": instruction, "prose": state["final_text"],
                "character_states": state["character_states"], "suggestions": guarded_suggestions,
                "initial_states": state.get("initial_states_this_turn"),
                "scene_state": state["scene_state"],
                "initial_scene_state": state.get("initial_scene_state_this_turn"),
                "event_log_entries": state.get("event_log_entries_this_turn") or [],
                "profile_mutation": state.get("profile_mutation_this_turn"),
                "relationship_mutation": state.get("relationship_mutation_this_turn"),
                "rolling_summary_after": state["rolling_summary"],
                "recall_context": recall_block,
                "recalled_settings": state.get("recalled_settings_this_turn", []),
            }
            new_turns = [*state["turns"], new_round]

            return {"turns": new_turns, "suggestions": guarded_suggestions}
    return _n


def _build_suggest_rewrite_node(
    chapter: int, call_llm_suggest: CallLLM, core_xp: list[str], guard_text: GuardText,
):
    """Rewrite finish: replace last round, no summary fold."""
    async def _n(state: SandboxState) -> dict:
        async with sandbox_step_timer("suggest", {"chapter": chapter}):
            from engine.story_sandbox.cast import resolve_character_cards, resolve_related_cast

            present_names = set(state.get("active_cast") or {})
            present_states = {k: v for k, v in state["character_states"].items() if k in present_names}
            cards = resolve_character_cards(chapter, sorted(present_states))
            related_names = [n for n in resolve_related_cast(present_names, state.get("relationship_overlay") or {}) if n not in present_names]
            related_cards = resolve_character_cards(chapter, related_names)
            recall_block = state.get("recall_context_this_turn", "")
            suggestions = await suggest_directions(
                state["final_text"], present_states, call_llm_suggest,
                core_xp=core_xp, cards=cards, related_cards=related_cards, recall_block=recall_block,
            )
            guarded_suggestions = await _guard_list(suggestions, guard_text)
            last_round = state["turns"][-1]
            new_round: Round = {
                "id": last_round.get("id") or uuid.uuid4().hex,
                "instruction": last_round["instruction"], "prose": state["final_text"],
                "character_states": state["character_states"], "suggestions": guarded_suggestions,
                "initial_states": last_round["initial_states"],
                "scene_state": state["scene_state"],
                "initial_scene_state": last_round["initial_scene_state"],
                "event_log_entries": state.get("event_log_entries_this_turn") or [],
                "profile_mutation": state.get("profile_mutation_this_turn"),
                "relationship_mutation": state.get("relationship_mutation_this_turn"),
                "rolling_summary_after": state["rolling_summary"],
                "recall_context": recall_block,
                "recalled_settings": state.get("recalled_settings_this_turn", []),
            }
            new_turns = [*state["turns"][:-1], new_round]
            return {"turns": new_turns, "suggestions": guarded_suggestions}
    return _n


def _compile_graph(
    chapter: int, branch_id: str, instruction: str, write_turn: WriteTurn, *,
    call_llm_derive_char: CallLLM, call_llm_derive_scene: CallLLM,
    call_llm_summary_fold: CallLLM, call_llm_event_extract: CallLLM,
    call_llm_profile_mutate: CallLLM, call_llm_suggest: CallLLM,
    call_llm_identify: CallLLM | None, call_llm_dialogue_draft: CallLLM | None, checkpointer,
    guard_text_derive_char: GuardText, guard_text_derive_scene: GuardText,
    guard_text_summary_fold: GuardText, guard_text_event_extract: GuardText,
    guard_text_profile_mutate: GuardText,
    guard_text_suggest: GuardText,
):
    from repositories import get_plot_repo

    core_xp = get_plot_repo().chapter_core_xp(chapter)
    g = StateGraph(SandboxState)
    g.add_node("resolve_cast", _build_resolve_cast_node(chapter))
    g.add_node("dialogue_draft", _build_dialogue_draft_node(chapter, instruction, call_llm_dialogue_draft))
    g.add_node("recall", _build_recall_node(chapter, branch_id, instruction))
    g.add_node("prose", _build_prose_node(chapter, branch_id, instruction, write_turn))
    g.add_node("derive_char", _build_derive_char_node(
        chapter, call_llm_derive_char, call_llm_identify, guard_text_derive_char,
    ))
    g.add_node("derive_scene", _build_derive_scene_node(call_llm_derive_scene, guard_text_derive_scene))
    g.add_node("summary_fold", build_summary_fold_node(instruction, call_llm_summary_fold, guard_text_summary_fold))
    g.add_node("event_extract", build_event_extract_node(
        chapter, instruction, call_llm_event_extract, guard_text_event_extract, branch_id=branch_id,
    ))
    g.add_node("profile_mutate", build_profile_mutate_node(
        chapter, call_llm_profile_mutate, guard_text_profile_mutate,
    ))
    g.add_node(
        "suggest",
        _build_suggest_node(chapter, instruction, call_llm_suggest, core_xp, guard_text_suggest),
    )
    g.add_edge(START, "resolve_cast")
    g.add_edge("resolve_cast", "dialogue_draft")
    g.add_edge("resolve_cast", "recall")
    g.add_edge("dialogue_draft", "prose")
    g.add_edge("recall", "prose")
    g.add_edge("prose", "derive_scene")
    g.add_edge("prose", "derive_char")
    g.add_edge("prose", "summary_fold")
    g.add_edge("prose", "event_extract")
    g.add_edge("event_extract", "profile_mutate")
    g.add_edge(["derive_char", "derive_scene", "profile_mutate", "summary_fold"], "suggest")
    g.add_edge("suggest", END)
    return g.compile(checkpointer=checkpointer)


def _compile_opening_graph(
    chapter: int, branch_id: str, instruction: str, write_turn: WriteTurn, *,
    call_llm_derive_char: CallLLM, call_llm_derive_scene: CallLLM,
    call_llm_summary_fold: CallLLM, call_llm_event_extract: CallLLM,
    call_llm_profile_mutate: CallLLM, call_llm_suggest: CallLLM,
    call_llm_identify: CallLLM | None, call_llm_dialogue_draft: CallLLM | None, checkpointer,
    guard_text_derive_char: GuardText, guard_text_derive_scene: GuardText,
    guard_text_summary_fold: GuardText, guard_text_event_extract: GuardText,
    guard_text_profile_mutate: GuardText,
    guard_text_suggest: GuardText,
):
    from repositories import get_plot_repo

    core_xp = get_plot_repo().chapter_core_xp(chapter)
    g = StateGraph(SandboxState)
    g.add_node("init_char", _build_init_char_node(
        chapter, instruction, call_llm_derive_char, call_llm_identify, guard_text_derive_char,
    ))
    g.add_node("init_scene", _build_init_scene_node(chapter, instruction, call_llm_derive_scene, guard_text_derive_scene))
    g.add_node("resolve_cast", _build_resolve_cast_opening_node(chapter, instruction))
    g.add_node("dialogue_draft", _build_dialogue_draft_opening_node(
        chapter, instruction, call_llm_dialogue_draft,
    ))
    g.add_node("recall", _build_recall_opening_node(chapter, branch_id, instruction))
    g.add_node("prose", _build_prose_opening_node(chapter, branch_id, instruction, write_turn))
    g.add_node("derive_char", _build_derive_char_node(
        chapter, call_llm_derive_char, call_llm_identify, guard_text_derive_char,
    ))
    g.add_node("derive_scene", _build_derive_scene_node(call_llm_derive_scene, guard_text_derive_scene))
    g.add_node("summary_fold", build_summary_fold_node(instruction, call_llm_summary_fold, guard_text_summary_fold))
    g.add_node("event_extract", build_event_extract_node(
        chapter, instruction, call_llm_event_extract, guard_text_event_extract, branch_id=branch_id,
    ))
    g.add_node("profile_mutate", build_profile_mutate_node(
        chapter, call_llm_profile_mutate, guard_text_profile_mutate,
    ))
    g.add_node(
        "suggest",
        _build_suggest_node(chapter, instruction, call_llm_suggest, core_xp, guard_text_suggest),
    )
    g.add_edge(START, "init_char")
    g.add_edge(START, "init_scene")
    # resolve_cast must wait on BOTH init_char and init_scene (not just init_char) even though
    # it only reads init_char's output -- LangGraph's per-node trigger check fires as soon as
    # ANY one trigger channel has a newer version (OR not AND across a node's listed triggers);
    # init_char/init_scene land in the same superstep (both direct children of START) so gating
    # resolve_cast on both keeps it a single clean fan-in, same reasoning that previously
    # applied to dialogue_draft directly. dialogue_draft/recall now each hang off resolve_cast
    # ALONE (single trigger, no OR-hazard possible) instead of off init_char/init_scene
    # directly -- this is what makes it safe for them to read resolve_cast's active_cast/
    # related_cast_this_turn output: a two-trigger node reading a value written by only ONE of
    # its triggers (e.g. dialogue_draft depending on {resolve_cast, init_scene} while only
    # resolve_cast writes active_cast) would refire the instant the OTHER trigger's stale
    # version is seen, before resolve_cast's own superstep has actually completed -- see spec
    # 2026-08-03-sandbox-cast-resolve-and-passerby-design.md section 2.4 for the full trace.
    g.add_edge("init_char", "resolve_cast")
    g.add_edge("init_scene", "resolve_cast")
    g.add_edge("resolve_cast", "dialogue_draft")
    g.add_edge("resolve_cast", "recall")
    g.add_edge("dialogue_draft", "prose")
    g.add_edge("recall", "prose")
    g.add_edge("prose", "derive_scene")
    g.add_edge("prose", "derive_char")
    g.add_edge("prose", "summary_fold")
    g.add_edge("prose", "event_extract")
    g.add_edge("event_extract", "profile_mutate")
    g.add_edge(["derive_char", "derive_scene", "profile_mutate", "summary_fold"], "suggest")
    g.add_edge("suggest", END)
    return g.compile(checkpointer=checkpointer)


def _compile_rewrite_graph(
    chapter: int, branch_id: str, feedback: str, write_turn: WriteTurn, *,
    call_llm_derive_char: CallLLM, call_llm_derive_scene: CallLLM,
    call_llm_summary_fold: CallLLM, call_llm_event_extract: CallLLM,
    call_llm_profile_mutate: CallLLM, call_llm_suggest: CallLLM,
    call_llm_identify: CallLLM | None, call_llm_dialogue_draft: CallLLM | None, checkpointer,
    guard_text_derive_char: GuardText, guard_text_derive_scene: GuardText,
    guard_text_summary_fold: GuardText, guard_text_event_extract: GuardText,
    guard_text_profile_mutate: GuardText,
    guard_text_suggest: GuardText,
):
    from repositories import get_plot_repo

    core_xp = get_plot_repo().chapter_core_xp(chapter)
    g = StateGraph(SandboxState)
    g.add_node("resolve_cast", _build_resolve_cast_rewrite_node(chapter))
    g.add_node("dialogue_draft", _build_dialogue_draft_rewrite_node(chapter, call_llm_dialogue_draft))
    g.add_node("recall", _build_recall_rewrite_node(chapter, branch_id))
    g.add_node("prose_rewrite", _build_prose_rewrite_node(chapter, branch_id, feedback, write_turn))
    g.add_node("derive_char", _build_derive_char_node(
        chapter, call_llm_derive_char, call_llm_identify, guard_text_derive_char, is_rewrite=True,
    ))
    g.add_node("derive_scene", _build_derive_scene_node(call_llm_derive_scene, guard_text_derive_scene))
    g.add_node("summary_fold", build_summary_fold_rewrite_node(call_llm_summary_fold, guard_text_summary_fold))
    g.add_node("event_extract", build_event_extract_rewrite_node(
        chapter, call_llm_event_extract, guard_text_event_extract, branch_id=branch_id,
    ))
    g.add_node("profile_mutate", build_profile_mutate_node(
        chapter, call_llm_profile_mutate, guard_text_profile_mutate, is_rewrite=True,
    ))
    g.add_node(
        "suggest_rewrite",
        _build_suggest_rewrite_node(chapter, call_llm_suggest, core_xp, guard_text_suggest),
    )
    g.add_edge(START, "resolve_cast")
    g.add_edge("resolve_cast", "dialogue_draft")
    g.add_edge("resolve_cast", "recall")
    g.add_edge("dialogue_draft", "prose_rewrite")
    g.add_edge("recall", "prose_rewrite")
    g.add_edge("prose_rewrite", "derive_scene")
    g.add_edge("prose_rewrite", "derive_char")
    g.add_edge("prose_rewrite", "summary_fold")
    g.add_edge("prose_rewrite", "event_extract")
    g.add_edge("event_extract", "profile_mutate")
    g.add_edge(["derive_char", "derive_scene", "profile_mutate", "summary_fold"], "suggest_rewrite")
    g.add_edge("suggest_rewrite", END)
    return g.compile(checkpointer=checkpointer)


def _compile_noop_graph(checkpointer):
    g = StateGraph(SandboxState)
    g.add_node("noop", lambda _state: {})
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    return g.compile(checkpointer=checkpointer)


def _accumulate_derive_pair(
    pending: dict[str, Any], node_name: str, delta: dict[str, Any],
) -> dict[str, Any] | None:
    """Buffers derive_char/derive_scene deltas until both fan-in siblings have reported."""
    if node_name == "derive_char":
        pending["states"] = delta["character_states"]
        pending["active_cast"] = sorted((delta.get("active_cast") or {}).keys())
    elif node_name == "derive_scene":
        pending["scene_state"] = delta["scene_state"]
    if "states" in pending and "scene_state" in pending:
        return pending
    return None


def _accumulate_event_pair(
    pending: dict[str, Any], node_name: str, delta: dict[str, Any],
) -> dict[str, Any] | None:
    if node_name == "summary_fold":
        pending["rolling_summary"] = delta.get("rolling_summary", "")
    elif node_name == "event_extract":
        pending["entries"] = delta.get("event_log_entries_this_turn") or []
    if "rolling_summary" in pending and "entries" in pending:
        return pending
    return None


async def run_turn(
    novel_id: str, chapter: int, text: str, *, write_turn: WriteTurn,
    call_llm_derive_char: CallLLM, call_llm_derive_scene: CallLLM,
    call_llm_summary_fold: CallLLM, call_llm_event_extract: CallLLM,
    call_llm_profile_mutate: CallLLM, call_llm_suggest: CallLLM,
    guard_text_derive_char: GuardText, guard_text_derive_scene: GuardText,
    guard_text_summary_fold: GuardText, guard_text_event_extract: GuardText,
    guard_text_profile_mutate: GuardText,
    guard_text_suggest: GuardText, submitted_directions: list[str] | None = None,
    call_llm_identify: CallLLM | None = None, call_llm_dialogue_draft: CallLLM | None = None,
    branch_id: str = LEGACY_BRANCH_ID,
) -> AsyncIterator[dict]:
    """Run one turn end to end as a stream of steps -- yields one dict per completed graph node
    (prose -> derive_state -> suggest), so the caller (message_hub.py) can broadcast each result
    the moment its LLM call finishes instead of waiting for the whole turn. Seeds a brand-new
    thread on first use, else starts a fresh pass over the existing checkpoint's accumulated
    state (each call still compiles a new graph with `text` baked into the node closures --
    this is not a resume of a previously-interrupted run). submitted_directions, if given, marks
    the previous round with whichever of its own suggestions match."""
    from engine.story_sandbox.state import seed_state

    checkpointer = await ensure_checkpointer(novel_id)
    config = {"configurable": {"thread_id": _thread_id(novel_id, chapter, branch_id)}}
    peek_graph = _compile_noop_graph(checkpointer)
    existing = await peek_graph.aget_state(config)
    if submitted_directions and existing and existing.values and existing.values.get("turns"):
        # Persist the previous round's mark right now, before the graph (and its
        # potentially long-running prose node) even starts -- otherwise a concurrent
        # history read (e.g. a remounted frontend tab) keeps seeing that round as
        # unsubmitted until this turn's prose finishes streaming, since that used to be
        # the only place this mark got folded into checkpointed state.
        marked_turns = _mark_prior_submitted(existing.values["turns"], submitted_directions)
        if marked_turns is not existing.values["turns"]:
            await peek_graph.aupdate_state(config, {"turns": marked_turns}, as_node="noop")
    is_opening = not (existing and existing.values and existing.values.get("turns"))
    input_state: SandboxState | dict[str, Any] = (
        seed_state() if not (existing and existing.values) else {
            "profile_mutate_feedback": None, "profile_mutate_directed_rewrite": False,
        }
    )
    graph = (
        _compile_opening_graph(
            chapter, branch_id, text, write_turn, checkpointer=checkpointer,
            call_llm_derive_char=call_llm_derive_char, call_llm_derive_scene=call_llm_derive_scene,
            call_llm_summary_fold=call_llm_summary_fold, call_llm_event_extract=call_llm_event_extract,
            call_llm_profile_mutate=call_llm_profile_mutate,
            call_llm_suggest=call_llm_suggest, call_llm_identify=call_llm_identify,
            call_llm_dialogue_draft=call_llm_dialogue_draft,
            guard_text_derive_char=guard_text_derive_char, guard_text_derive_scene=guard_text_derive_scene,
            guard_text_summary_fold=guard_text_summary_fold, guard_text_event_extract=guard_text_event_extract,
            guard_text_profile_mutate=guard_text_profile_mutate,
            guard_text_suggest=guard_text_suggest,
        )
        if is_opening else
        _compile_graph(
            chapter, branch_id, text, write_turn, checkpointer=checkpointer,
            call_llm_derive_char=call_llm_derive_char, call_llm_derive_scene=call_llm_derive_scene,
            call_llm_summary_fold=call_llm_summary_fold, call_llm_event_extract=call_llm_event_extract,
            call_llm_profile_mutate=call_llm_profile_mutate,
            call_llm_suggest=call_llm_suggest, call_llm_identify=call_llm_identify,
            call_llm_dialogue_draft=call_llm_dialogue_draft,
            guard_text_derive_char=guard_text_derive_char, guard_text_derive_scene=guard_text_derive_scene,
            guard_text_summary_fold=guard_text_summary_fold, guard_text_event_extract=guard_text_event_extract,
            guard_text_profile_mutate=guard_text_profile_mutate,
            guard_text_suggest=guard_text_suggest,
        )
    )
    pending_init: dict[str, Any] = {}
    pending_derive: dict[str, Any] = {}
    pending_recall: dict[str, Any] = {}
    pending_event: dict[str, Any] = {}
    initial_state_emitted = False
    async for update in graph.astream(input_state, config, stream_mode="updates"):
        for node_name, delta in update.items():
            if node_name == "init_char":
                pending_init["states"] = delta["initial_states_this_turn"]
            elif node_name == "init_scene":
                pending_init["scene_state"] = delta["initial_scene_state_this_turn"]
            elif node_name == "resolve_cast":
                pending_recall["active_cast"] = delta["active_cast"]
            elif node_name == "recall":
                pending_recall = {**pending_recall, **delta}
            if (
                not initial_state_emitted
                and "states" in pending_init and "scene_state" in pending_init
            ):
                #Broadcast the moment both init derivations land, instead of waiting for the
                #prose node (which can take much longer) -- otherwise the frontend gate on
                #pendingFields.initialStates keeps the whole live round hidden until prose is
                #already fully generated, defeating streaming for the chapter's opening round.
                initial_state_emitted = True
                yield {
                    "type": SandboxStepType.INITIAL_STATE,
                    "states": pending_init["states"], "scene_state": pending_init["scene_state"],
                }
            if node_name == "prose":
                yield {
                    "type": SandboxStepType.PROSE, "text": delta["final_text"],
                    "recall_context": pending_recall.get("recall_context_this_turn", ""),
                    "recalled_settings": pending_recall.get("recalled_settings_this_turn", []),
                    "active_cast": sorted((pending_recall.get("active_cast") or {}).keys()),
                }
            elif node_name in ("derive_char", "derive_scene"):
                combined = _accumulate_derive_pair(pending_derive, node_name, delta)
                if combined is not None:
                    yield {
                        "type": SandboxStepType.STATE,
                        "states": combined["states"], "scene_state": combined["scene_state"],
                        "active_cast": combined["active_cast"],
                    }
            elif node_name == "suggest":
                # "suggest" is the node that appends this turn's freshly-created round (see
                # _build_suggest_node) -- surfacing its id here is the only way message_hub.py can
                # thread it onto story_sandbox_suggestions/liveRound, since nothing else yielded
                # from this generator carries the new round's identity.
                yield {
                    "type": SandboxStepType.SUGGESTIONS, "options": delta["suggestions"],
                    "round_id": delta["turns"][-1].get("id"),
                }
            elif node_name in ("summary_fold", "event_extract"):
                combined = _accumulate_event_pair(pending_event, node_name, delta)
                if combined is not None:
                    yield {
                        "type": SandboxStepType.EVENT_LOG,
                        "entries": combined["entries"], "rolling_summary": combined["rolling_summary"],
                    }
            elif node_name == "profile_mutate":
                yield {
                    "type": SandboxStepType.PROFILE_MUTATION,
                    "mutation": (delta or {}).get("profile_mutation_this_turn"),
                    "relationship_mutation": (delta or {}).get("relationship_mutation_this_turn"),
                }


def _persistent_view(state: SandboxState) -> SandboxState:
    """Strip node-scratch keys (final_text/baseline_states/initial_states_this_turn) that may
    linger in the checkpoint after a graph run but are not part of the persisted API surface."""
    return {
        "turns": state.get("turns", []),
        "rolling_summary": state.get("rolling_summary", ""),
        "character_states": state.get("character_states", {}),
        "suggestions": state.get("suggestions", []),
        "scene_state": state.get("scene_state", {}),
        "character_profile": state.get("character_profile", {}),
        "recall_cooldown": state.get("recall_cooldown", {}),
        "active_cast": state.get("active_cast", {}),
        "relationship_overlay": state.get("relationship_overlay", {}),
        "background_cast": state.get("background_cast", []),
    }


async def _ensure_round_ids(graph: Any, config: dict, turns: list[Round]) -> list[Round]:
    """Lazily backfill+persist a stable `id` onto any round checkpointed before round-id
    targeting shipped (see rewrite_selection's round_id param) -- same lazy-migrate pattern as
    setup_chat_history's checkpoint backfill. A no-op (no extra write) once every round already
    has one."""
    if all(r.get("id") for r in turns):
        return turns
    backfilled: list[Round] = [
        r if r.get("id") else cast(Round, {**r, "id": uuid.uuid4().hex}) for r in turns
    ]
    await graph.aupdate_state(config, {"turns": backfilled}, as_node="noop")
    return backfilled


async def peek_state(novel_id: str, chapter: int, *, branch_id: str = LEGACY_BRANCH_ID) -> SandboxState:
    """Read current state without running a turn -- used by the history endpoint. A brand-new
    thread (no checkpoint yet) reads as a fresh seed_state rather than an error."""
    from engine.story_sandbox.state import seed_state

    checkpointer = await ensure_checkpointer(novel_id)
    graph = _compile_noop_graph(checkpointer)
    config = {"configurable": {"thread_id": _thread_id(novel_id, chapter, branch_id)}}
    existing = await graph.aget_state(config)
    if existing and existing.values:
        state = cast(SandboxState, existing.values)
        turns = await _ensure_round_ids(graph, config, state.get("turns") or [])
        return _persistent_view({**state, "turns": turns})
    return seed_state()


async def snapshot_state(
    novel_id: str, chapter: int, *, branch_id: str = LEGACY_BRANCH_ID,
) -> dict[str, Any]:
    """Raw, unfiltered state values (unlike peek_state's _persistent_view) for turn-cancel
    snapshot/restore. Empty dict means no checkpoint existed yet (this would-be turn was the
    chapter's opening turn)."""
    checkpointer = await ensure_checkpointer(novel_id)
    graph = _compile_noop_graph(checkpointer)
    config = {"configurable": {"thread_id": _thread_id(novel_id, chapter, branch_id)}}
    existing = await graph.aget_state(config)
    return dict(existing.values) if existing and existing.values else {}


async def restore_state(
    novel_id: str, chapter: int, values: dict[str, Any], *, branch_id: str = LEGACY_BRANCH_ID,
) -> None:
    """Full overwrite back to a snapshot captured by snapshot_state. Falls back to seed_state()
    when the snapshot is empty -- SandboxState has no reducer-annotated channels (verified: no
    Annotated/operator.add in state.py), so this is a safe full replace, same idiom as
    reset_chapter below."""
    from engine.story_sandbox.state import seed_state

    checkpointer = await ensure_checkpointer(novel_id)
    graph = _compile_noop_graph(checkpointer)
    config = {"configurable": {"thread_id": _thread_id(novel_id, chapter, branch_id)}}
    await graph.aupdate_state(config, values or seed_state(), as_node="noop")


async def fork_branch(
    novel_id: str, chapter: int, source_branch_id: str, dest_branch_id: str,
) -> dict[str, str]:
    """Copies source_branch_id's full checkpoint state into dest_branch_id's (new, previously
    unused) thread -- the engine-level half of "new branch forks from the current one" (see
    docs/superpowers/specs/2026-07-28-sandbox-story-branches-design.md, "Fork 时的记忆隔离").

    Every round's event_log_entries[].id is rewritten to a fresh uuid before the copy is written, and
    the old_id -> new_id mapping is returned so the caller (message_hub.py) can duplicate the
    matching sandbox_event_log.json/vector-memory entries under those same new ids. This is not
    optional cleanup: event_log.json's "replace on rewrite" and the vector-memory store's upsert are both keyed
    globally by id, not scoped by branch -- if the copy kept the source's ids, then the FIRST
    time either branch rewrites its last round after forking, it would silently overwrite the
    other branch's memory entry sharing that id.

    Returns {} (dest thread left untouched) when the source has no state yet -- forking a blank
    branch is a no-op, not an error."""
    source_state = await peek_state(novel_id, chapter, branch_id=source_branch_id)
    turns = source_state.get("turns") or []
    if not turns:
        return {}

    id_remap: dict[str, str] = {}
    new_turns: list[Round] = []
    for round_ in turns:
        entries = round_event_log_entries(round_)
        if not entries:
            new_turns.append(round_)
            continue
        remapped_entries: list[dict] = []
        for entry in entries:
            old_id = entry.get("id")
            if not old_id:
                remapped_entries.append(entry)
                continue
            new_id = str(uuid.uuid4())
            id_remap[old_id] = new_id
            remapped_entries.append({**entry, "id": new_id})
        new_turns.append(cast(Round, {**round_, "event_log_entries": remapped_entries}))

    new_state = {**source_state, "turns": new_turns}
    await restore_state(novel_id, chapter, new_state, branch_id=dest_branch_id)
    return id_remap


async def reset_chapter(novel_id: str, chapter: int, *, branch_id: str = LEGACY_BRANCH_ID) -> None:
    """Overwrite this chapter's thread back to a fresh seed_state -- not file/row deletion.
    seed_state returns every SandboxState key, so this is a full, unambiguous overwrite via
    aupdate_state (the same LangGraph API setup_chat/agent.py's _drive_stream already uses).
    Only this chapter's thread is touched; other chapters' sandbox sessions are untouched.

    Also strips this chapter's own entries from the two per-novel memory stores (event_log.json,
    the vector-memory collection) -- both persist independently of the checkpoint and are keyed
    by chapter, not by thread_id, so resetting the checkpoint alone would leave this chapter's
    stale memories recallable by recall_relevant_context (whose cross-chapter recall itself stays
    intentional -- see recall.py -- only this chapter's own history is meant to be wiped here).
    Memory cleanup is dispatched as a background task so the HTTP reset can return as soon as
    the checkpoint overwrite lands."""
    from engine.story_sandbox.state import seed_state

    checkpointer = await ensure_checkpointer(novel_id)
    graph = _compile_noop_graph(checkpointer)
    config = {"configurable": {"thread_id": _thread_id(novel_id, chapter, branch_id)}}
    await graph.aupdate_state(config, seed_state(), as_node="noop")

    async def _cleanup() -> None:
        await delete_entries_for_chapter(chapter, branch_id)
        await get_sandbox_vector_memory_repo().delete_chapter(chapter, branch_id)

    task = asyncio.create_task(_cleanup())
    _pending_cleanup_tasks.add(task)
    task.add_done_callback(_pending_cleanup_tasks.discard)


async def wait_for_pending_sandbox_cleanup() -> None:
    """Test-only seam: wait for all reset_chapter background cleanup tasks to finish so
    assertions can run deterministically after cleanup. Production never calls this --
    reset_chapter itself is fire-and-forget for the memory wipe."""
    pending = list(_pending_cleanup_tasks)
    if pending:
        await asyncio.gather(*pending)


async def regenerate_suggestions(
    novel_id: str, chapter: int, call_llm_suggest: CallLLM, *, guard_text: GuardText,
    hint: str = "", run_skill_agent: RunSkillAgent | None = None,
    branch_id: str = LEGACY_BRANCH_ID,
) -> list[str]:
    """Re-roll just the most recent round's suggestions -- one LLM call, reusing that round's
    already-persisted prose/character_states (no new prose, no state re-derivation). Returns
    [] without touching the checkpoint if there are no rounds yet.

    Runs a fresh recall_relevant_context pass (same turn_index/cooldown contract as
    rewrite_last_round) using the round instruction, optional hint, and finalized prose before
    calling suggest_directions -- not the round's previously persisted recall_context.

    A hint of the form `/skill-name ...` that matches a registered kind=plot-extension skill
    routes to run_skill_suggestion instead (only when run_skill_agent is given) -- an
    unrecognized /name, or a plain hint with no leading slash, always falls back to this
    function's normal suggest_directions call."""
    from engine.story_sandbox.state import seed_state

    checkpointer = await ensure_checkpointer(novel_id)
    graph = _compile_noop_graph(checkpointer)
    config = {"configurable": {"thread_id": _thread_id(novel_id, chapter, branch_id)}}
    existing = await graph.aget_state(config)
    state: SandboxState = (
        cast(SandboxState, existing.values) if existing and existing.values else seed_state()
    )
    if not state["turns"]:
        return []

    from repositories import get_plot_repo

    from engine.story_sandbox.cast import resolve_character_cards, resolve_related_cast

    last_round = state["turns"][-1]
    core_xp = get_plot_repo().chapter_core_xp(chapter)
    # regenerate_suggestions only ever re-rolls turns[-1] (the most recent, still-current round
    # -- see this function's own docstring), so the top-level, currently-persisted active_cast
    # is exactly the right "who's present" set for it, same source of truth _build_suggest_node
    # uses for a fresh (non-regenerated) round.
    present_names = set(state.get("active_cast") or {})
    present_states = {
        k: v for k, v in last_round["character_states"].items() if k in present_names
    }
    cards = resolve_character_cards(chapter, sorted(present_states))
    related_names = [n for n in resolve_related_cast(present_names, state.get("relationship_overlay") or {}) if n not in present_names]
    related_cards = resolve_character_cards(chapter, related_names)
    recall_block, recalled_settings, updated_cooldown = await _recall_for_round_rewrite(
        state, chapter, branch_id, extra_scan_text=hint, include_current_prose=True,
    )

    skill_name, skill_hint = parse_skill_hint(hint) if run_skill_agent is not None else (None, hint)
    if skill_name is not None and run_skill_agent is not None:
        new_suggestions = await run_skill_suggestion(
            skill_name, last_round["prose"], present_states, run_skill_agent,
            hint=skill_hint, core_xp=core_xp, cards=cards, related_cards=related_cards,
            recall_block=recall_block,
        )
    else:
        new_suggestions = await suggest_directions(
            last_round["prose"], present_states, call_llm_suggest,
            hint=hint, core_xp=core_xp, cards=cards, related_cards=related_cards,
            recall_block=recall_block,
        )

    guarded_suggestions = await _guard_list(new_suggestions, guard_text)
    updated_last: Round = {
        **last_round,
        "suggestions": guarded_suggestions,
        "recall_context": recall_block,
        "recalled_settings": recalled_settings,
    }
    new_turns = [*state["turns"][:-1], updated_last]
    new_state: SandboxState = {
        **state,
        "turns": new_turns,
        "suggestions": guarded_suggestions,
        "recall_cooldown": updated_cooldown,
    }
    await graph.aupdate_state(config, new_state, as_node="noop")
    return guarded_suggestions


async def rewrite_profile_mutation(
    novel_id: str, chapter: int, feedback: str,
    call_llm_profile_mutate: CallLLM, guard_text: GuardText,
    branch_id: str = LEGACY_BRANCH_ID,
) -> tuple[dict[str, dict] | None, dict[str, dict] | None, int]:
    """Re-derive profile_mutation and relationship_mutation for turns[-1] only, steered by
    free-text user feedback -- no prose re-generation, no state re-derivation. Returns
    (profile_mutation, relationship_mutation, round_index) where round_index is 0-based.
    Raises ValueError when there are no rounds yet.

    Runs a fresh recall_relevant_context pass (same turn_index/cooldown contract as
    rewrite_last_round) using the round instruction, feedback, and finalized prose, and
    injects the result into the profile_mutate LLM user prompt."""
    from engine.story_sandbox.state import seed_state

    checkpointer = await ensure_checkpointer(novel_id)
    graph = _compile_noop_graph(checkpointer)
    config = {"configurable": {"thread_id": _thread_id(novel_id, chapter, branch_id)}}
    existing = await graph.aget_state(config)
    state: SandboxState = (
        cast(SandboxState, existing.values) if existing and existing.values else seed_state()
    )
    turns = await _ensure_round_ids(graph, config, state.get("turns") or [])
    if not turns:
        raise ValueError("没有可重写的轮次")

    last_round = turns[-1]
    recall_block, _, updated_cooldown = await _recall_for_round_rewrite(
        {**state, "turns": turns}, chapter, branch_id,
        extra_scan_text=feedback, include_current_prose=True,
    )
    node_input: SandboxState = {
        **state,
        "turns": turns,
        "final_text": last_round["prose"],
        "profile_mutate_feedback": feedback,
        "profile_mutate_directed_rewrite": True,
        "event_log_entries_this_turn": round_event_log_entries(last_round),
        "recall_context_this_turn": recall_block,
    }
    node = build_profile_mutate_node(
        chapter, call_llm_profile_mutate, guard_text, is_rewrite=True,
    )
    delta = await node(node_input)
    profile_mutation = delta.get("profile_mutation_this_turn")
    relationship_mutation = delta.get("relationship_mutation_this_turn")

    updated_last: Round = {
        **last_round,
        "profile_mutation": profile_mutation,
        "relationship_mutation": relationship_mutation,
    }
    new_turns = [*turns[:-1], updated_last]
    await graph.aupdate_state(
        config,
        {
            **state, "turns": new_turns,
            "profile_mutate_feedback": None, "profile_mutate_directed_rewrite": False,
            "recall_cooldown": updated_cooldown,
        },
        as_node="noop",
    )
    return profile_mutation, relationship_mutation, len(turns) - 1


async def rewrite_selection(
    novel_id: str, chapter: int, original_text: str, anchor_offset: int, feedback: str,
    *, call_llm: CallLLM, guard_text: GuardText, style_card: str = "",
    round_id: str | None = None, branch_id: str = LEGACY_BRANCH_ID,
) -> str:
    """Locate `original_text` inside the target round's prose (`round_id` when given, else the
    chapter's latest round -- nearest occurrence to `anchor_offset` when it appears more than
    once, see `_locate_fragment`), ask the LLM to rewrite just that fragment, run the replacement
    through `guard_text`, splice it back in, and persist. Returns the round's full new prose. No
    character/scene-state, event-log, or profile-mutation re-derivation runs -- this is a
    wording-only patch. Raises ValueError when there are no rounds yet, `round_id` no longer
    exists (chapter reset from under it), or `original_text` can't be located.

    `round_id` lets this safely target a round that is no longer `turns[-1]` by the time it runs
    -- the frontend queues a selection-rewrite instead of blocking while a busy-guarded task (a
    new turn, another rewrite, ...) is running, and that task may finish (e.g. appending a fresh
    round) before this one executes. is_story_sandbox_busy() still fully serializes every
    story_sandbox_* task including this one, so there is no concurrent writer to race against by
    the time this actually runs -- round_id only needs to survive the queue, not a live race."""
    from engine.story_sandbox.state import seed_state

    checkpointer = await ensure_checkpointer(novel_id)
    graph = _compile_noop_graph(checkpointer)
    config = {"configurable": {"thread_id": _thread_id(novel_id, chapter, branch_id)}}
    existing = await graph.aget_state(config)
    state: SandboxState = (
        cast(SandboxState, existing.values) if existing and existing.values else seed_state()
    )
    turns = await _ensure_round_ids(graph, config, state.get("turns") or [])
    if not turns:
        raise ValueError("没有可重写的轮次")

    target_id = round_id or turns[-1]["id"]
    target_idx = next((i for i, r in enumerate(turns) if r.get("id") == target_id), None)
    if target_idx is None:
        raise ValueError("目标轮次已不存在，可能已被清空或重置")
    target = turns[target_idx]
    prose = target["prose"]
    start, end = _locate_fragment(prose, original_text, anchor_offset)

    system, user = _build_selection_rewrite_prompt(style_card, prose, original_text, feedback)
    raw = await call_llm(system, user)
    guarded = await guard_text(_extract_rewritten_fragment(raw))
    new_prose = prose[:start] + guarded + prose[end:]

    new_turns = [*turns[:target_idx], {**target, "prose": new_prose}, *turns[target_idx + 1:]]
    await graph.aupdate_state(config, {"turns": new_turns}, as_node="noop")
    return new_prose


async def rewrite_last_round(
    novel_id: str, chapter: int, feedback: str, *, write_turn: WriteTurn,
    call_llm_derive_char: CallLLM, call_llm_derive_scene: CallLLM,
    call_llm_summary_fold: CallLLM, call_llm_event_extract: CallLLM,
    call_llm_profile_mutate: CallLLM, call_llm_suggest: CallLLM,
    guard_text_derive_char: GuardText, guard_text_derive_scene: GuardText,
    guard_text_summary_fold: GuardText, guard_text_event_extract: GuardText,
    guard_text_profile_mutate: GuardText,
    guard_text_suggest: GuardText,
    call_llm_identify: CallLLM | None = None, call_llm_dialogue_draft: CallLLM | None = None,
    branch_id: str = LEGACY_BRANCH_ID,
) -> AsyncIterator[dict]:
    """Regenerate the chapter's most recent round's prose in place, steered by free-text
    feedback about the writing itself (not the scene) -- the round's original `instruction` is
    reused unchanged. Plain coroutine returning an async generator: raises ValueError on `await`
    if there are no rounds yet, before any streaming starts."""
    checkpointer = await ensure_checkpointer(novel_id)
    graph = _compile_rewrite_graph(
        chapter, branch_id, feedback, write_turn, checkpointer=checkpointer,
        call_llm_derive_char=call_llm_derive_char, call_llm_derive_scene=call_llm_derive_scene,
        call_llm_summary_fold=call_llm_summary_fold, call_llm_event_extract=call_llm_event_extract,
        call_llm_profile_mutate=call_llm_profile_mutate,
        call_llm_suggest=call_llm_suggest, call_llm_identify=call_llm_identify,
        call_llm_dialogue_draft=call_llm_dialogue_draft,
        guard_text_derive_char=guard_text_derive_char, guard_text_derive_scene=guard_text_derive_scene,
        guard_text_summary_fold=guard_text_summary_fold, guard_text_event_extract=guard_text_event_extract,
        guard_text_profile_mutate=guard_text_profile_mutate,
        guard_text_suggest=guard_text_suggest,
    )
    config = {"configurable": {"thread_id": _thread_id(novel_id, chapter, branch_id)}}
    existing = await graph.aget_state(config)
    if not (existing and existing.values and existing.values.get("turns")):
        raise ValueError("没有可重写的轮次")
    return _stream_rewrite(graph, config)


async def _stream_rewrite(graph, config: dict) -> AsyncIterator[dict]:
    pending_derive: dict[str, Any] = {}
    pending_recall: dict[str, Any] = {}
    pending_event: dict[str, Any] = {}
    async for update in graph.astream(
        {"profile_mutate_feedback": None, "profile_mutate_directed_rewrite": False}, config, stream_mode="updates",
    ):
        for node_name, delta in update.items():
            if node_name == "resolve_cast":
                pending_recall["active_cast"] = delta["active_cast"]
            elif node_name == "recall":
                pending_recall = {**pending_recall, **delta}
            if node_name == "prose_rewrite":
                yield {
                    "type": SandboxStepType.PROSE, "text": delta["final_text"],
                    "initial_states": None, "initial_scene_state": None,
                    "recall_context": pending_recall.get("recall_context_this_turn", ""),
                    "recalled_settings": pending_recall.get("recalled_settings_this_turn", []),
                    "active_cast": sorted((pending_recall.get("active_cast") or {}).keys()),
                }
            elif node_name in ("derive_char", "derive_scene"):
                combined = _accumulate_derive_pair(pending_derive, node_name, delta)
                if combined is not None:
                    yield {
                        "type": SandboxStepType.STATE,
                        "states": combined["states"], "scene_state": combined["scene_state"],
                        "active_cast": combined["active_cast"],
                    }
            elif node_name in ("summary_fold", "event_extract"):
                combined = _accumulate_event_pair(pending_event, node_name, delta)
                if combined is not None:
                    yield {
                        "type": SandboxStepType.EVENT_LOG,
                        "entries": combined["entries"], "rolling_summary": combined["rolling_summary"],
                    }
            elif node_name == "profile_mutate":
                yield {
                    "type": SandboxStepType.PROFILE_MUTATION,
                    "mutation": (delta or {}).get("profile_mutation_this_turn"),
                    "relationship_mutation": (delta or {}).get("relationship_mutation_this_turn"),
                }
            elif node_name == "suggest_rewrite":
                yield {"type": SandboxStepType.SUGGESTIONS, "options": delta["suggestions"]}
