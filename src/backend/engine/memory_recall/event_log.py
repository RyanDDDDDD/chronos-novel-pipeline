"""story_sandbox event journal: runs every round immediately (real-time, no window-aging delay)
and persists an entity-tagged event entry for later keyword recall. See
docs/superpowers/specs/2026-07-14-story-sandbox-event-log-realtime-and-vector-memory-design.md
§5 (note: that spec's original "batch every 20 rounds" vector-memory archiving trigger has since
been replaced by _archive_previous_round's per-turn "archive once superseded" trigger, to close a
staleness gap the batch design had -- see that function's docstring)."""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any, Protocol

from repositories import get_sandbox_vector_memory_repo
from repositories.entities import MemoryOrigin
from repositories.sqlite_store import SqliteStore
from utils.paths import active_novel_id

from engine.story_sandbox.state import Round, SandboxState
from engine.story_sandbox.summary_fold import CallLLM, EventResult

GuardText = Callable[[str], Awaitable[str]]


class _EventLike(Protocol):
    event: str | None
    time: str | None
    location: str | None
    entities: list[str]
    characters: list[str]
    summary: str

_log = logging.getLogger(__name__)
_event_log_lock = asyncio.Lock()
_COOLDOWN_DOC_KEY = "recall_cooldown"


def _store() -> SqliteStore:
    return SqliteStore(active_novel_id())


def _load_entries_from_db() -> list[dict]:
    from repositories.engine import session_for
    from repositories.models import SandboxEvent
    from sqlmodel import col, select

    with session_for() as s:
        rows = s.exec(
            select(SandboxEvent.entry_json)
            .order_by(col(SandboxEvent.chapter), col(SandboxEvent.turn_index))
        ).all()
    return [dict(r) for r in rows if isinstance(r, dict)]


def _save_entries_to_db(entries: list[dict]) -> None:
    from repositories.engine import engine_for_novel
    from repositories.models import SandboxEvent
    from sqlalchemy import delete
    from sqlmodel import Session

    with Session(engine_for_novel(active_novel_id())) as s:
        s.exec(delete(SandboxEvent))
        for entry in entries:
            entry_id = entry.get("id")
            if not entry_id:
                continue
            s.add(SandboxEvent(
                id=str(entry_id),
                chapter=int(entry.get("chapter", 0)),
                turn_index=int(entry.get("turn_index", 0)),
                entry_json=entry,
            ))
        s.commit()


def load_event_log() -> dict:
    return {"entries": _load_entries_from_db()}


def entries_in_scope(
    entries: list[dict], chapter: int, branch_id: str | None, origin: str,
) -> list[dict]:
    """Entries visible at this point in the story: past/current chapters only (never future --
    逻辑断崖：本章还没写到那里), either canon (branch_id None) or this exact branch, AND tagged
    with the caller's own origin (author_loop only ever sees its own canon entries, sandbox only
    its own -- see recall_relevant_context). branch_id itself being None disables the branch
    filter (author_loop has no branch concept). Entries predating the origin field (missing key)
    are treated as MemoryOrigin.SANDBOX."""
    return [
        e for e in entries
        if isinstance(e, dict) and e.get("id") and e.get("chapter", 0) <= chapter
        and (branch_id is None or e.get("branch_id") in (None, branch_id))
        and (e.get("origin") or MemoryOrigin.SANDBOX) == origin
    ]


def list_memory_archive(chapter: int, branch_id: str | None, origin: str) -> list[dict]:
    """Full scoped entry list for manual browsing (story_sandbox right panel) -- unlike
    recall_relevant_context, no keyword/semantic filtering: every in-scope entry, newest first."""
    entries = load_event_log().get("entries") or []
    scoped = entries_in_scope(entries, chapter, branch_id, origin)
    return sorted(scoped, key=lambda e: (e.get("chapter", 0), e.get("turn_index", 0)), reverse=True)


def load_recall_cooldown() -> dict[str, int]:
    data = _store().get_doc(_COOLDOWN_DOC_KEY, "")
    if isinstance(data, dict):
        return {str(k): int(v) for k, v in data.items() if isinstance(v, int)}
    return {}


