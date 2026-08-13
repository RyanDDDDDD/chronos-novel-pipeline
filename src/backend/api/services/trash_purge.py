"""Startup purge of expired novels under novels/.trash/.

Registered as a once job from register_startup_warmup (api/hub.py). Retention is read from
config (novels.trash_retention_days); 0 disables purge."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import time

from loguru import logger
from utils.config import trash_retention_days
from utils.paths import novels_trash_dir

_META_NAME = "novel.json"
_SECONDS_PER_DAY = 86400


def trash_entry_deleted_at(entry_path: str) -> float | None:
    """Return unix seconds when this trash entry was deleted.

    Cascade: novel.json deleted_at, then directory mtime."""
    meta_path = os.path.join(entry_path, _META_NAME)
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        deleted_at = meta.get("deleted_at")
        if isinstance(deleted_at, (int, float)) and deleted_at > 0:
            return float(deleted_at)
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    try:
        return os.path.getmtime(entry_path)
    except OSError:
        return None


def purge_expired_trash(*, retention_days: int) -> int:
    """Remove trash entries older than retention_days. Returns purged count."""
    if retention_days <= 0:
        return 0
    trash_dir = novels_trash_dir()
    if not os.path.isdir(trash_dir):
        return 0
    cutoff = time.time() - retention_days * _SECONDS_PER_DAY
    trash_abs = os.path.abspath(trash_dir)
    purged = 0
    for name in os.listdir(trash_dir):
        entry_path = os.path.join(trash_dir, name)
        if not os.path.isdir(entry_path):
            logger.debug("[trash-purge] skip non-directory entry={}", name)
            continue
        if os.path.abspath(entry_path) != os.path.join(trash_abs, name):
            continue
        deleted_at = trash_entry_deleted_at(entry_path)
        if deleted_at is None or deleted_at >= cutoff:
            continue
        try:
            shutil.rmtree(entry_path)
            purged += 1
            logger.info("[trash-purge] purged entry={} deleted_at={}", name, deleted_at)
        except OSError:
            logger.exception("[trash-purge] failed to purge entry={}", name)
    return purged


async def run_trash_purge() -> None:
    days = trash_retention_days()
    if days <= 0:
        return
    count = await asyncio.to_thread(purge_expired_trash, retention_days=days)
    if count:
        logger.info("[trash-purge] purged {} expired entr(y/ies)", count)
