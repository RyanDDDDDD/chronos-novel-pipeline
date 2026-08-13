"""Per-chapter sandbox conversation state: the shape LangGraph's checkpointer persists across
turns. character_states starts empty on a brand-new thread -- no lore-record or cast-card
injection. A chapter's opening round runs a dedicated initial-state derivation
(state_derive.py::derive_initial_states) before any prose is written -- captured on that round's
initial_states field, distinct from character_states (the post-write snapshot every round has).
Every later round leaves initial_states None; only character_states keeps evolving via
derive_character_states."""
from __future__ import annotations

from enum import StrEnum
from typing import Any, NotRequired, TypedDict

CharacterState = dict[str, Any]
SceneState = dict[str, Any]

LEGACY_BRANCH_ID = "legacy"  # sentinel branch id for a chapter's pre-existing (pre-branching-
    # feature) checkpoint thread -- resolves to the old two-segment thread id
    # f"{novel_id}:{chapter}" instead of the three-segment f"{novel_id}:{chapter}:{branch_id}"
    # every other branch uses. Deterministic (not a random uuid) so it's self-healing if the
    # branch registry file is ever lost. See engine/story_sandbox/branches.py and
    # graph.py::_thread_id.


class SandboxStepType(StrEnum):
    """Tags one completed graph-node's output as run_turn()/rewrite_last_round() stream it --
    member value = the wire-format string message_hub.py compares against (StrEnum, not a raw
    string comparison, per project convention)."""

    PROSE = "prose"
    INITIAL_STATE = "initial_state"
    STATE = "state"
    SUGGESTIONS = "suggestions"
    EVENT_LOG = "event_log"
    PROFILE_MUTATION = "profile_mutation"


class SandboxLiveMode(StrEnum):
    """Which start_story_sandbox_* flow produced the in-flight round MessageHub is currently
    caching for live-turn recovery (see MessageHub._story_sandbox_live)."""

    TURN = "turn"
    REWRITE = "rewrite"
    SUGGESTIONS_REGENERATE = "suggestions_regenerate"
    SELECTION_REWRITE = "selection_rewrite"
    PROFILE_MUTATION_REWRITE = "profile_mutation_rewrite"


class Round(TypedDict):
    id: NotRequired[str]  # stable identity for this round, assigned once at creation and carried
        # over verbatim by a whole-round rewrite (which replaces content, not identity) -- lets
        # selection-rewrite target this exact round even after later rounds get appended, and lets
        # a request queued while busy still resolve correctly once it fires. NotRequired only
        # because rounds persisted before this field shipped lack it (see graph.py's lazy
        # backfill-and-persist in peek_state/rewrite_selection, mirroring setup_chat_history's
        # checkpoint-backfill convention).
    instruction: str                              # director's input that turn
    prose: str                                      # this feature's finalized (post-guard) output that turn
    character_states: dict[str, CharacterState]    # snapshot AFTER this round
    suggestions: list[str]                          # shown after this round
    initial_states: dict[str, CharacterState] | None  # pre-write initial derivation; only non-None on a chapter's opening round
    scene_state: SceneState                         # snapshot AFTER this round -- mirrors character_states
    initial_scene_state: SceneState | None          # mirrors initial_states -- only non-None on a chapter's opening round
    submitted_directions: NotRequired[list[str] | None]  # which of THIS round's suggestions the next round's instruction was built from
    event_log_entries: NotRequired[list[dict]]  # keyword-recall entries for THIS round (see event_log.py), written directly when _build_suggest_node/_build_suggest_rewrite_node construct the round -- empty when the fold produced no events this round
    event_log_entry: NotRequired[dict | None]  # legacy singular field; readers should use round_event_log_entries()
    profile_mutation: NotRequired[dict[str, dict] | None]  # this round's character-profile mutation (name -> changed fields), or None -- written directly when _build_suggest_node/_build_suggest_rewrite_node construct new_round, same "transient scratch -> written straight onto the round" pattern as event_log_entry
    relationship_mutation: NotRequired[dict[str, dict] | None]  # this round's relationship-graph-edge proposals ("from→to" -> edge dict), or None -- same deferred-commit lifecycle as profile_mutation (see profile_mutate.py), written directly when _build_suggest_node/_build_suggest_rewrite_node construct new_round
    rolling_summary_after: NotRequired[str]  # rolling_summary snapshot right after THIS round's own fold -- lets a later rewrite of this round recompute from the correct pre-fold baseline (turns[-2]) instead of the already-stale current state["rolling_summary"]
    recall_context: NotRequired[str]  # recall_relevant_context(instruction) result captured at prose-write time; always a string ('' when nothing was recalled), never absent on a round produced after this feature ships
    recalled_settings: NotRequired[list[dict]]  # structured subset of recall_context -- just the world-bible named entries (factions/geography/races/power_system) that matched this round, for the frontend to highlight separately from event-log history (see RecalledSettingsBubble). Always a list ([] when nothing matched), never absent on a round produced after this feature ships; NotRequired only because rounds persisted before this feature shipped lack the key entirely.