def save_recall_cooldown(cooldown: dict[str, int]) -> None:
    try:
        _store().save_doc(_COOLDOWN_DOC_KEY, "", cooldown)
    except OSError:
        _log.exception("recall cooldown ledger write failed")


def _replace_event_entry_sync(old_id: str | None, new_entry: dict | None) -> None:
    """old_id non-empty -> drop any entry with that id first; new_entry non-empty -> append. The
    two act independently, giving replace/pure-append/pure-delete depending on which args are
    given -- append_event_entry(entry) is just replace_event_entry(None, entry)."""
    entries = _load_entries_from_db()
    if old_id:
        entries = [e for e in entries if e.get("id") != old_id]
    if new_entry is not None:
        entries.append(new_entry)
    try:
        _save_entries_to_db(entries)
    except OSError:
        _log.exception("story_sandbox event log write failed")


async def replace_event_entry(old_id: str | None, new_entry: dict | None) -> None:
    async with _event_log_lock:
        await asyncio.to_thread(_replace_event_entry_sync, old_id, new_entry)


async def append_event_entry(entry: dict) -> None:
    await replace_event_entry(None, entry)


def _append_event_entries_sync(entries: list[dict]) -> None:
    if not entries:
        return
    combined = _load_entries_from_db() + entries
    try:
        _save_entries_to_db(combined)
    except OSError:
        _log.exception("story_sandbox event log write failed")


async def append_event_entries(entries: list[dict]) -> None:
    if not entries:
        return
    async with _event_log_lock:
        await asyncio.to_thread(_append_event_entries_sync, entries)


def _replace_event_entries_sync(old_ids: list[str], new_entries: list[dict]) -> None:
    old_set = set(old_ids)
    kept = [e for e in _load_entries_from_db() if e.get("id") not in old_set]
    combined = kept + list(new_entries)
    try:
        _save_entries_to_db(combined)
    except OSError:
        _log.exception("story_sandbox event log write failed")


async def replace_event_entries(old_ids: list[str], new_entries: list[dict]) -> None:
    if not old_ids and not new_entries:
        return
    async with _event_log_lock:
        await asyncio.to_thread(_replace_event_entries_sync, old_ids, new_entries)


def round_event_log_entries(round_: Round | dict[str, Any]) -> list[dict]:
    """Read a round's persisted event entries, supporting legacy singular field."""
    plural = round_.get("event_log_entries")
    if isinstance(plural, list):
        return [e for e in plural if isinstance(e, dict) and e.get("summary")]
    singular = round_.get("event_log_entry")
    if isinstance(singular, dict) and singular.get("summary"):
        return [singular]
    return []


def _delete_entries_for_chapter_sync(chapter: int, branch_id: str | None = None) -> None:
    """Strips entries belonging to this chapter (and, when branch_id is given, only this
    branch's own entries -- canon entries with branch_id None and sibling branches' entries are
    left untouched). Used by reset_chapter (graph.py) so a deleted branch's stale entries stop
    bleeding into recall_relevant_context's keyword-hit path. Cross-chapter recall itself stays
    intentional (see recall.py) -- only this chapter's own history is ever a candidate here.

    Any branch-scoped reset/delete also strips entries with the "branch_id" key entirely absent
    from the dict, regardless of which branch_id was passed: those predate the branch_id field
    (added 2026-07-28, see git history) and never legitimately belong to any one branch -- the
    single pre-branching thread they came from usually isn't even the branch a chapter's current
    story lines were later registered as (e.g. a chapter whose old checkpoint was never lazily
    claimed via register_legacy_branch before the user created a fresh branch by hand), so there
    is no single "right" branch_id to gate this on. Meanwhile entries_in_scope already treats
    them as visible from every branch, so leaving them undeletable from all of them would
    contradict the reset/delete UI's own "清空所有内容" promise for any branch a user picks.

    This is deliberately keyed on the "branch_id" key's outright absence, not "branch_id is
    None" -- author_loop's own event archiving (dialogue_mode/react_graph.py::
    _archive_stage_event) calls build_entry without a branch_id and so always produces an
    explicit "branch_id": None, tagging a real canonical chapter fact that must survive every
    sandbox branch reset for that chapter. Only the key's outright absence (impossible for any
    entry built after 2026-07-28, since build_entry always sets the key) safely identifies a
    stray pre-migration sandbox entry instead of a genuine cross-branch canon fact."""
    entries = _load_entries_from_db()
    if branch_id is None:
        filtered = [e for e in entries if e.get("chapter") != chapter]
    else:
        def _is_own(e: dict) -> bool:
            if e.get("chapter") != chapter:
                return False
            if e.get("branch_id") == branch_id:
                return True
            return "branch_id" not in e

        filtered = [e for e in entries if not _is_own(e)]
    try:
        _save_entries_to_db(filtered)
    except OSError:
        _log.exception("story_sandbox event log chapter-clear write failed")


