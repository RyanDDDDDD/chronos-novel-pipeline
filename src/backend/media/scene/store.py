"""Persist a sandbox scene image to disk + a per-novel sidecar doc keyed by
(chapter, branch_id, round_id). Deliberately NOT stored in the LangGraph checkpoint turn
state -- mirrors how engine.story_sandbox.branches and the memory-archive keep their own
docs. Filenames are unix-timestamp-versioned so a regenerate produces a fresh URL (no stale
browser cache), same trick as media.portrait.service.store_portrait."""
from __future__ import annotations

import os
import time
from datetime import UTC, datetime

from repositories.sqlite_store import SqliteStore
from utils.paths import active_novel_id, sandbox_scene_dir, sandbox_scene_path

_DOC_KEY = "story_sandbox_scene_images"


def _key(chapter: int, branch_id: str, round_id: str) -> str:
    return f"{chapter}:{branch_id}:{round_id}"


def _load() -> dict:
    data = SqliteStore(active_novel_id()).get_doc(_DOC_KEY, "")
    return data if isinstance(data, dict) else {}


def _save(doc: dict) -> None:
    SqliteStore(active_novel_id()).save_doc(_DOC_KEY, "", doc)


def store_sandbox_scene_image(
    chapter: int, branch_id: str, round_id: str, image_bytes: bytes,
) -> str:
    """Write a fresh versioned file, delete the previous file for this
    (chapter, branch, round), record it in the sidecar doc, return the new filename."""
    os.makedirs(sandbox_scene_dir(), exist_ok=True)
    doc = _load()
    old = doc.get(_key(chapter, branch_id, round_id))
    old_fn = old.get("filename") if isinstance(old, dict) else None

    filename = f"{chapter}_{branch_id}_{round_id}-{int(time.time())}.png"
    with open(sandbox_scene_path(filename), "wb") as f:
        f.write(image_bytes)

    if old_fn and old_fn != filename:
        try:
            os.remove(sandbox_scene_path(old_fn))
        except OSError:
            pass  # stale/already-gone -- not worth failing the whole regenerate over

    doc[_key(chapter, branch_id, round_id)] = {
        "filename": filename,
        "created_at": datetime.now(UTC).isoformat(),
    }
    _save(doc)
    return filename


def list_sandbox_scene_images(chapter: int, branch_id: str) -> dict[str, str]:
    prefix = f"{chapter}:{branch_id}:"
    out: dict[str, str] = {}
    for k, v in _load().items():
        if (
            isinstance(k, str) and k.startswith(prefix)
            and isinstance(v, dict) and v.get("filename")
        ):
            out[k[len(prefix):]] = str(v["filename"])
    return out


def sandbox_scene_image_filename(chapter: int, branch_id: str, round_id: str) -> str | None:
    v = _load().get(_key(chapter, branch_id, round_id))
    return str(v["filename"]) if isinstance(v, dict) and v.get("filename") else None
