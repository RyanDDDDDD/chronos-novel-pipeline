"""Session layer interaction record (message table): The purified record of client ↔ backend interaction, the front end directly reads it and restores it.

Engine-independent checkpoint/memory: checkpoint=engine continued running state, this module=message table from user perspective."""
from __future__ import annotations

import json
import os
import time
import uuid

from repositories.sqlite_store import SqliteStore, get_connection
from utils.paths import novel_dir

_MSG_FILE = "messages.json"


def _novel_id_from_session_dir(session_dir: str) -> str:
    norm = session_dir.replace("\\", "/").rstrip("/")
    parts = norm.split("/")
    if len(parts) >= 2 and parts[-1] == "session":
        return parts[-2]
    from utils.paths import active_novel_id

    return active_novel_id()


def _session_initialized(session_dir: str) -> bool:
    if os.path.exists(os.path.join(session_dir, _MSG_FILE)):
        return True
    if load_messages(session_dir):
        return True
    flag = SqliteStore(_novel_id_from_session_dir(session_dir)).get_doc("session_initialized", "")
    return isinstance(flag, dict) and bool(flag.get("initialized"))


def _db_conn(session_dir: str):
    nid = _novel_id_from_session_dir(session_dir)
    return get_connection(os.path.join(novel_dir(nid), "chronos.sqlite3"))


def _encode_content(rec: dict) -> str:
    base = rec.get("content", "")
    extras = {k: rec[k] for k in ("thinking", "options") if k in rec}
    if extras:
        return json.dumps({"content": base, **extras}, ensure_ascii=False)
    return str(base)


def _decode_content(raw: str) -> dict:
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "content" in data:
                return data
        except json.JSONDecodeError:
            pass
    return {"content": raw}


def _row_to_message(row: tuple) -> dict:
    msg_id, role, content_raw, seq, ts = row
    rec = {"id": msg_id, "role": role, "seq": seq, "ts": ts}
    rec.update(_decode_content(content_raw))
    return rec


def load_messages(session_dir: str) -> list[dict]:
    conn = _db_conn(session_dir)
    rows = conn.execute(
        "SELECT id, role, content, seq, ts FROM session_messages ORDER BY seq",
    ).fetchall()
    return [_row_to_message(row) for row in rows]


def clear_messages(session_dir: str) -> None:
    """Wipe this novel's session message table (used by setup-chat's "清空对话" reset). Leaves
    the session_initialized flag untouched -- _session_initialized falls through to
    load_messages() either way, which is now empty, so a stale True flag doesn't resurrect
    anything."""
    conn = _db_conn(session_dir)
    conn.execute("DELETE FROM session_messages")
    conn.commit()


def _save(session_dir: str, messages: list[dict]) -> None:
    conn = _db_conn(session_dir)
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM session_messages")
        for rec in messages:
            if not isinstance(rec, dict):
                continue
            msg_id = rec.get("id")
            role = rec.get("role")
            if not msg_id or not role:
                continue
            conn.execute(
                "INSERT INTO session_messages (id, role, content, seq, ts) VALUES (?, ?, ?, ?, ?)",
                (
                    str(msg_id),
                    str(role),
                    _encode_content(rec),
                    int(rec.get("seq", 0)),
                    int(rec.get("ts", 0)),
                ),
            )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    SqliteStore(_novel_id_from_session_dir(session_dir)).save_doc(
        "session_initialized", "", {"initialized": True},
    )


def next_seq(messages: list[dict]) -> int:
    """
Authoritative monotonic sequence number: existing maximum seq + 1 (empty → 0)."""
    seqs = [int(m.get("seq", -1)) for m in messages if isinstance(m, dict)]
    return (max(seqs) + 1) if seqs else 0


def _append(session_dir: str, role: str, content: str, msg_id: str, thinking: str = "") -> dict:
    messages = load_messages(session_dir)
    rec = {"id": msg_id, "role": role, "content": content,
           "seq": next_seq(messages), "ts": _now_ms()}
    #Collapse thinking block: write the key only if it is not empty, backward compatible (old messages without thinking do not have thinking).
    if thinking.strip():
        rec["thinking"] = thinking
    messages.append(rec)
    _save(session_dir, messages)
    return rec


def _now_ms() -> int:
    return int(time.time() * 1000)


def append_user(session_dir: str, content: str) -> dict:
    return _append(session_dir, "user", content, f"u-{uuid.uuid4().hex[:12]}")


def append_assistant(
    session_dir: str, content: str, *, msg_id: str | None = None, thinking: str = "",
) -> dict:
    return _append(
        session_dir, "assistant", content, msg_id or f"a-{uuid.uuid4().hex[:12]}", thinking,
    )


def append_system(session_dir: str, content: str) -> dict:
    """System-style notice line (interruption/rollback alerts), survives refresh."""
    return _append(session_dir, "system", content, f"s-{uuid.uuid4().hex[:12]}")


def append_choice(session_dir: str, question: str, options: list[str]) -> dict:
    """Persists a present_choices offer as its own record (sibling to user/assistant/system,
    not nested in an assistant message) so it survives independently of whether the turn that
    offered it ever finishes. Whether it's still "pending" is derived positionally elsewhere
    (session_record stays append-only, no "answered" mutation here)."""
    messages = load_messages(session_dir)
    rec = {
        "id": f"c-{uuid.uuid4().hex[:12]}", "role": "choice", "content": question,
        "options": options, "seq": next_seq(messages), "ts": _now_ms(),
    }
    messages.append(rec)
    _save(session_dir, messages)
    return rec


def remove_message(session_dir: str, msg_id: str) -> bool:
    """Remove one record by id (user-cancel rollback, unlike the append-only path above)."""
    messages = load_messages(session_dir)
    filtered = [m for m in messages if m.get("id") != msg_id]
    if len(filtered) == len(messages):
        return False
    _save(session_dir, filtered)
    return True
