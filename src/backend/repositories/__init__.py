"""Data access layer entry: in-process Engine singleton + repo accessor + life cycle.

During startup, init_repositories(); reset_repositories(); refresh_plot().

Sharded per novel_id rather than a single process-wide instance, so multiple novels can
each keep their own in-memory cache valid at the same time."""
from __future__ import annotations

from utils.paths import active_novel_id

from repositories.doc_repositories import WorldRepository
from repositories.engine import (
    _engines,
    dispose_engine,
    engine_for_novel,
    reset_archive_cache,
)
from repositories.engine import (
    _last_touched as _last_touched,
)
from repositories.engine import (
    last_touched_at as engine_last_touched_at,
)
from repositories.engine import (
    loaded_novel_ids as engine_loaded_novel_ids,
)
from repositories.sqlite_repositories import (
    SqliteArchiveRepository,
    SqliteLoreRepository,
    SqlitePlotRepository,
)
from repositories.timeline_repository import TimelineRepository
from repositories.vector_repositories import ResearchRepository, SandboxVectorMemoryRepository

_STORES = _engines
_RESEARCH = ResearchRepository()
_SANDBOX_VECTOR_MEMORY = SandboxVectorMemoryRepository()


def init_repositories(novel_id: str | None = None) -> None:
    """All structured data is loaded during startup for this novel (defaults to the currently
    active one). Pre-warms the Engine and runs migrations."""
    nid = novel_id or active_novel_id()
    engine_for_novel(nid)


def reset_repositories(novel_id: str | None = None) -> None:
    """Rebuild this novel's shard from disk (clears its structured + archive cache). Does not
    touch other novels' shards -- switching focus no longer destroys/rebuilds a shared cache."""
    nid = novel_id or active_novel_id()
    reset_archive_cache(nid)


def drop_repositories(novel_id: str) -> None:
    """Evict a novel's shard entirely (used on delete). Drops engine and archive cache."""
    dispose_engine(novel_id)
    reset_archive_cache(novel_id)


def loaded_novel_ids() -> list[str]:
    """Currently resident novel ids."""
    return engine_loaded_novel_ids()


def last_touched_at(novel_id: str) -> float | None:
    return engine_last_touched_at(novel_id)


def refresh_plot(novel_id: str | None = None) -> None:
    """No-op: plot is always read from DB directly."""


def get_lore_repo(novel_id: str | None = None) -> SqliteLoreRepository:
    return SqliteLoreRepository(novel_id or active_novel_id())


def get_plot_repo(novel_id: str | None = None) -> SqlitePlotRepository:
    return SqlitePlotRepository(novel_id or active_novel_id())


def get_archive_repo(novel_id: str | None = None) -> SqliteArchiveRepository:
    return SqliteArchiveRepository(novel_id or active_novel_id())


def get_world_repo(novel_id: str | None = None) -> WorldRepository:
    return WorldRepository(novel_id or active_novel_id())


def get_timeline_repo() -> TimelineRepository:
    return TimelineRepository()


def get_research_repo() -> ResearchRepository:
    return _RESEARCH


def get_sandbox_vector_memory_repo() -> SandboxVectorMemoryRepository:
    return _SANDBOX_VECTOR_MEMORY