class SandboxState(TypedDict, total=False):
    """Per-chapter sandbox conversation state persisted by LangGraph's checkpointer.
    final_text/baseline_states/initial_states_this_turn/baseline_scene_state/
    initial_scene_state_this_turn/event_log_entries_this_turn/instruction_this_turn are transient,
    node-to-node scratch fields written by prose/prose_rewrite and read by
    derive_state/event_log/profile_mutate/suggest -- they don't carry meaning once a turn's
    graph run completes and are absent from seed_state()."""

    turns: list[Round]
    rolling_summary: str
    character_states: dict[str, CharacterState]
    suggestions: list[str]
    final_text: str
    baseline_states: dict[str, CharacterState]
    initial_states_this_turn: dict[str, CharacterState] | None
    scene_state: SceneState
    baseline_scene_state: SceneState
    initial_scene_state_this_turn: SceneState | None
    event_log_entries_this_turn: list[dict]
    recall_context_this_turn: str  # transient, node-to-node scratch field -- same category as event_log_entry_this_turn
    recalled_settings_this_turn: list[dict]  # transient, node-to-node scratch field -- same category as recall_context_this_turn, written by the same prose nodes that write recall_context_this_turn
    character_profile: dict[str, dict]  # accumulated session-local profile-mutation overlay ({name: {field: value}}), persisted by the checkpointer, NEVER written to character_timeline/archive.json
    profile_mutation_this_turn: dict[str, dict] | None  # transient scratch, same category as event_log_entry_this_turn -- this turn's newly-produced mutation only
    relationship_overlay: dict[str, dict]  # accumulated session-local relationship-graph-edge overlay ({"from→to": edge dict}, same key format as relationship_graph.py::load_graph), persisted by the checkpointer, NEVER written to relationship_edges.jsonl -- merged over the static base graph at read time (see relationship_graph.merge_overlay), same baseline+overlay pattern as character_profile
    relationship_mutation_this_turn: dict[str, dict] | None  # transient scratch, same category as profile_mutation_this_turn -- this turn's newly-proposed/updated edges only
    recall_cooldown: dict[str, int]  # item cooldown key -> turn_index last recalled at; per-
        # chapter session state, persisted by the checkpointer alongside everything else
    active_cast: dict[str, int]  # character name -> last-seen turn_index (director instruction
        # or previous turn's prose mentioned them); see cast_tracker.py::update_active_cast for
        # how this is maintained and cast.py::render_dynamic_cast_block for how it's rendered
    instruction_this_turn: str  # transient, node-to-node scratch field written by
        # prose/prose_opening/prose_rewrite, read by cast_tracker.chapter_cast_ceiling (chapter
        # mode's active_cast/character_states/character_profile growth cap) -- same category as
        # final_text/baseline_states, absent from seed_state()
    dialogue_draft_this_turn: str  # transient, node-to-node scratch field written by the
        # dialogue_draft node (see graph.py::_build_dialogue_draft_node and its opening/rewrite
        # variants), read by prose/prose_opening/prose_rewrite -- same category as
        # instruction_this_turn, absent from seed_state()
    related_cast_this_turn: list[str]  # transient, node-to-node scratch field written by the
        # resolve_cast node (see graph.py::_build_resolve_cast_node and its opening/rewrite
        # variants) -- characters related to active_cast via the relationship graph, computed
        # once per turn and read by dialogue_draft/prose instead of each independently re-
        # calling cast.resolve_related_cast. Same category as dialogue_draft_this_turn, absent
        # from seed_state().
    background_cast: list[str]  # names scan_characters(final_text) caught this turn that the
        # identify call did NOT confirm as actually on stage -- i.e. mentioned/background-only
        # (recollection, hearsay, a name in passing), never a claim they're present. Replaced
        # wholesale every turn by derive_char (not decayed like active_cast/passerby_names),
        # read by resolve_cast/resolve_cast_rewrite to fold into related_cast_this_turn so the
        # NEXT turn's prompt (and the frontend's 相关角色 panel) can reference them. See
        # docs/superpowers/specs/2026-08-12-sandbox-nonopening-cast-state-redesign-design.md.
    passerby_names: list[str]  # names currently in active_cast that are NOT lore-registered
        # characters (build_character_vocab() misses) -- background/incidental characters like
        # "路边大爷" that got a state derived but have no persona card. Decays in lockstep with
        # active_cast's own ABSENCE_LIMIT pruning (see graph.py::_build_derive_char_node and
        # _build_init_char_node), never a separately-tracked lifecycle. Persisted by the
        # checkpointer alongside active_cast.
    known_roster_fallback_this_turn: list[str]  # transient, node-to-node scratch field written by
        # init_char when the opening instruction named nobody and the identify layer had a non-
        # empty roster to fall back on; read by prose_opening to render a plain "known characters,
        # don't invent new ones" guardrail instead of full persona cards. Same category as
        # dialogue_draft_this_turn, absent from seed_state().
    instruction_grounding_graph_this_turn: str  # transient subgraph block when
        # known_roster_fallback fires but the instruction mentions a group/social-network cue;
        # read by prose_opening/build_sandbox_system_prompt. Same category as
        # known_roster_fallback_this_turn.
    instruction_grounding_briefs_this_turn: str  # transient distilled brief block paired with
        # instruction_grounding_graph_this_turn. Same category as known_roster_fallback_this_turn.
    profile_mutate_feedback: str | None  # transient scratch for directed profile/relationship
        # mutation rewrite (graph.py::rewrite_profile_mutation) -- cleared once the rewrite
        # finishes or a fresh turn/whole-round rewrite starts, same category as
        # instruction_this_turn, absent from seed_state().
    profile_mutate_directed_rewrite: bool  # transient flag set only by rewrite_profile_mutation --
        # forces the LLM call even when feedback is empty and event_log would otherwise skip
        # this node; cleared together with profile_mutate_feedback.


def seed_state() -> SandboxState:
    """Initial state for a brand-new thread."""
    return {
        "turns": [], "rolling_summary": "", "character_states": {}, "suggestions": [],
        "scene_state": {}, "character_profile": {}, "recall_cooldown": {}, "active_cast": {},
        "relationship_overlay": {}, "passerby_names": [], "background_cast": [],
    }
