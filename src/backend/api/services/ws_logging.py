"""WebSocket message log assistance: filtering + preview used for sending and receiving messages in server.log (pure function, easy for testing).

Front-end and back-end log isolation - the back-end side only handles server.log; the front-end interaction log is in the browser console (no return)."""
from __future__ import annotations

#Logs are not flushed for high-frequency events (segment-by-segment output/heartbeat); other interaction/life cycle events are recorded.
EVENT_LOG_SKIP = frozenset({"author_loop_segment", "author_loop_progress"})


def should_log_event(event_type: str | None) -> bool:
    """
Whether broadcast outbound events should be logged: skip high-frequency segment/progress, and record the rest."""
    return event_type not in EVENT_LOG_SKIP


def preview(obj: object, limit: int = 200) -> str:
    """Compress events/messages into a single line of log preview: long string truncation, list truncation, to avoid flushing the entire text into the log."""
    if isinstance(obj, dict):
        return "{" + ", ".join(f"{k}={preview(v, limit)}" for k, v in obj.items()) + "}"
    if isinstance(obj, list):
        head = ", ".join(preview(x, limit) for x in obj[:10])
        return "[" + head + ("…" if len(obj) > 10 else "") + "]"
    if isinstance(obj, str):
        return repr(obj if len(obj) <= limit else obj[:limit] + f"…(+{len(obj) - limit})")
    return repr(obj)
