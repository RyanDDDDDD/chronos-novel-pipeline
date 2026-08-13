"""Sandbox story-branch registry: per-novel branch list stored in chronos.sqlite3 documents table."""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import cast

from repositories.sqlite_store import SqliteStore
from utils.paths import active_novel_id

from engine.story_sandbox.state import LEGACY_BRANCH_ID

_BRANCH_DOC_KEY = "story_sandbox_branches"

_BRANCH_NUMBER_RE = re.compile(r"^故事线(\d+)$")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _next_branch_number(chapter: int, branches: list[dict]) -> int:
    """Smallest positive integer not currently used by this chapter's auto-named branches.
    Only names matching exactly "故事线<N>" count as occupying a number -- a custom name (even
    one a user typed to look like "故事线5") doesn't block or consume anything here, since this
    is a simple pattern scan, not a hidden persisted counter."""
    used: set[int] = set()
    for b in branches:
        if b.get("chapter") != chapter:
            continue
        m = _BRANCH_NUMBER_RE.match(str(b.get("name", "")))
        if m:
            used.add(int(m.group(1)))
    n = 1
    while n in used:
        n += 1
    return n


def _store() -> SqliteStore:
    return SqliteStore(active_novel_id())


def _load() -> dict:
    data = _store().get_doc(_BRANCH_DOC_KEY, "")
    if not isinstance(data, dict):
        return {"branches": []}
    branches = data.get("branches")
    return {"branches": branches if isinstance(branches, list) else []}


def _save(doc: dict) -> None:
    _store().save_doc(_BRANCH_DOC_KEY, "", doc)


def list_branches(chapter: int) -> list[dict]:
    """Branches for this chapter, sorted by updated_at descending (most recently active first)."""
    doc = _load()
    rows = [b for b in doc["branches"] if b.get("chapter") == chapter]
    return sorted(rows, key=lambda b: b.get("updated_at", ""), reverse=True)


def register_legacy_branch(chapter: int) -> dict:
    """Idempotent: registers the pre-existing checkpoint thread (branch_id == LEGACY_BRANCH_ID)
    as this chapter's first story line, for chapters that already had sandbox conversations
    before this feature shipped. Returns the existing record unchanged if already registered."""
    doc = _load()
    for b in doc["branches"]:
        if b.get("chapter") == chapter and b.get("id") == LEGACY_BRANCH_ID:
            return cast(dict, b)
    now = _now()
    record = {
        "id": LEGACY_BRANCH_ID, "chapter": chapter, "name": "故事线1",
        "created_at": now, "updated_at": now,
    }
    doc["branches"].append(record)
    _save(doc)
    return record


def create_branch(chapter: int, name: str | None = None) -> dict:
    """New story line (blank, or forked -- forking itself is orchestrated by
    message_hub.create_story_sandbox_branch, this function only ever creates the blank registry
    record). name defaults to an auto-numbered "故事线N", N = the smallest number not already
    used by this chapter's auto-named branches (see _next_branch_number) -- fills gaps left by
    deletions, not a monotonic counter."""
    doc = _load()
    now = _now()
    record = {
        "id": str(uuid.uuid4()), "chapter": chapter,
        "name": (name or "").strip() or f"故事线{_next_branch_number(chapter, doc['branches'])}",
        "created_at": now, "updated_at": now,
    }
    doc["branches"].append(record)
    _save(doc)
    return record


def rename_branch(chapter: int, branch_id: str, name: str) -> dict:
    doc = _load()
    for b in doc["branches"]:
        if b.get("chapter") == chapter and b.get("id") == branch_id:
            b["name"] = name
            b["updated_at"] = _now()
            _save(doc)
            return cast(dict, b)
    raise ValueError(f"故事线不存在: {branch_id}")


def get_branch(chapter: int, branch_id: str) -> dict:
    doc = _load()
    for b in doc["branches"]:
        if b.get("chapter") == chapter and b.get("id") == branch_id:
            return cast(dict, b)
    raise ValueError(f"故事线不存在: {branch_id}")


def touch_branch(chapter: int, branch_id: str) -> None:
    """Bumps updated_at after a branch produces a new round, for list_branches' ordering. No-op
    if the branch is missing (defensive only -- every branch a turn can run against was already
    created via create_branch/register_legacy_branch first)."""
    doc = _load()
    for b in doc["branches"]:
        if b.get("chapter") == chapter and b.get("id") == branch_id:
            b["updated_at"] = _now()
            _save(doc)
            return


def delete_branch(chapter: int, branch_id: str) -> dict:
    """Removes the branch record. If it was the last one for this chapter, creates a fresh blank
    replacement so the chapter always has at least one story line to write into. Returns the
    branch the caller should switch to: the most-recently-updated survivor, or the fresh
    replacement. Does NOT touch the checkpoint thread or event_log/vector-memory entries -- the
    caller (message_hub.delete_story_sandbox_branch) is responsible for that, since this module
    has no engine/checkpoint dependency."""
    doc = _load()
    before = len(doc["branches"])
    doc["branches"] = [
        b for b in doc["branches"] if not (b.get("chapter") == chapter and b.get("id") == branch_id)
    ]
    if len(doc["branches"]) == before:
        raise ValueError(f"故事线不存在: {branch_id}")
    remaining = sorted(
        (b for b in doc["branches"] if b.get("chapter") == chapter),
        key=lambda b: b.get("updated_at", ""), reverse=True,
    )
    if remaining:
        _save(doc)
        return cast(dict, remaining[0])
    n = _next_branch_number(chapter, doc["branches"])
    now = _now()
    replacement = {
        "id": str(uuid.uuid4()), "chapter": chapter, "name": f"故事线{n}",
        "created_at": now, "updated_at": now,
    }
    doc["branches"].append(replacement)
    _save(doc)
    return replacement