async def delete_entries_for_chapter(chapter: int, branch_id: str | None = None) -> None:
    async with _event_log_lock:
        await asyncio.to_thread(_delete_entries_for_chapter_sync, chapter, branch_id)


def _copy_entries_for_branch_sync(chapter: int, dest_branch_id: str, id_remap: dict[str, str]) -> None:
    entries = _load_entries_from_db()
    copies = [
        {**e, "id": id_remap[e["id"]], "branch_id": dest_branch_id}
        for e in entries
        if e.get("chapter") == chapter and e.get("id") in id_remap
    ]
    if not copies:
        return
    try:
        _save_entries_to_db(entries + copies)
    except OSError:
        _log.exception("story_sandbox event log branch-copy write failed")


async def copy_entries_for_branch(chapter: int, dest_branch_id: str, id_remap: dict[str, str]) -> None:
    """Duplicates this chapter's event_log.json entries named as keys in id_remap (produced by
    graph.py::fork_branch) into new entries tagged dest_branch_id, using the pre-computed new ids
    -- see fork_branch's docstring for why the ids must be remapped, not reused. No-op when
    id_remap is empty (source branch had no state to fork, per fork_branch's own contract)."""
    if not id_remap:
        return
    async with _event_log_lock:
        await asyncio.to_thread(_copy_entries_for_branch_sync, chapter, dest_branch_id, id_remap)


def build_entry(
    result: _EventLike, chapter: int, turn_index: int, present: list[str] | None,
    branch_id: str | None = None, *, origin: str,
) -> dict | None:
    if not result.event:
        return None
    from engine.memory_recall.entity_index import scan_entities

    scanned = scan_entities(f"{result.event} {result.summary}")
    entities = sorted(set(result.entities) | set(scanned))
    characters = present if present is not None else result.characters
    return {
        "id": str(uuid.uuid4()),
        "chapter": chapter,
        "turn_index": turn_index,
        "time": result.time or "",
        "location": result.location or "",
        "characters": characters,
        "summary": result.event,
        "entities": entities,
        "branch_id": branch_id,
        "origin": origin,
    }


async def _archive_previous_round(state: SandboxState) -> None:
    """Embeds the PREVIOUS round's own entries into vector memory -- deferred until now (the
    current round's own turn) rather than at the moment that round was created, because
    rewrite_last_round can only ever rewrite turns[-1]. By the time this turn's graph is running,
    the previous round has already been superseded and can never be rewritten again, so its
    entries (whatever a rewrite may have last replaced them with) are now permanently safe to
    archive. This turn's OWN entries are deliberately never archived here -- they're still
    turns[-1]-to-be and could themselves still be rewritten before the round after it begins.
    No-op on the opening round (no previous round yet) or when the previous round produced no
    events. Failure here never blocks the turn -- best-effort persistence side effect, same
    posture as append_event_entry's own OSError handling."""
    turns = state.get("turns") or []
    if not turns:
        return
    prev_entries = round_event_log_entries(turns[-1])
    if not prev_entries:
        return
    try:
        await get_sandbox_vector_memory_repo().archive(prev_entries)
    except (OSError, RuntimeError, ValueError):
        _log.exception("story_sandbox vector memory archive failed")


async def _identity_guard(text: str) -> str:
    return text


