"""Persist a main-writer per-stage scene image to disk + a per-novel sidecar doc keyed by
(chapter, stage_index). Deliberately NOT in the LangGraph chapter checkpoint -- mirrors
media.scene.store (sandbox) and the memory-archive keeping their own docs. Filenames are
unix-timestamp-versioned so a regenerate yields a fresh URL (no stale browser cache)."""
from __future__ import annotations

import os
import time
from datetime import UTC, datetime

from repositories.sqlite_store import SqliteStore
from utils.paths import active_novel_id, author_scene_dir, author_scene_path

_DOC_KEY = "author_stage_scene_images"


def _key(chapter: int, stage_index: int) -> str:
    return f"{chapter}:{stage_index}"


def _load() -> dict:
    data = SqliteStore(active_novel_id()).get_doc(_DOC_KEY, "")
    return data if isinstance(data, dict) else {}


def _save(doc: dict) -> None:
    SqliteStore(active_novel_id()).save_doc(_DOC_KEY, "", doc)


def store_author_stage_scene_image(chapter: int, stage_index: int, image_bytes: bytes) -> str:
    """Write a fresh versioned file, delete the previous file for this (chapter, stage),
    record it in the sidecar doc, return the new filename."""
    os.makedirs(author_scene_dir(), exist_ok=True)
    doc = _load()
    old = doc.get(_key(chapter, stage_index))
    old_fn = old.get("filename") if isinstance(old, dict) else None

    filename = f"{chapter}_{stage_index}-{int(time.time())}.png"
    with open(author_scene_path(filename), "wb") as f:
        f.write(image_bytes)

    if old_fn and old_fn != filename:
        try:
            os.remove(author_scene_path(old_fn))
        except OSError:
            pass  # stale/already-gone -- not worth failing the regenerate over

    doc[_key(chapter, stage_index)] = {
        "filename": filename,
        "created_at": datetime.now(UTC).isoformat(),
    }
    _save(doc)
    return filename


def list_author_stage_scene_images(chapter: int) -> dict[str, str]:
    prefix = f"{chapter}:"
    out: dict[str, str] = {}
    for k, v in _load().items():
        if (
            isinstance(k, str) and k.startswith(prefix)
            and isinstance(v, dict) and v.get("filename")
        ):
            out[k[len(prefix):]] = str(v["filename"])
    return out


def author_stage_scene_image_filename(chapter: int, stage_index: int) -> str | None:
    v = _load().get(_key(chapter, stage_index))
    return str(v["filename"]) if isinstance(v, dict) and v.get("filename") else None


def clear_author_stage_scene_images(chapter: int) -> None:
    """Drop every sidecar entry for `chapter` and remove its files. Called on chapter
    restart / clear (see api.services.message_hub) so a re-run doesn't show stale scene art."""
    prefix = f"{chapter}:"
    doc = _load()
    remaining = {}
    for k, v in doc.items():
        if isinstance(k, str) and k.startswith(prefix):
            fn = v.get("filename") if isinstance(v, dict) else None
            if fn:
                try:
                    os.remove(author_scene_path(str(fn)))
                except OSError:
                    pass
        else:
            remaining[k] = v
    if len(remaining) != len(doc):
        _save(remaining)
