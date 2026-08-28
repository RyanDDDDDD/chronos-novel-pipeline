"""Per-novel Engine cache + Session helper. Replaces sqlite_store.get_connection's
connection cache and repositories/__init__._STORES. One Engine per novel_id over
data/novels/<id>/chronos.sqlite3; short-lived Session per operation."""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, event, pool
from sqlmodel import Session, create_engine
from utils.paths import active_novel_id, novel_db_path

_engines: dict[str, Engine] = {}
_engines_by_path: dict[str, Engine] = {}
_registry_engine_cache: list[Engine] = []
_archive_caches: dict[str, dict[str, dict]] = {}
_last_touched: dict[str, float] = {}
_lock = threading.Lock()


def _novel_db_path(novel_id: str) -> str:  # indirection point for tests
    return novel_db_path(novel_id)


def _make_engine(path: str) -> Engine:
    dirname = os.path.dirname(path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
        poolclass=pool.NullPool,
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _rec):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def engine_for_path(db_path: str) -> Engine:
    """Engine cache keyed by absolute db path -- for callers that hold a path, not a
    novel_id (SqliteVectorStore). Same migrate-on-first-open contract as engine_for_novel."""
    abs_path = os.path.abspath(db_path)
    with _lock:
        engine = _engines_by_path.get(abs_path)
        if engine is None:
            from repositories.migrations import ensure_novel_db_migrated

            ensure_novel_db_migrated(abs_path)
            engine = _make_engine(abs_path)
            _engines_by_path[abs_path] = engine
        return engine


def engine_for_novel(novel_id: str) -> Engine:
    abs_path = os.path.abspath(_novel_db_path(novel_id))
    with _lock:
        engine = _engines.get(novel_id)
        if engine is not None and str(getattr(engine, "url", "")) != f"sqlite:///{abs_path}":
            engine = None  # path changed under this id (test env swap); rebind below
    if engine is None:
        engine = engine_for_path(abs_path)
        with _lock:
            _engines[novel_id] = engine
    with _lock:
        _last_touched[novel_id] = time.monotonic()
    return engine


@contextmanager
def session_for(novel_id: str | None = None) -> Iterator[Session]:
    nid = novel_id or active_novel_id()
    with Session(engine_for_novel(nid)) as session:
        yield session


def registry_engine() -> Engine:
    from repositories.registry_store import registry_path

    path = registry_path()
    with _lock:
        if _registry_engine_cache:
            eng = _registry_engine_cache[0]
            if str(getattr(eng, "url", "")) != f"sqlite:///{path}":
                if hasattr(eng, "dispose"):
                    eng.dispose()
                _registry_engine_cache.clear()
        if not _registry_engine_cache:
            from repositories.migrations import ensure_registry_migrated

            ensure_registry_migrated(path)
            _registry_engine_cache.append(_make_engine(path))
        return _registry_engine_cache[0]


def dispose_engine(novel_id: str) -> None:
    abs_path = os.path.abspath(_novel_db_path(novel_id))
    with _lock:
        engine = _engines.pop(novel_id, None)
        _last_touched.pop(novel_id, None)
        path_engine = _engines_by_path.pop(abs_path, None)
    for e in (engine, path_engine):
        if e is not None and hasattr(e, "dispose"):
            e.dispose()


def archive_cache_for(novel_id: str) -> dict[str, dict]:
    return _archive_caches.setdefault(novel_id, {})


def reset_archive_cache(novel_id: str) -> None:
    _archive_caches.pop(novel_id, None)


def loaded_novel_ids() -> list[str]:
    with _lock:
        return list(_engines.keys())


def last_touched_at(novel_id: str) -> float | None:
    with _lock:
        return _last_touched.get(novel_id)


def touch(novel_id: str) -> None:
    with _lock:
        _last_touched[novel_id] = time.monotonic()
