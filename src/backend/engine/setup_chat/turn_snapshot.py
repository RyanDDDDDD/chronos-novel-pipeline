"""Call-level transactional snapshot for setup-chat write tools (spec D2/D5/D7/D16).

One snapshot slot per novel, overwritten before each write-tool batch. Restore is
gated on tool_call_id intersection so a stale snapshot can never revert unrelated
state. Snapshot lives under setup_chat_dir()/snapshot -- inside the excluded zone,
so it never recursively captures itself."""
from __future__ import annotations

import fnmatch
import os
import shutil
import sqlite3
import time

from loguru import logger

_SNAPSHOT_DIRNAME = "snapshot"
_META_DOC_KEY = "snapshot_meta"

# Relative to active_novel_dir(), "/" separators. setup_chat/session hold the
# conversation ledger (repaired via messages, never via file rollback); the chapters/
# patterns are runtime artifacts (D16) -- in particular, the two *.sqlite entries are live
# LangGraph checkpoint databases that can be held open by an active connection, so
# snapshotting/restoring them risks a locked-file failure (see _restore()'s copy-before-
# delete ordering, which exists specifically to survive that failure without data loss).
# chronos.sqlite3 is also connection-cached and must use SQLite backup API instead of copy2.
_EXCLUDED_PATTERNS = (
    "chronos.sqlite3",
    "setup_chat",
    "setup_chat/*",
    "session",
    "session/*",
    "chapters/_author_loop_graph.sqlite",
    "chapters/_story_sandbox.sqlite",
    "chapters/*/chapter_*_journal.ndjson",
    "chapters/*/第*章_主笔.md",
)


def is_excluded(rel_path: str) -> bool:
    #Always normalize backslashes, not just os.sep -- rel_path can arrive Windows-style
    #(e.g. tool-call metadata recorded on Windows) regardless of the host OS running this
    #check, and on Linux os.sep == "/" would make this a no-op, leaving "\\"-joined paths
    #unmatched against the "/"-separated patterns above.
    rel = rel_path.replace("\\", "/")
    return any(fnmatch.fnmatch(rel, p) for p in _EXCLUDED_PATTERNS)


def _snapshot_root() -> str:
    from utils.paths import setup_chat_dir

    return os.path.join(setup_chat_dir(), _SNAPSHOT_DIRNAME)


def _files_dir() -> str:
    return os.path.join(_snapshot_root(), "files")


def _iter_included_files(base: str):
    """Yield rel paths of non-excluded files under base (excluded dirs pruned)."""
    for dirpath, dirnames, filenames in os.walk(base):
        rel_dir = os.path.relpath(dirpath, base)
        rel_dir = "" if rel_dir == "." else rel_dir
        dirnames[:] = [
            d for d in dirnames
            if not is_excluded(os.path.join(rel_dir, d) if rel_dir else d)
        ]
        for fn in filenames:
            rel = os.path.join(rel_dir, fn) if rel_dir else fn
            if not is_excluded(rel):
                yield rel


def _backup_chronos_sqlite(src_dir: str, dst_dir: str) -> None:
    from repositories.sqlite_store import get_connection

    live_db = os.path.join(src_dir, "chronos.sqlite3")
    if not os.path.exists(live_db):
        return
    dst_db = os.path.join(dst_dir, "chronos.sqlite3")
    os.makedirs(os.path.dirname(dst_db) or dst_dir, exist_ok=True)
    backup_conn = sqlite3.connect(dst_db)
    try:
        get_connection(live_db).backup(backup_conn)
    finally:
        backup_conn.close()


def _restore_chronos_sqlite(snap_dir: str, target_dir: str) -> None:
    from repositories.sqlite_store import get_connection

    snap_db = os.path.join(snap_dir, "chronos.sqlite3")
    if not os.path.exists(snap_db):
        return
    dst_db = os.path.join(target_dir, "chronos.sqlite3")
    src_conn = sqlite3.connect(snap_db)
    try:
        src_conn.backup(get_connection(dst_db))
    finally:
        src_conn.close()


def _meta_store():
    from repositories.sqlite_store import SqliteStore
    from utils.paths import active_novel_id

    return SqliteStore(active_novel_id())


def _write_meta(meta: dict) -> None:
    _meta_store().save_doc(_META_DOC_KEY, "", meta)


def take_snapshot(tool_call_ids: list[str], tool_names: list[str]) -> bool:
    """Copy the non-excluded novel tree + write meta. False on failure (degrade,
    never block the tool call -- snapshot is a defensive layer, spec §5.1)."""
    import utils.paths as paths

    src = paths.active_novel_dir()
    try:
        files = _files_dir()
        if os.path.isdir(files):
            shutil.rmtree(files)
        os.makedirs(files, exist_ok=True)
        for rel in _iter_included_files(src):
            dst = os.path.join(files, rel)
            os.makedirs(os.path.dirname(dst) or files, exist_ok=True)
            shutil.copy2(os.path.join(src, rel), dst)
        _backup_chronos_sqlite(src, files)
        meta = {
            "tool_call_ids": list(tool_call_ids),
            "tool_names": list(tool_names),
            "ts": time.time(),
            "resume_attempts": 0,
        }
        _write_meta(meta)
        return True
    except (OSError, sqlite3.Error) as e:
        logger.warning("[turn-snapshot] take_snapshot failed: {}", e)
        return False


