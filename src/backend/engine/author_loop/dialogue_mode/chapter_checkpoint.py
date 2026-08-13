"""Synchronous reading/management of checkpoints for the entire chapter in line mode.

Write to AsyncSqliteSaver (chapter_graph, the graph is async); but the caller of save/clear/scan is the synchronization engine function,
Therefore, use synchronous SqliteSaver to read the same SQLite (schema and async versions are interoperable, verified). thread_id=ch{chapter number}."""
from __future__ import annotations

import os
import re
import sqlite3
from typing import Any


def _open(cp_path: str):
    from langgraph.checkpoint.sqlite import SqliteSaver

    conn = sqlite3.connect(cp_path)
    return SqliteSaver(conn), conn


def read_chapter_checkpoint_values(cp_path: str, thread_id: str) -> dict[str, Any]:
    """
Get the channel_values ​​of the latest checkpoint of the thread in this chapter; no library/stateless → {}."""
    if not os.path.exists(cp_path):
        return {}
    saver, conn = _open(cp_path)
    try:
        tup = saver.get_tuple({"configurable": {"thread_id": thread_id}})
    except (sqlite3.Error, KeyError):
        return {}
    finally:
        conn.close()
    if tup is None:
        return {}
    vals: Any = (getattr(tup, "checkpoint", {}) or {}).get("channel_values", {})
    return vals if isinstance(vals, dict) else {}


def read_chapter_parts(cp_path: str, thread_id: str) -> list[str]:
    """Get the parts of the latest checkpoint of the thread in this chapter (finalize the text beat by beat); no library/stateless → []."""
    parts = read_chapter_checkpoint_values(cp_path, thread_id).get("parts")
    return [str(p) for p in parts] if isinstance(parts, list) else []


def clear_chapter_thread(cp_path: str, thread_id: str) -> None:
    """
Delete all checkpoints of the thread in this chapter (used for "restart"); ignore them if there is no library."""
    if not os.path.exists(cp_path):
        return
    saver, conn = _open(cp_path)
    try:
        saver.delete_thread(thread_id)
    except sqlite3.Error:
        pass
    finally:
        conn.close()


def scan_resumable_chapters(cp_path: str) -> list[int]:
    """There is already a checkpoint chapter number in sqlite (thread_id=ch{N} reverse solution); no library → []."""
    if not os.path.exists(cp_path):
        return []
    chapters: set[int] = set()
    saver, conn = _open(cp_path)
    try:
        for ct in saver.list(None):
            tid = str((ct.config.get("configurable") or {}).get("thread_id", ""))
            m = re.match(r"ch(\d+)$", tid)
            if m:
                chapters.add(int(m.group(1)))
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return sorted(chapters)
