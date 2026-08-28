"""Novel files: scan to enumerate, switch, create (blank/clone), rename, delete, one-time initialization.

According to pipeline_profiles, replace it with the content axis. Each novel data/novels/<id>/{lore,plot,chapters},
display name and lifecycle live in the cross-novel registry (_registry.sqlite3). The factory sample novel default
is stored in the warehouse; the user creates a new novel gitignore.

Deletion: First, mark deleted_at in registry (the list is immediately hidden) → EventScheduler asynchronously
releases the handle → Move the entire directory into .trash."""
from __future__ import annotations

import os
import re
import shutil
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from loguru import logger
from repositories.registry_store import get_registry_connection
from repositories.sqlite_store import SqliteStore, get_connection
from utils.paths import (
    active_novel_id,
    novel_dir,
    novels_trash_dir,
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_TRASH_DIRNAME = ".trash"
_MOVE_ERR = "无法移入回收站，文件可能被占用（请先结束设定对话/主笔循环后重试）"
# Skip when copying novels: setup_chat/session hold runtime conversation state.
_COPY_SKIP_TOP = frozenset({"setup_chat", "session"})
# Doc keys cleared after copy_novel copies chronos.sqlite3 (runtime/session data must not carry over).
_COPY_PURGE_DOC_KEYS = (
    "token_ledger",
    "setup_chat_memory",
    "snapshot_meta",
)

ReleaseHandles = Callable[[], Awaitable[None]]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _settings_store(nid: str) -> SqliteStore:
    return SqliteStore(nid)


def _read_novel_settings(nid: str) -> dict:
    data = _settings_store(nid).get_doc("novel_settings", "")
    return data if isinstance(data, dict) else {}


def _write_novel_settings(nid: str, settings: dict) -> None:
    _settings_store(nid).save_doc("novel_settings", "", settings)


def _merge_novel_settings(nid: str, patch: dict) -> dict:
    settings = _read_novel_settings(nid)
    settings.update(patch)
    _write_novel_settings(nid, settings)
    return settings


def _existing_ids() -> list[str]:
    try:
        rows = get_registry_connection().execute("SELECT id FROM novels").fetchall()
        return [str(row[0]) for row in rows if row and row[0]]
    except Exception:
        return []


def _is_deleted(nid: str) -> bool:
    """Deleted: registry row has non-null deleted_at."""
    try:
        row = get_registry_connection().execute(
            "SELECT deleted_at FROM novels WHERE id = ?",
            (nid,),
        ).fetchone()
        return row is not None and row[0] is not None
    except Exception:
        return False


def _registry_row(nid: str) -> tuple[str, str] | None:
    try:
        row = get_registry_connection().execute(
            "SELECT id, name FROM novels WHERE id = ?",
            (nid,),
        ).fetchone()
        if row is None:
            return None
        return str(row[0]), str(row[1])
    except Exception:
        return None


def _resolve_trash_dest(nid: str) -> str:
    os.makedirs(novels_trash_dir(), exist_ok=True)
    dst = os.path.join(novels_trash_dir(), nid)
    if os.path.exists(dst):
        dst = os.path.join(novels_trash_dir(), f"{nid}-{int(time.time())}")
    return dst


def move_novel_to_trash(nid: str) -> None:
    """Move the novel folder in the root directory into .trash (idempotent: skip if the source does not exist)."""
    from repositories.sqlite_store import close_connection

    db_path = os.path.join(novel_dir(nid), "chronos.sqlite3")
    close_connection(db_path)
    src = novel_dir(nid)
    if not os.path.isdir(src):
        return
    dst = _resolve_trash_dest(nid)
    try:
        shutil.move(src, dst)
    except OSError as e:
        raise ValueError(_MOVE_ERR) from e


async def _noop_release() -> None:
    pass


def _schedule_trash_move(nid: str, release: ReleaseHandles) -> None:
    """
Asynchronously move trash after marking: first release the handle (such as setup-chat sqlite), and then physically move it."""
    from api.services.scheduler import SCHEDULER

    async def _job() -> None:
        await release()
        try:
            move_novel_to_trash(nid)
        except ValueError:
            logger.exception("[novels] 移入回收站失败 nid={}", nid)
            raise

    SCHEDULER.schedule_once(f"novel_trash:{nid}", 0.0, _job, dedup=True)


def slugify(name: str) -> str:
    """Filesystem security slug; pure non-ASCII (Chinese) tell-all novel-<n>."""
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    existing = set(_existing_ids())
    if slug:
        base, n = slug, 1
        while slug in existing:
            n += 1
            slug = f"{base}-{n}"
        return slug
    n = len(existing) + 1
    while f"novel-{n}" in existing:
        n += 1
    return f"novel-{n}"


def list_novels() -> list[dict]:
    """Registry query returns [{id, name, active, pinned}]. Pinned novels sort first (most
    recently pinned on top, via pinned_at DESC); unpinned novels keep the existing name order."""
    active = active_novel_id()
    out: list[dict] = []
    try:
        rows = get_registry_connection().execute(
            "SELECT id, name, pinned_at FROM novels WHERE deleted_at IS NULL "
            "ORDER BY (pinned_at IS NULL) ASC, pinned_at DESC, name ASC",
        ).fetchall()
        for row in rows:
            nid, name, pinned_at = str(row[0]), str(row[1]), row[2]
            out.append({"id": nid, "name": name or nid, "active": nid == active, "pinned": pinned_at is not None})
    except Exception:
        pass
    return out


def set_novel_pinned(nid: str, pinned: bool) -> None:
    """Pin/unpin a novel for the sidebar's top-of-list ordering. pinned_at also doubles as the
    sort key among multiple pinned novels (see list_novels), so pinning an already-pinned novel
    again refreshes it to the top rather than being a no-op."""
    if _registry_row(nid) is None:
        raise ValueError(f"小说不存在: {nid}")
    conn = get_registry_connection()
    conn.execute(
        "UPDATE novels SET pinned_at = ? WHERE id = ?",
        (_now_iso() if pinned else None, nid),
    )
    conn.commit()


def set_active(nid: str) -> None:
    if _registry_row(nid) is None:
        raise ValueError(f"小说不存在: {nid}")
    if _is_deleted(nid):
        raise ValueError(f"小说已删除: {nid}")
    conn = get_registry_connection()
    conn.execute("BEGIN")
    try:
        conn.execute("UPDATE novels SET is_active = 0")
        conn.execute("UPDATE novels SET is_active = 1 WHERE id = ?", (nid,))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _copy_novel_contents(src: str, dst: str) -> None:
    """Copy the settings/story directory tree (including chronos.sqlite3 when present)."""
    os.makedirs(dst, exist_ok=True)
    for entry in os.listdir(src):
        if entry in _COPY_SKIP_TOP:
            continue
        s = os.path.join(src, entry)
        d = os.path.join(dst, entry)
        if os.path.isdir(s):
            shutil.copytree(s, d)
        elif entry != "token_ledger.json":
            shutil.copy2(s, d)


def _purge_copied_runtime_data(nid: str) -> None:
    """Strip session/token/setup-chat runtime data accidentally copied via chronos.sqlite3."""
    db_path = os.path.join(novel_dir(nid), "chronos.sqlite3")
    if not os.path.isfile(db_path):
        return
    conn = get_connection(db_path)
    conn.execute("DELETE FROM session_messages")
    conn.execute("DELETE FROM sandbox_events")
    placeholders = ",".join("?" * len(_COPY_PURGE_DOC_KEYS))
    conn.execute(
        f"DELETE FROM documents WHERE doc_key IN ({placeholders})",
        _COPY_PURGE_DOC_KEYS,
    )
    conn.commit()


def _insert_registry_row(nid: str, name: str, *, is_active: bool = False) -> None:
    conn = get_registry_connection()
    conn.execute(
        "INSERT INTO novels (id, name, created_at, is_active) VALUES (?, ?, ?, ?)",
        (nid, name, _now_iso(), 1 if is_active else 0),
    )
    conn.commit()


def copy_novel(source_id: str, name: str) -> str:
    """Copies settings and plot from the specified novel to a new file (new ID); purges runtime sqlite data."""
    if _registry_row(source_id) is None:
        raise ValueError(f"小说不存在: {source_id}")
    if _is_deleted(source_id):
        raise ValueError(f"小说已删除: {source_id}")
    src = novel_dir(source_id)
    nid = slugify(name)
    dst = novel_dir(nid)
    src_settings = _read_novel_settings(source_id)
    src_prose = src_settings.get("prose_style")
    if not isinstance(src_prose, dict):
        src_prose = dict(_DEFAULT_PROSE_STYLE)
    if os.path.isdir(src):
        _copy_novel_contents(src, dst)
    else:
        os.makedirs(dst, exist_ok=True)
    _purge_copied_runtime_data(nid)
    _insert_registry_row(nid, name)
    settings: dict = {"prose_style": src_prose}
    sandbox_count = src_settings.get("sandbox_dialogue_turn_count")
    if isinstance(sandbox_count, int) and not isinstance(sandbox_count, bool):
        settings["sandbox_dialogue_turn_count"] = sandbox_count
    _write_novel_settings(nid, settings)
    return nid


def create_novel(name: str, clone: bool = False) -> str:
    """Create a new novel. clone=True copies the current active novel (same character, make a variant);
    clone=False Blank: lore/plot data lives in chronos.sqlite3 (created lazily on first SqliteStore
    access), only chapters/ needs pre-creating for prose .md / journal.ndjson / checkpoint files."""
    if clone:
        return copy_novel(active_novel_id(), name)
    nid = slugify(name)
    dst = novel_dir(nid)
    os.makedirs(os.path.join(dst, "chapters"), exist_ok=True)
    _insert_registry_row(nid, name)
    _write_default_novel_settings(nid)
    return nid


def rename_novel(nid: str, name: str) -> None:
    """Only the registry display name changes; directory id remains unchanged."""
    if _registry_row(nid) is None:
        raise ValueError(f"小说不存在: {nid}")
    conn = get_registry_connection()
    conn.execute("UPDATE novels SET name = ? WHERE id = ?", (name, nid))
    conn.commit()


def get_novel_name(nid: str) -> str:
    """Display name from registry; falls back to the novel id when missing/unreadable."""
    row = _registry_row(nid)
    if row is None:
        return nid
    _nid, name = row
    return name if name else nid


_DEFAULT_PROSE_STYLE = {"preset": "plain-direct", "custom_addendum": ""}


def _write_default_novel_settings(nid: str, prose_style: dict | None = None) -> None:
    ps = prose_style if prose_style is not None else dict(_DEFAULT_PROSE_STYLE)
    _write_novel_settings(nid, {"prose_style": ps})


def get_prose_style(nid: str) -> dict[str, str]:
    """Read prose_style from novel_settings doc; defaults to
    engine.execution.prose_style.default_prose_style_preset() when unset."""
    from engine.execution.prose_style import default_prose_style_preset

    ps = _read_novel_settings(nid).get("prose_style") or {}
    if not isinstance(ps, dict):
        ps = {}
    preset = ps.get("preset") or default_prose_style_preset()
    return {
        "preset": preset,
        "custom_addendum": ps.get("custom_addendum") or "",
    }


def set_prose_style(nid: str, preset: str, custom_addendum: str) -> None:
    """Merge-write prose_style into novel_settings doc."""
    if _registry_row(nid) is None:
        raise ValueError(f"小说不存在: {nid}")
    _merge_novel_settings(nid, {"prose_style": {"preset": preset, "custom_addendum": custom_addendum}})


def get_sandbox_dialogue_turn_count(nid: str) -> int | None:
    """Read sandbox_dialogue_turn_count from novel_settings; None (missing/invalid/out-of-range) =
    auto mode, caller falls back to len(present_names) + 1."""
    v = _read_novel_settings(nid).get("sandbox_dialogue_turn_count")
    return v if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 20 else None


def set_sandbox_dialogue_turn_count(nid: str, value: int | None) -> None:
    """Merge-write sandbox_dialogue_turn_count into novel_settings; None clears back to auto."""
    if _registry_row(nid) is None:
        raise ValueError(f"小说不存在: {nid}")
    _merge_novel_settings(nid, {"sandbox_dialogue_turn_count": value})


def delete_novel(nid: str, *, release_handles: ReleaseHandles | None = None) -> None:
    """Delete the novel: Mark deleted and heal active, then asynchronously release the handle through the scheduler and then move it into .trash.

    It is forbidden to delete until there is only one novel left (only the novel can be seen in the statistical list). legacy Only books that have not been moved can be deleted again to trigger relocation."""

    if nid not in _existing_ids():
        raise ValueError(f"小说不存在: {nid}")
    if not os.path.isdir(novel_dir(nid)):
        return  # moved trash

    already_marked = _is_deleted(nid)
    visible = [i for i in _existing_ids() if not _is_deleted(i)]
    if not already_marked and len(visible) <= 1:
        raise ValueError("至少保留一部小说")

    if not already_marked:
        conn = get_registry_connection()
        conn.execute(
            "UPDATE novels SET deleted_at = ? WHERE id = ?",
            (_now_iso(), nid),
        )
        conn.commit()
        _heal_active()

    _schedule_trash_move(nid, release_handles or _noop_release)


def _heal_active() -> None:
    """When active points to a novel that does not exist, has been deleted, or lacks a physical
    directory, correct it to the first visible novel."""
    try:
        rows = get_registry_connection().execute(
            "SELECT id FROM novels WHERE deleted_at IS NULL ORDER BY id",
        ).fetchall()
        ids = [str(row[0]) for row in rows if row and row[0]]
    except Exception:
        ids = []
    active = active_novel_id()
    needs_heal = bool(
        ids
        and (
            active not in ids
            or not os.path.isdir(novel_dir(active))
        )
    )
    if needs_heal:
        set_active(sorted(ids)[0])


def ensure_initialized() -> None:
    """Idempotent initialization: There is a novel → Correct the dangling active; otherwise, create a blank default.

    Factory example novel is shipped by default (data/novels/default/chronos.sqlite3), fresh checkout
    no migration required. This function handles the empty novels root case (like a fresh
    CHRONOS_NOVELS_DIR/TEST)."""

    if _existing_ids():
        _heal_active()
        return
    dst = novel_dir("default")
    os.makedirs(os.path.join(dst, "chapters"), exist_ok=True)
    conn = get_registry_connection()
    conn.execute(
        "INSERT INTO novels (id, name, created_at, is_active) VALUES (?, ?, ?, ?)",
        ("default", "默认", _now_iso(), 1),
    )
    conn.commit()
    _write_default_novel_settings("default")
