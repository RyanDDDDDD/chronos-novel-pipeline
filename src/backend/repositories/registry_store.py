"""Cross-novel registry: data/novels/_registry.sqlite3, one row per novel (id/name/created_at/
is_active/deleted_at/pinned_at). Independent of any single novel's chronos.sqlite3 -- lives
outside active_novel_dir() so the main process can list/switch novels without opening a novel's
full per-novel store.

Consumers go through the typed helpers below (list_novels / set_active / ...), not raw SQL.
get_registry_connection() stays only as a shim for tests that still poke the table directly."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import delete
from sqlmodel import Session, col, select

from repositories.engine import registry_engine
from repositories.registry_models import Novel


def registry_path() -> str:
    import os

    from utils.paths import novels_dir

    return os.path.join(novels_dir(), "_registry.sqlite3")


@contextmanager
def _session() -> Iterator[Session]:
    with Session(registry_engine()) as s:
        yield s


def get_registry_connection() -> sqlite3.Connection:
    """Shim: raw sqlite3 handle on the (migrated) registry db. Prefer the typed helpers."""
    from repositories.migrations import ensure_registry_migrated

    path = registry_path()
    ensure_registry_migrated(path)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---- reads ----

def existing_ids() -> list[str]:
    with _session() as s:
        return list(s.exec(select(Novel.id)).all())


def novel_row(nid: str) -> Novel | None:
    with _session() as s:
        return s.get(Novel, nid)


def novel_name(nid: str) -> str | None:
    row = novel_row(nid)
    return row.name if row is not None else None


def is_deleted(nid: str) -> bool:
    row = novel_row(nid)
    return row is not None and row.deleted_at is not None


def active_id() -> str | None:
    with _session() as s:
        return s.exec(
            select(Novel.id).where(col(Novel.is_active) == 1).limit(1)
        ).one_or_none()


def visible_ids_sorted() -> list[str]:
    """Ids of not-deleted novels, ordered by id."""
    with _session() as s:
        return list(
            s.exec(
                select(Novel.id).where(col(Novel.deleted_at).is_(None)).order_by(col(Novel.id))
            ).all()
        )


def visible_ordered() -> list[tuple[str, str, str | None]]:
    """(id, name, pinned_at) for not-deleted novels: pinned first (pinned_at DESC), then name."""
    with _session() as s:
        rows = s.exec(
            select(Novel.id, Novel.name, Novel.pinned_at)
            .where(col(Novel.deleted_at).is_(None))
            .order_by(
                col(Novel.pinned_at).is_(None).asc(),
                col(Novel.pinned_at).desc(),
                col(Novel.name).asc(),
            )
        ).all()
    return [(r[0], r[1], r[2]) for r in rows]


# ---- writes ----

def insert_novel(nid: str, name: str, created_at: str, *, is_active: bool = False) -> None:
    with _session() as s:
        s.add(Novel(id=nid, name=name, created_at=created_at, is_active=1 if is_active else 0))
        s.commit()


def rename_novel(nid: str, name: str) -> None:
    with _session() as s:
        row = s.get(Novel, nid)
        if row is not None:
            row.name = name
            s.commit()


def set_pinned(nid: str, pinned_at: str | None) -> None:
    with _session() as s:
        row = s.get(Novel, nid)
        if row is not None:
            row.pinned_at = pinned_at
            s.commit()


def mark_deleted(nid: str, deleted_at: str) -> None:
    with _session() as s:
        row = s.get(Novel, nid)
        if row is not None:
            row.deleted_at = deleted_at
            s.commit()


def set_active(nid: str) -> None:
    from sqlalchemy import update

    with _session() as s:
        s.exec(update(Novel).values(is_active=0))
        row = s.get(Novel, nid)
        if row is not None:
            row.is_active = 1
        s.commit()


def delete_row(nid: str) -> None:
    """Hard-delete a registry row (used by tests / cleanup, not the normal soft-delete flow)."""
    with _session() as s:
        s.exec(delete(Novel).where(col(Novel.id) == nid))
        s.commit()