def load_meta() -> dict | None:
    data = _meta_store().get_doc(_META_DOC_KEY, "")
    return data if isinstance(data, dict) else None


def restore_if_matches(dangling_ids: set[str]) -> bool:
    """Restore the snapshot iff dangling ids intersect the snapshot's ids (D5)."""
    meta = load_meta()
    if not meta:
        return False
    if not (set(meta.get("tool_call_ids") or []) & set(dangling_ids)):
        return False
    return _restore()


def _restore() -> bool:
    """Copy the snapshotted files back first, then remove whatever's left in dst that
    wasn't part of the snapshot (created since). Order matters: copy-back must happen
    before any deletion, so a failure partway through (a locked file, a permission error)
    can leave since-created extra files behind but can never destroy a file that already
    existed -- the previous delete-everything-then-copy-back order could delete a file
    like novel.json in its first pass and then abort before restoring it if the copy-back
    pass hit an OSError, silently destroying it with only a warning log."""
    import utils.paths as paths

    dst = paths.active_novel_dir()
    files = _files_dir()
    if not os.path.isdir(files):
        return False
    try:
        snapshot_rels = set(_iter_included_files(files))
        for rel in snapshot_rels:
            target = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(target) or dst, exist_ok=True)
            shutil.copy2(os.path.join(files, rel), target)
        _restore_chronos_sqlite(files, dst)
        # Empty leftover dirs are harmless and kept.
        for rel in list(_iter_included_files(dst)):
            if rel not in snapshot_rels:
                os.remove(os.path.join(dst, rel))
        return True
    except (OSError, sqlite3.Error) as e:
        logger.warning("[turn-snapshot] restore failed: {}", e)
        return False


def resume_attempts() -> int:
    meta = load_meta()
    if not meta:
        return 0
    try:
        return max(0, int(meta.get("resume_attempts") or 0))
    except (TypeError, ValueError):
        return 0


def bump_resume_attempts() -> int:
    meta = load_meta() or {"tool_call_ids": [], "tool_names": [], "ts": time.time()}
    n = resume_attempts() + 1
    meta["resume_attempts"] = n
    try:
        _write_meta(meta)
    except (OSError, sqlite3.Error) as e:
        logger.warning("[turn-snapshot] bump_resume_attempts failed: {}", e)
    return n


_TURN_SNAPSHOT_DIRNAME = "snapshot_turn"


def _turn_snapshot_root() -> str:
    from utils.paths import setup_chat_dir

    return os.path.join(setup_chat_dir(), _TURN_SNAPSHOT_DIRNAME)


def _turn_files_dir() -> str:
    return os.path.join(_turn_snapshot_root(), "files")


def snapshot_turn_start() -> bool:
    """Turn-level snapshot (D2): captures the pre-turn tree so a user cancel can undo every
    write this turn made, not just the last one (unlike take_snapshot/restore_if_matches,
    which is call-level and exists for the auto-resume dangling-call repair path)."""
    import utils.paths as paths

    src = paths.active_novel_dir()
    try:
        files = _turn_files_dir()
        if os.path.isdir(files):
            shutil.rmtree(files)
        os.makedirs(files, exist_ok=True)
        for rel in _iter_included_files(src):
            dst = os.path.join(files, rel)
            os.makedirs(os.path.dirname(dst) or files, exist_ok=True)
            shutil.copy2(os.path.join(src, rel), dst)
        _backup_chronos_sqlite(src, files)
        return True
    except (OSError, sqlite3.Error) as e:
        logger.warning("[turn-snapshot] snapshot_turn_start failed: {}", e)
        return False


def restore_turn_start() -> bool:
    """Unconditional restore (no id matching -- a user cancel always means 'undo this turn')."""
    import utils.paths as paths

    dst = paths.active_novel_dir()
    files = _turn_files_dir()
    if not os.path.isdir(files):
        return False
    try:
        snapshot_rels = set(_iter_included_files(files))
        for rel in snapshot_rels:
            target = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(target) or dst, exist_ok=True)
            shutil.copy2(os.path.join(files, rel), target)
        _restore_chronos_sqlite(files, dst)
        for rel in list(_iter_included_files(dst)):
            if rel not in snapshot_rels:
                os.remove(os.path.join(dst, rel))
        return True
    except (OSError, sqlite3.Error) as e:
        logger.warning("[turn-snapshot] restore_turn_start failed: {}", e)
        return False
