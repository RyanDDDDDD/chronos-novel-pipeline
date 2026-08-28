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
from repositories import registry_store
from repositories.sqlite_store import SqliteStore
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
        return registry_store.existing_ids()
    except Exception:
        return []


def _is_deleted(nid: str) -> bool:
    """Deleted: registry row has non-null deleted_at."""
    try:
        return registry_store.is_deleted(nid)
    except Exception:
        return False


def _registry_row(nid: str) -> tuple[str, str] | None:
    try:
        row = registry_store.novel_row(nid)
        return (row.id, row.name) if row is not None else None
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
    from repositories.engine import dispose_engine

    dispose_engine(nid)
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
        for nid, name, pinned_at in registry_store.visible_ordered():
            out.append({
                "id": nid, "name": name or nid,
                "active": nid == active, "pinned": pinned_at is not None,
            })
    except Exception:
        pass
    return out


def set_novel_pinned(nid: str, pinned: bool) -> None:
    """Pin/unpin a novel for the sidebar's top-of-list ordering. pinned_at also doubles as the
    sort key among multiple pinned novels (see list_novels), so pinning an already-pinned novel
    again refreshes it to the top rather than being a no-op."""
    if _registry_row(nid) is None:
        raise ValueError(f"小说不存在: {nid}")
    registry_store.set_pinned(nid, _now_iso() if pinned else None)


def set_active(nid: str) -> None:
    if _registry_row(nid) is None:
        raise ValueError(f"小说不存在: {nid}")
    if _is_deleted(nid):
        raise ValueError(f"小说已删除: {nid}")
    registry_store.set_active(nid)


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
    from repositories.engine import engine_for_novel
    from repositories.models import Document, SandboxEvent, SessionMessage
    from sqlalchemy import delete
    from sqlmodel import Session, col

    with Session(engine_for_novel(nid)) as s:
        s.exec(delete(SessionMessage))
        s.exec(delete(SandboxEvent))
        s.exec(delete(Document).where(col(Document.doc_key).in_(_COPY_PURGE_DOC_KEYS)))
        s.commit()


def _insert_registry_row(nid: str, name: str, *, is_active: bool = False) -> None:
    registry_store.insert_novel(nid, name, _now_iso(), is_active=is_active)


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
    src_franchise = src_settings.get("source_franchise")
    if isinstance(src_franchise, str) and src_franchise.strip():
        settings["source_franchise"] = src_franchise.strip()
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
    registry_store.rename_novel(nid, name)


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


def get_source_franchise(nid: str) -> str:
    """The existing work this novel is fan fiction of (e.g. 'Blue Archive'); '' = original work.
    Fed to the portrait visual-tag extractor so it can lead with the danbooru character tag."""
    value = _read_novel_settings(nid).get("source_franchise")
    return value.strip() if isinstance(value, str) else ""


def set_source_franchise(nid: str, value: str) -> None:
    """Merge-write source_franchise into the novel_settings doc."""
    if _registry_row(nid) is None:
        raise ValueError(f"小说不存在: {nid}")
    _merge_novel_settings(nid, {"source_franchise": (value or "").strip()})


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
        registry_store.mark_deleted(nid, _now_iso())
        _heal_active()

    _schedule_trash_move(nid, release_handles or _noop_release)


def _heal_active() -> None:
    """When active points to a novel that does not exist, has been deleted, or lacks a physical
    directory, correct it to the first visible novel."""
    try:
        ids = registry_store.visible_ids_sorted()
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
    registry_store.insert_novel("default", "默认", _now_iso(), is_active=True)
    _write_default_novel_settings("default")
