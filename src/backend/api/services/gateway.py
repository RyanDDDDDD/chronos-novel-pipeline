"""Interaction gateway: front-end and back-end IO core - WS client + broadcast + replay buffer.

Same process module (non-independent process). Extracted from MessageHub to decouple "interaction recording/recovery" from "engine orchestration".
Does not hold any agent/task/Future - orchestration and interrupt recovery remain in MessageHub."""
from __future__ import annotations

from loguru import logger

from api.services.ws_logging import preview, should_log_event

# Lifecycle events are broadcast to every connection regardless of focus -- they're what
# drives the novel-list status dot (running/done/error) for novels the user isn't currently
# looking at. Everything else (streaming tokens, states, suggestions, event logs, ...) is
# "content" and is only forwarded to a connection currently focused on that event's novel_id
# -- a background novel's content stream would otherwise silently corrupt whichever novel's
# view the frontend currently has mounted.
_LIFECYCLE_EVENT_TYPES = frozenset({
    "author_loop_start", "author_loop_done", "author_loop_error", "author_loop_stopped",
    "setup_chat_start", "setup_chat_done",
    "setup_chat_error", "setup_chat_turn_cancelled",
    "story_sandbox_start", "story_sandbox_done", "story_sandbox_error",
    "story_sandbox_turn_cancelled", "story_sandbox_rewrite_done",
    "story_sandbox_suggestions_regenerated", "story_sandbox_suggestions_regenerate_error",
    "story_sandbox_selection_rewrite_done", "story_sandbox_selection_rewrite_error",
    "story_sandbox_profile_mutation_rewrite_done", "story_sandbox_profile_mutation_rewrite_error",
    "skeleton_review_started", "skeleton_review_restarted", "skeleton_review_done",
    "timeline_cascade_started", "timeline_cascade_restarted", "timeline_cascade_done",
    "world_review_started", "world_review_restarted", "world_review_done",
})

# Streaming token event types: never itemized to [ws-send], only accumulated in memory and
# flushed as one [ws-stream] line once the run of same-type/agent/role tokens ends (frontend
# delivery via sent_json is untouched -- see _log_outbound).
_STREAMING_TOKEN_EVENT_TYPES = frozenset({
    "author_loop_token", "story_sandbox_token", "story_sandbox_rewrite_token", "setup_chat_token",
})

# A run reaching one of these means there is nothing further to recover by replaying it (or
# its own already-buffered milestones -- see broadcast()'s prune step below) on a later
# reconnect -- same "state is REST-recoverable, replay only pollutes" reasoning
# _is_transient_event already applies to archive_build_*.
_TERMINAL_AUTHOR_LOOP_EVENT_TYPES = frozenset({
    "author_loop_done", "author_loop_error", "author_loop_stopped",
})

# portrait_generation_done is portrait generation's only terminal event -- same "state is
# REST-recoverable, replay only pollutes" reasoning as author_loop_done et al. (the cast grid
# already re-fetches on this event, see listeners.ts). Unlike author_loop_done, its prune step
# is scoped to (novel_id, character) rather than novel_id alone -- see
# _prune_portrait_buffer's docstring for why.
_PORTRAIT_TERMINAL_EVENT_TYPE = "portrait_generation_done"


