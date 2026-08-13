"""Generic async elapsed-time logging for perf-sensitive hot paths (currently only
story_sandbox's turn graph, see docs/superpowers/specs/2026-08-03-sandbox-cast-resolve-and-
passerby-design.md section 3) -- not tied to story_sandbox specifically, any future
per-step perf instrumentation can reuse this."""
from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from loguru import logger


@asynccontextmanager
async def async_step_timer(
    step_name: str, *, log_prefix: str, extra_meta: dict | None = None,
) -> AsyncIterator[None]:
    start = time.perf_counter()
    logger.info("[{}] Node '{}' STARTED | meta={}", log_prefix, step_name, extra_meta or {})
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "[{}] Node '{}' COMPLETED | elapsed_ms={:.2f} | meta={}",
            log_prefix, step_name, elapsed_ms, extra_meta or {},
        )


@asynccontextmanager
async def sandbox_step_timer(
    step_name: str, extra_meta: dict | None = None,
) -> AsyncIterator[None]:
    async with async_step_timer(step_name, log_prefix="story_sandbox_perf", extra_meta=extra_meta):
        yield


@asynccontextmanager
async def setup_chat_step_timer(
    step_name: str, extra_meta: dict | None = None,
) -> AsyncIterator[None]:
    async with async_step_timer(step_name, log_prefix="setup_chat_perf", extra_meta=extra_meta):
        yield
