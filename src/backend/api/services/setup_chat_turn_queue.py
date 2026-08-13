"""In-memory FIFO queue for deferred setup-chat agent turns, keyed by novel_id."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum


class SetupChatTurnKind(StrEnum):
    USER = "user"
    REGENERATE = "regenerate"
    SYSTEM_NOTICE = "system_notice"


@dataclass(frozen=True)
class SetupChatTurnItem:
    novel_id: str
    kind: SetupChatTurnKind
    text: str = ""
    attachment_ids: tuple[str, ...] = field(default_factory=tuple)
    user_msg_id: str = ""
    user_text: str = ""
    summary_text: str = ""


class SetupChatTurnQueue:
    def __init__(self) -> None:
        self._queues: dict[str, deque[SetupChatTurnItem]] = {}

    def enqueue(self, item: SetupChatTurnItem) -> None:
        self._queues.setdefault(item.novel_id, deque()).append(item)

    def enqueue_or_merge_system_notice(self, novel_id: str, summary_text: str) -> None:
        """Background review/derivation jobs (character review, chapter skeleton review,
        timeline cascade, world review) each call this once they finish, to tell the setup
        chat agent about the result. If one of those notices is already sitting in the queue
        unconsumed, folding the new summary into it (instead of enqueueing a second item)
        collapses what would be back-to-back chat-agent turns into a single one -- the common
        case whenever several such jobs land while the agent is busy composing the previous
        notice's reply."""
        q = self._queues.get(novel_id)
        if q:
            for i, item in enumerate(q):
                if item.kind == SetupChatTurnKind.SYSTEM_NOTICE:
                    merged_text = f"{item.summary_text}\n\n---\n\n{summary_text}"
                    q[i] = SetupChatTurnItem(
                        novel_id=novel_id,
                        kind=SetupChatTurnKind.SYSTEM_NOTICE,
                        summary_text=merged_text,
                    )
                    return
        self.enqueue(
            SetupChatTurnItem(novel_id=novel_id, kind=SetupChatTurnKind.SYSTEM_NOTICE, summary_text=summary_text)
        )

    def clear(self, novel_id: str) -> None:
        self._queues.pop(novel_id, None)

    def peek(self, novel_id: str) -> SetupChatTurnItem | None:
        q = self._queues.get(novel_id)
        if not q:
            return None
        return q[0]

    def pop(self, novel_id: str) -> SetupChatTurnItem | None:
        q = self._queues.get(novel_id)
        if not q:
            return None
        item = q.popleft()
        if not q:
            self._queues.pop(novel_id, None)
        return item

    def len_for(self, novel_id: str) -> int:
        q = self._queues.get(novel_id)
        return len(q) if q else 0


SETUP_CHAT_TURN_QUEUE = SetupChatTurnQueue()
