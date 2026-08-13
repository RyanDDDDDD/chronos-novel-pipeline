"""Periodic LRU eviction of idle/excess in-memory novel shards under multi-novel
concurrency. Mirrors heartbeat_watchdog.py's structure: module-level constants + a
periodic job registered on the process's EventScheduler.

This module owns no cache itself -- it only decides *which* novel_id to evict and
*when*, then calls four already-existing per-novel release functions. See
docs/superpowers/specs/2026-08-04-novel-memory-lru-scavenger-design.md for the full
design, especially why RSS is read once per tick and never re-read within the same
tick to decide whether to keep evicting (CPython/platform allocators don't reliably
return freed memory to the OS immediately, so re-measuring mid-tick is unreliable)."""
from __future__ import annotations

import gc
import time

import psutil
from engine.memory_recall.entity_index import invalidate_entity_vocab_cache
from loguru import logger
from repositories import drop_repositories, last_touched_at, loaded_novel_ids

from api.services.message_hub import MessageHub
from api.services.scheduler import EventScheduler

MEMORY_SCAN_INTERVAL_S = 60.0
MEMORY_HIGH_WATERMARK_BYTES = 300 * 1024 * 1024  # 300 MB process RSS -- lowered from the
# original 1.5GB once ChromaDB removal + disk-persisted tool-routing embeddings (2026-08-08/09)
# dropped single-novel steady-state RSS from ~1.6GB to ~300MB (see docs/superpowers/specs/
# 2026-08-08-chroma-to-sqlite-vector-store-migration-design.md and 2026-08-09-tool-vector-
# cache-persistence-design.md); the old threshold sat below even the pre-optimization baseline,
# so it never had headroom to actually evict anything.
IDLE_EVICT_TTL_S = 15 * 60.0  # 15 min
MAX_HIGH_WATER_EVICTIONS_PER_TICK = 1


def _current_rss_bytes() -> int | None:
    """This process's current physical memory usage, or None if unavailable (extreme
    edge case -- psutil.Process() construction or memory_info() itself failing). A
    None result only suppresses this tick's high-water branch; idle-TTL eviction is
    independent of this signal and still runs."""
    try:
        return int(psutil.Process().memory_info().rss)
    except psutil.Error:
        return None


async def _evict(hub: MessageHub, novel_id: str, reason: str) -> None:
    try:
        drop_repositories(novel_id)
        invalidate_entity_vocab_cache(novel_id)
        await hub.reset_setup_chat(novel_id)
        await hub.reset_story_sandbox(novel_id)
        gc.collect()  # best-effort for any cyclic refs (e.g. compiled LangGraph
        # objects); does not itself guarantee OS-visible RSS reduction -- see module
        # docstring.
        logger.info("[novel-memory-scavenger] evicted novel_id={} reason={}", novel_id, reason)
    except Exception:  # noqa: BLE001 - one novel's eviction failure must not block
        # the rest of this tick's candidates, mirroring scheduler._dispatch's own
        # per-job isolation.
        logger.exception("[novel-memory-scavenger] failed to evict novel_id={}", novel_id)


async def _scan(hub: MessageHub) -> None:
    now = time.monotonic()
    rss = _current_rss_bytes()
    focus = hub._gateway.get_focus()
    candidates = [
        nid
        for nid in loaded_novel_ids()
        if nid != focus
        and not hub.is_pipeline_busy(nid)
        and not hub.is_setup_chat_busy(nid)
        and not hub.is_story_sandbox_busy(nid)
    ]

    idle_ids = [
        nid for nid in candidates if now - (last_touched_at(nid) or 0.0) > IDLE_EVICT_TTL_S
    ]
    for nid in idle_ids:
        await _evict(hub, nid, "idle")

    if rss is not None and rss > MEMORY_HIGH_WATERMARK_BYTES:
        remaining = [nid for nid in candidates if nid not in idle_ids]
        remaining.sort(key=lambda nid: last_touched_at(nid) or 0.0)
        for nid in remaining[:MAX_HIGH_WATER_EVICTIONS_PER_TICK]:
            await _evict(hub, nid, "high_water")


def register_novel_memory_scavenger(scheduler: EventScheduler, hub: MessageHub) -> None:
    """Call once at startup (_lifespan, alongside register_heartbeat_watchdog)."""
    scheduler.register_periodic("novel_memory_scavenger", MEMORY_SCAN_INTERVAL_S, lambda: _scan(hub))
