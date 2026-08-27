"""Per-novel buffer that batches setup-chat background-review results.

The four background review/derivation jobs -- world_background_review,
character_background_review, skeleton_background_review, timeline_auto -- used to each
call MessageHub.trigger_system_notice_turn independently the moment they finished,
producing one chat-agent turn per job. This buffer instead collects their results
keyed by review target, so MessageHub can wait until a novel has NO review still
in flight (the "barrier") and then surface the whole batch as a single turn.

Single event loop, not thread-safe -- same contract as SCHEDULER / MessageHub.
Process-global ephemeral state; nothing here is persisted across a process restart
(same as SETUP_CHAT_TURN_QUEUE).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

# ("world",) / ("character", name) / ("skeleton", chapter) / ("timeline",) / ("timeline", name).
# Elements mix str and int, so the alias stays a bare tuple.
ReviewKey = tuple[object, ...]


class ReviewStatus(StrEnum):
    CLEAN = "clean"        # review passed, nothing changed (body == "")
    RESOLVED = "resolved"  # issue found + auto-fixed, fix errored, or cascade re-derived
    TIMEOUT = "timeout"    # gave up after two watchdog timeouts


@dataclass(frozen=True)
class ReviewFeedbackEntry:
    kind: str              # "world" | "character" | "skeleton" | "timeline"
    label: str             # chat-facing zh label: 世界观 / 角色「甲」 / 第3章骨架 / 角色「甲」时间线
    status: ReviewStatus
    body: str = ""         # structured facts for the chat agent; "" when CLEAN


class ReviewFeedbackBuffer:
    """Per-novel review-batch coordination state: what is still running, what has
    finished and is waiting to be flushed, and per-key timeout retry counters."""

    def __init__(self) -> None:
        self._pending: dict[str, set[ReviewKey]] = {}
        self._buffer: dict[str, dict[ReviewKey, ReviewFeedbackEntry]] = {}
        self._attempts: dict[str, dict[ReviewKey, int]] = {}

    # ---- barrier units ----
    def mark_pending(self, novel_id: str, key: ReviewKey) -> None:
        self._pending.setdefault(novel_id, set()).add(key)

    def clear_pending(self, novel_id: str, key: ReviewKey) -> None:
        s = self._pending.get(novel_id)
        if s is not None:
            s.discard(key)
            if not s:
                self._pending.pop(novel_id, None)

    def has_pending(self, novel_id: str) -> bool:
        return bool(self._pending.get(novel_id))

    # ---- result buffer ----
    def record(self, novel_id: str, key: ReviewKey, entry: ReviewFeedbackEntry) -> None:
        """In-place replace: dict is insertion-ordered, so `buf[key] = entry` keeps an
        existing key at its original position while overwriting its value."""
        self._buffer.setdefault(novel_id, {})[key] = entry

    def snapshot(self, novel_id: str) -> list[ReviewFeedbackEntry]:
        return list(self._buffer.get(novel_id, {}).values())

    def clear_buffer(self, novel_id: str) -> None:
        self._buffer.pop(novel_id, None)

    # ---- timeout retry counters ----
    def bump_attempt(self, novel_id: str, key: ReviewKey) -> int:
        m = self._attempts.setdefault(novel_id, {})
        m[key] = m.get(key, 0) + 1
        return m[key]

    def reset_attempt(self, novel_id: str, key: ReviewKey) -> None:
        m = self._attempts.get(novel_id)
        if m is not None:
            m.pop(key, None)
            if not m:
                self._attempts.pop(novel_id, None)

    # ---- lifecycle ----
    def clear_all(self, novel_id: str) -> None:
        self._pending.pop(novel_id, None)
        self._buffer.pop(novel_id, None)
        self._attempts.pop(novel_id, None)


REVIEW_FEEDBACK = ReviewFeedbackBuffer()


# Appended once to any batch that contains a RESOLVED/TIMEOUT entry -- the review+fix
# pipeline is fully self-healing, but the chat agent would otherwise read the
# rubric/fix report as an open action item and re-invoke the setup tools on its own,
# duplicating (or fighting) the fix agent's already-applied write. Previously each
# review module appended its own near-identical copy of this sentence; centralised here.
_AUTO_RESOLVED_NOTICE = (
    "以上均为后台自动审查与修复的结果，仅供你了解情况；不需要、也不要据此再手动调用工具修改。"
)


def render_review_feedback(entries: list[ReviewFeedbackEntry]) -> str:
    """Render a whole batch into the structured-facts text handed to the setup-chat
    agent. MessageHub._execute_system_notice_turn wraps this again with the
    「【系统事件，非用户输入】…请你用自己的话跟用户说明」 framing, so this stays facts only."""
    clean = [e for e in entries if e.status is ReviewStatus.CLEAN]
    other = [e for e in entries if e.status is not ReviewStatus.CLEAN]

    lines: list[str] = [f"本轮后台审查共 {len(entries)} 项："]
    if clean:
        lines.append("")
        lines.append("【通过，无需调整】" + "、".join(e.label for e in clean))
    for e in other:
        suffix = "（超时）" if e.status is ReviewStatus.TIMEOUT else ""
        lines.append("")
        lines.append(f"━━ {e.label}{suffix} ━━")
        lines.append(e.body)
    if other:
        lines.append("")
        lines.append(_AUTO_RESOLVED_NOTICE)
    return "\n".join(lines)


async def handle_review_timeout(
    novel_id: str,
    pending_key: ReviewKey,
    *,
    kind: str,
    label: str,
    retry: Callable[[], None],
    give_up: Callable[[], Awaitable[None]],
) -> None:
    """Shared on_timeout behaviour for the four background review jobs. First watchdog
    timeout for a key -> reschedule the job once (immediately). Second timeout -> stop
    retrying: run the module's own cleanup (`give_up`: clear its active flag + broadcast
    `*_review_done`) and drop a TIMEOUT entry into the batch, which then waits for the
    barrier to clear like any other entry.

    Worst case a genuinely hung job costs ~2 x SCHEDULER.watchdog_timeout_s before it is
    abandoned; accepted (see the spec's 非目标 section)."""
    if REVIEW_FEEDBACK.bump_attempt(novel_id, pending_key) < 2:
        retry()
        return

    REVIEW_FEEDBACK.reset_attempt(novel_id, pending_key)
    await give_up()

    from api.routes import _hub_instance

    entry = ReviewFeedbackEntry(
        kind=kind,
        label=label,
        status=ReviewStatus.TIMEOUT,
        body=f"{label}的后台审查两次超时未完成，已放弃。",
    )
    await _hub_instance().report_review_done(novel_id, pending_key, [(pending_key, entry)])


