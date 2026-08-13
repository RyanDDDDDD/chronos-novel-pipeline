"""Agent-less read-only checkpoint reader: only used to backfill old setup-chat history into the message table.

Steady-state recovery never goes here (read-only message table). Use independent AsyncSqliteSaver to connect to per-novel checkpoint.sqlite,
aget_tuple takes the latest checkpoint messages and does not construct an LLM agent."""
from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from engine.setup_chat.session_record import _save, load_messages, next_seq

Reader = Callable[[str, str], Awaitable[list]]


async def read_checkpoint_messages(checkpoint_path: str, thread_id: str) -> list:
    """
Get the raw message list of the thread's latest checkpoint; no library/read failure/empty → []."""
    if not os.path.exists(checkpoint_path):
        return []
    try:
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        conn = await aiosqlite.connect(checkpoint_path)
        try:
            saver = AsyncSqliteSaver(conn)
            tup = await saver.aget_tuple({"configurable": {"thread_id": thread_id}})
        finally:
            await conn.close()
    except Exception:  #noqa: BLE001 — Migration read failure is not fatal, downgrade is empty
        return []
    if tup is None:
        return []
    values = getattr(tup, "checkpoint", {}).get("channel_values", {}) if tup else {}
    msgs = values.get("messages") if isinstance(values, dict) else None
    return list(msgs) if isinstance(msgs, list) else []


async def backfill_if_missing(
    session_dir: str,
    checkpoint_path: str,
    thread_id: str,
    *,
    persist_dir: str,
    reader: Reader = read_checkpoint_messages,
) -> list[dict]:
    """The message table exists → return its contents directly (checkpoint is not read).
    Missing → read checkpoint projection (reuse UI export purification), write the table once
    (even when empty, so a thread with no checkpoint history doesn't re-read the checkpoint file
    on every subsequent call) and return."""
    from engine.setup_chat.session_record import _session_initialized

    if _session_initialized(session_dir):
        return load_messages(session_dir)

    raw = await reader(checkpoint_path, thread_id)
    out: list[dict] = []
    if raw:
        from engine.setup_chat.history import export_chat_messages_for_ui

        exported = export_chat_messages_for_ui(raw, persist_dir=persist_dir)
        for i, m in enumerate(exported):
            rec = {"id": m.get("id") or f"bf-{i}", "role": m["role"],
                   "content": m["content"], "seq": next_seq(out), "ts": 0}
            #The folded thinking block is landed together with the backfill (export has been rebuilt; it will only have a key if it is not empty).
            if m.get("thinking"):
                rec["thinking"] = m["thinking"]
            out.append(rec)
    _save(session_dir, out)
    return out
