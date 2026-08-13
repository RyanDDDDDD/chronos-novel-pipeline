"""Persists a generated portrait image to disk and records it on the character's lore entry
(`portrait_path`, a filename served via GET /api/character-portrait/{name}/file -- see
api/routes.py). Filenames are versioned with a unix timestamp so a regenerate always produces
a new URL (avoids the browser caching the old image at a stale path)."""
from __future__ import annotations

import os
import time


def store_portrait(character_name: str, image_bytes: bytes) -> str:
    """Write `image_bytes` to a new versioned portrait file, delete the character's previous
    portrait file (if any), and record the new relative filename on their lore entry. Returns
    the stored `portrait_path` value. Raises ValueError if the character does not exist."""
    from repositories import get_lore_repo
    from utils.paths import portrait_dir, portrait_path

    repo = get_lore_repo()
    raw = next((c for c in repo.list_raw() if c.get("name") == character_name), None)
    if raw is None:
        raise ValueError(f"角色不存在：{character_name}")

    old_relative = raw.get("portrait_path")

    os.makedirs(portrait_dir(), exist_ok=True)
    relative = f"{character_name}-{int(time.time())}.png"
    with open(portrait_path(relative), "wb") as f:
        f.write(image_bytes)

    if old_relative and old_relative != relative:
        try:
            os.remove(portrait_path(old_relative))
        except OSError:
            pass  # stale/already-gone file -- not worth failing the whole regenerate over

    repo.upsert_character({**raw, "portrait_path": relative})
    return relative
