"""Data access layer entry: in-process SqliteStore singleton + repo accessor + life cycle.

During startup, init_repositories(); reset_repositories(); reset the plot to disk refresh_plot().

Sharded per novel_id (dict) rather than a single process-wide instance, so multiple novels can
each keep their own in-memory cache valid at the same time -- switching which novel is "active"
no longer destroys and rebuilds a shared cache."""
from __future__ import annotations

import time

from utils.paths import active_novel_id

from repositories.doc_repositories import WorldRepository
from repositories.sqlite_repositories import (
    SqliteArchiveRepository,
    SqliteLoreRepository,
    SqlitePlotRepository,
)
from repositories.sqlite_store import SqliteStore
from repositories.timeline_repository import TimelineRepository
from repositories.vector_repositories import ResearchRepository, SandboxVectorMemoryRepository

_STORES: dict[str, SqliteStore] = {}
_last_touched: dict[str, float] = {}
_RESEARCH = ResearchRepository()
_SANDBOX_VECTOR_MEMORY = SandboxVectorMemoryRepository()


def _make_store(novel_id: str) -> SqliteStore:
    return SqliteStore(novel_id)


def _store(novel_id: str | None = None) -> SqliteStore:
    nid = novel_id or active_novel_id()
    _last_touched[nid] = time.monotonic()
    store = _STORES.get(nid)
    if store is None:
        store = _make_store(nid)
        _STORES[nid] = store
    return store


def init_repositories(novel_id: str | None = None) -> None:
    """All structured data is loaded during startup for this novel (defaults to the currently
    active one). Equivalent to old init_indexers + register_providers, now per-novel."""
    nid = novel_id or active_novel_id()
    _last_touched[nid] = time.monotonic()
    _STORES[nid] = _make_store(nid)


def reset_repositories(novel_id: str | None = None) -> None:
    """Rebuild this novel's shard from disk (clears its structured + archive cache). Does not
    touch other novels' shards -- switching focus no longer destroys/rebuilds a shared cache."""
    _store(novel_id).reset()


def drop_repositories(novel_id: str) -> None:
    """Evict a novel's shard entirely (used on delete, see Task 5) -- distinct from
    reset_repositories, which rebuilds in place; this removes the dict entry so a subsequent
    access (which shouldn't happen for a deleted novel, but defensively) rebuilds from scratch.
    Also drops the last-touched bookkeeping entry so it doesn't linger indefinitely across a
    long-running process building/deleting many novels over time."""
    store = _STORES.pop(novel_id, None)
    if store is not None:
        store.close()
    _last_touched.pop(novel_id, None)


def loaded_novel_ids() -> list[str]:
    """Currently resident novel ids -- authoritative via _STORES, not _last_touched (which
    may retain orphaned entries between an eviction and that novel's next access)."""
    return list(_STORES.keys())


def last_touched_at(novel_id: str) -> float | None:
    return _last_touched.get(novel_id)


def refresh_plot(novel_id: str | None = None) -> None:
    """plot_library Rescan after placing the order, for this novel."""
    _store(novel_id).refresh_plot()


def get_lore_repo(novel_id: str | None = None) -> SqliteLoreRepository:
    return SqliteLoreRepository(_store(novel_id))


def get_plot_repo(novel_id: str | None = None) -> SqlitePlotRepository:
    return SqlitePlotRepository(_store(novel_id))


def get_archive_repo(novel_id: str | None = None) -> SqliteArchiveRepository:
    return SqliteArchiveRepository(_store(novel_id))


def get_world_repo(novel_id: str | None = None) -> WorldRepository:
    return WorldRepository(_store(novel_id))


def get_timeline_repo() -> TimelineRepository:
    return TimelineRepository()


def get_research_repo() -> ResearchRepository:
    return _RESEARCH


def get_sandbox_vector_memory_repo() -> SandboxVectorMemoryRepository:
    return _SANDBOX_VECTOR_MEMORY