class Gateway:
    def __init__(self) -> None:
        self._ws_clients: list = []
        self._buffer: list[dict] = []
        #Monotonic per-process counter stamped onto every buffered event as `_seq`, so a
        #reconnecting client can ask add_client() to replay only what it hasn't seen yet
        #instead of the whole buffer every time.
        self._next_seq: int = 1
        #Streaming token aggregation: logs are not flushed token by token, but saved according to (type, agent, role), and the entire section is collected before being integrated into one.
        self._token_stream: dict | None = None
        self._focus_novel_id: str | None = None

    def set_focus(self, novel_id: str) -> None:
        """Called by the /api/novels/active handler on every switch -- see module docstring
        in the owning plan for why this is a single process-wide pointer rather than genuine
        per-connection subscription state."""
        self._focus_novel_id = novel_id

    def get_focus(self) -> str | None:
        return self._focus_novel_id

    @staticmethod
    def _is_transient_event(event: dict) -> bool:
        """
Transient events that do not enter the replay buffer:

        - setup_chat_*: The session is based on /api/setup-chat/history, and the replay will repeatedly fill the dialog box.
        - story_sandbox_*: Same reasoning as setup_chat_* -- the session is based on
          /api/story-sandbox/history, so replaying a completed round's events on reconnect
          (e.g. an F5 refresh) makes the frontend append a duplicate copy of that round on top
          of the one already returned by the history fetch.
        - author_loop_token: The author's streaming incremental token, which is high-frequency and only meaningful for the current round. Re-connection and replay are of no value.
        - archive_build_*: Same reasoning as setup_chat_*/story_sandbox_* -- current build state
          is always re-derivable from GET /api/archives (list_archive_overview), so there's
          nothing to recover by replaying it. Unlike those two, clear_buffer() is never called
          after a normal successful build (only on chapter reset/app shutdown), so leaving these
          in the buffer meant every later reconnect (a plain page refresh included) replayed a
          long-finished build's start/progress/done sequence, re-triggering the frontend's
          building->done toast on every refresh.
        - author_loop_done/error/stopped: current status is always re-derivable via REST (the
          same reasoning as archive_build_* above), so these terminal events themselves don't
          need to survive in the buffer either -- broadcast() additionally prunes this run's
          OTHER already-buffered milestones (start/segment/state/summary/chapter_progress/
          style_rewrite) once one of these fires, since a finished run has nothing left to
          recover by replaying its now-obsolete progress trail. Before this, those milestones
          stayed buffered indefinitely (clear_buffer() is chapter-reset/shutdown-only, same gap
          archive_build_* had), so any later reconnect -- a plain page refresh included --
          replayed a long-finished chapter's whole run again, spuriously re-marking the 主笔 tab's
          unread badge (viewUnreadSlice.ts has no way to tell "replay of old news" apart from
          "genuinely new")."""

        t = str(event.get("type", ""))
        return (
            t.startswith("setup_chat_") or t.startswith("story_sandbox_")
            or t.startswith("archive_build_") or t == "author_loop_token"
            or t in _TERMINAL_AUTHOR_LOOP_EVENT_TYPES
            or t == _PORTRAIT_TERMINAL_EVENT_TYPE
        )

    def _should_deliver(self, event: dict) -> bool:
        """Lifecycle events always deliver. Content events only deliver when this event's
        novel_id matches the current focus pointer (or there is no focus pointer yet / the
        event carries no novel_id -- fail open rather than silently dropping events from
        code paths not yet novel_id-aware)."""
        if str(event.get("type", "")) in _LIFECYCLE_EVENT_TYPES:
            return True
        nid = event.get("novel_id")
        if not nid or self._focus_novel_id is None:
            return True
        return bool(nid == self._focus_novel_id)

    def _prune_novel_buffer(self, novel_id: str, type_prefix: str) -> None:
        """Drop this novel's own already-buffered <type_prefix>* events -- called when a run
        reaches a terminal state (see _TERMINAL_AUTHOR_LOOP_EVENT_TYPES). Safe to key on
        novel_id alone (no chapter/thread matching needed): a novel's author_loop runs are
        strictly sequential (is_pipeline_busy() rejects a second start), so by the time a
        terminal event fires, every other buffered author_loop_* entry for this novel_id
        necessarily belongs to the very run that just ended -- there's no next run's events to
        accidentally catch, since a new run can't start until this task has fully returned."""
        self._buffer = [
            e for e in self._buffer
            if not (e.get("novel_id") == novel_id and str(e.get("type", "")).startswith(type_prefix))
        ]

    def _prune_portrait_buffer(self, novel_id: str, character: str) -> None:
        """Drop this character's own already-buffered portrait_generation_started event --
        called when portrait_generation_done fires for it. Keyed on (novel_id, character)
        rather than novel_id alone (unlike _prune_novel_buffer): unlike author_loop, several
        characters' portraits can be generating concurrently within the same novel (e.g. a
        batch regenerate), so pruning by novel_id alone would wipe out sibling characters'
        still-in-flight started events, not just the one that just finished.

        Before this method existed, portrait_generation_started/done were never excluded from
        the buffer at all (unlike every other *_started/*_done event family here) and nothing
        ever pruned them, so every character portrait ever generated in a session's lifetime
        stayed buffered indefinitely -- harmless in the short term (each event is a small
        dict), but genuinely unbounded over a long-running process across many characters."""
        self._buffer = [
            e for e in self._buffer
            if not (
                e.get("novel_id") == novel_id and e.get("character") == character
                and str(e.get("type", "")) == "portrait_generation_started"
            )
        ]

    async def broadcast(self, event: dict) -> None:
        """Write buffer + broadcast to all WS clients (dead connection cleanup). Content
        events for a non-focused novel are filtered out before the per-client fan-out."""
        if not self._is_transient_event(event):
            event["_seq"] = self._next_seq
            self._next_seq += 1
            self._buffer.append(event)
        t = str(event.get("type", ""))
        nid = event.get("novel_id")
        if t in _TERMINAL_AUTHOR_LOOP_EVENT_TYPES and nid:
            self._prune_novel_buffer(nid, "author_loop_")
        elif t == _PORTRAIT_TERMINAL_EVENT_TYPE and nid and event.get("character"):
            self._prune_portrait_buffer(nid, str(event["character"]))
        self._log_outbound(event)
        if not self._should_deliver(event):
            return
        dead = []
        for ws in self._ws_clients:
            try:
                await ws.send_json(event)
            except Exception:  #noqa: BLE001 — Single connection failure does not affect others, mark cleanup
                dead.append(ws)
        for ws in dead:
            self._ws_clients.remove(ws)

    def _log_outbound(self, event: dict) -> None:
        """Outbound log: Streaming tokens are aggregated into one log; other events are recorded as usual (flush the accumulated streams first to avoid interleaving).

        Sending to the front end is not affected by this - this method only controls server.log, and tokens are still sent_json one by one."""

        event_type = str(event.get("type", ""))
        if event_type in _STREAMING_TOKEN_EVENT_TYPES:
            self._accumulate_token(event_type, event)
            return
        self._flush_token_stream()
        if should_log_event(event.get("type")):
            logger.info("[ws-send] {}", preview(self._for_log(event)))

    @staticmethod
    def _for_log(event: dict) -> dict:
        """Swap novel_id for its display name for log readability -- returns a shallow copy
        so the original event (sent to clients, matched against _focus_novel_id) is untouched."""
        nid = event.get("novel_id")
        if not nid:
            return event
        from api.services.novels import get_novel_name
        return {**event, "novel_id": get_novel_name(nid)}

    def _accumulate_token(self, event_type: str, event: dict) -> None:
        """
Save a streaming token; when switching to a different (event type, agent, role) -- e.g. an
author_loop agent handoff, or story_sandbox_token giving way to story_sandbox_rewrite_token --
flush the previous stream first."""
        agent = str(event.get("agent", ""))
        role = event.get("role")
        cur = self._token_stream
        if cur is None or cur["type"] != event_type or cur["agent"] != agent or cur["role"] != role:
            self._flush_token_stream()
            self._token_stream = {
                "type": event_type, "agent": agent, "role": role,
                "text": str(event.get("delta", "")), "tokens": 1,
            }
        else:
            cur["text"] += str(event.get("delta", ""))
            cur["tokens"] += 1

    def _flush_token_stream(self) -> None:
        """Consolidate the accumulated streaming tokens into a [ws-stream] log; skip if empty."""
        cur = self._token_stream
        self._token_stream = None
        if not cur or not cur["text"]:
            return
        logger.info(
            "[ws-stream] type={} agent={} role={} tokens={} text={}",
            cur["type"], cur["agent"], cur["role"] or "", cur["tokens"], preview(cur["text"]),
        )

    async def add_client(self, ws: object, since_seq: int = 0) -> None:
        """Accept new clients: playback buffer first, then add to broadcast list. Buffer
        replay is not focus-filtered -- historically this only ever held one novel's events
        anyway (see _is_transient_event's docstring: setup_chat_*/story_sandbox_*/
        archive_build_* never enter the buffer), and author_loop's non-token milestones are
        low-frequency enough that replaying a background novel's milestones on reconnect is
        harmless (the frontend's per-novel-id filtering, see Task 2, ignores anything not
        for the currently mounted novel).

        since_seq lets a reconnecting client (which tracks the highest `_seq` it has already
        applied) skip everything it's already seen, instead of re-applying the entire buffer
        on every reconnect -- a plain first-time connect passes 0 and gets the full buffer."""
        self._ws_clients.append(ws)
        for event in list(self._buffer):
            if event["_seq"] <= since_seq:
                continue
            try:
                await ws.send_json(event)  # type: ignore[attr-defined]
            except Exception:  #noqa: BLE001 — If playback fails, the connection is disconnected and should be removed.
                self._ws_clients.remove(ws)
                return

    def remove_client(self, ws: object) -> None:
        if ws in self._ws_clients:
            self._ws_clients.remove(ws)

    def clear_buffer(self) -> None:
        self._buffer.clear()

    async def start(self) -> None:
        """inproc 无需连接，no-op（满足 GatewayPort 生命周期契约）。"""

    async def close(self) -> None:
        """inproc 无连接可关，no-op。"""
