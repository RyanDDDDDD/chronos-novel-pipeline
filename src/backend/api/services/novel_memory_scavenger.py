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
MEMORY_HIGH_WATERMARK_BYTES = 400 * 1024 * 1024  # 400 MB process RSS -- raised from 300MB
# (2026-08-15) after live-measuring the real single-novel steady-state floor at ~286MB
# (interpreter + fastapi/uvicorn/langchain_core + one warmed setup-chat/sandbox agent;
# an unrelated venv contamination -- torch/transformers accidentally pulled in by
# langchain_core's optional GPT2TokenizerFast fallback -- was inflating that floor to
# ~456MB and has been separately fixed, see docs/TECHNICAL_JOURNEY.md #35). The 300MB
# figure documented at the 2026-08-08/09 Chroma-removal baseline had already been below
# the real floor since the day it was set, so the watermark check was permanently true
# and evicting every tick regardless of actual novel count. 400MB leaves ~114MB of
# margin above the measured floor -- revisit if the single-novel floor itself moves
# (new heavy dependency, more warmup work, etc.).
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