async def _guard_and_build_entry(
    result: EventResult, chapter: int, turn_index: int, present: list[str] | None,
    branch_id: str | None, guard_text: GuardText, *, origin: str,
) -> dict | None:
    guarded_event = await guard_text(result.event) if result.event else result.event
    guarded_result = replace(result, event=guarded_event)
    return build_entry(
        guarded_result, chapter, turn_index, present, branch_id, origin=origin,
    )


async def build_event_entries(
    text: str, call_llm_event_extract: CallLLM, *,
    chapter: int, turn_index: int, present: list[str] | None = None,
    branch_id: str | None = None, origin: str,
    guard_text: GuardText | None = None,
) -> list[dict]:
    """Shared multi-event extract+build path for sandbox event_log nodes and author_loop archiving."""
    from engine.story_sandbox.summary_fold import extract_events

    guard = guard_text or _identity_guard
    results = await extract_events(text, call_llm_event_extract)
    if not results:
        return []
    built = await asyncio.gather(*(
        _guard_and_build_entry(r, chapter, turn_index, present, branch_id, guard, origin=origin)
        for r in results
    ))
    return [e for e in built if e]


async def _build_entries_from_round(
    round_text: str, call_llm_event_extract: CallLLM, guard_text: GuardText,
    *, chapter: int, turn_index: int, branch_id: str | None,
) -> list[dict]:
    return await build_event_entries(
        round_text, call_llm_event_extract,
        chapter=chapter, turn_index=turn_index, branch_id=branch_id,
        origin=MemoryOrigin.SANDBOX, guard_text=guard_text,
    )


def build_summary_fold_node(instruction: str, call_llm_summary_fold: CallLLM, guard_text: GuardText):
    async def _n(state: SandboxState) -> dict:
        from engine.story_sandbox.summary_fold import fold_summary

        round_text = f"【导演】{instruction}\n【正文】{state['final_text']}"
        summary = await fold_summary(state.get("rolling_summary", ""), round_text, call_llm_summary_fold)
        guarded = await guard_text(summary) if summary else summary
        return {"rolling_summary": guarded}
    return _n


def build_event_extract_node(
    chapter: int, instruction: str, call_llm_event_extract: CallLLM, guard_text: GuardText,
    *, branch_id: str | None = None,
):
    async def _n(state: SandboxState) -> dict:
        round_text = f"【导演】{instruction}\n【正文】{state['final_text']}"
        turn_index = len(state.get("turns") or [])
        entries = await _build_entries_from_round(
            round_text, call_llm_event_extract, guard_text,
            chapter=chapter, turn_index=turn_index, branch_id=branch_id,
        )
        await append_event_entries(entries)
        await _archive_previous_round(state)
        return {"event_log_entries_this_turn": entries}
    return _n


def build_summary_fold_rewrite_node(call_llm_summary_fold: CallLLM, guard_text: GuardText):
    async def _n(state: SandboxState) -> dict:
        from engine.story_sandbox.summary_fold import fold_summary

        turns = state["turns"]
        is_opening = len(turns) == 1
        baseline_summary = "" if is_opening else turns[-2].get("rolling_summary_after", "")
        round_text = f"【导演】{turns[-1]['instruction']}\n【正文】{state['final_text']}"
        summary = await fold_summary(baseline_summary, round_text, call_llm_summary_fold)
        guarded = await guard_text(summary) if summary else summary
        return {"rolling_summary": guarded}
    return _n


def build_event_extract_rewrite_node(
    chapter: int, call_llm_event_extract: CallLLM, guard_text: GuardText, *, branch_id: str | None = None,
):
    async def _n(state: SandboxState) -> dict:
        turns = state["turns"]
        last_round = turns[-1]
        round_text = f"【导演】{last_round['instruction']}\n【正文】{state['final_text']}"
        old_ids = [e["id"] for e in round_event_log_entries(last_round) if e.get("id")]
        entries = await _build_entries_from_round(
            round_text, call_llm_event_extract, guard_text,
            chapter=chapter, turn_index=len(turns) - 1, branch_id=branch_id,
        )
        await replace_event_entries(old_ids, entries)
        return {"event_log_entries_this_turn": entries}
    return _n
