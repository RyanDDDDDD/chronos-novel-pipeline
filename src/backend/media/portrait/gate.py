"""Process-wide serial gate for cloud image generation. NovelAI allows only ~1 concurrent
generation per account (web + API share it) -- more than that returns HTTP 429. This gate
serializes every provider.generate() call across the whole process (all novels, both
providers -- the NovelAI token is a single install-wide credential, so the limit is
per-account, never per-novel), spaces consecutive calls, and does 429-aware backoff. It
owns the retry loop that used to live inline in _run_portrait_generation."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx
from loguru import logger

_T = TypeVar("_T")

_MIN_INTERVAL_S = 3.0
_RATE_LIMIT_BACKOFF_S: tuple[float, ...] = (8.0, 20.0, 45.0)  # one per 429 retry; len == max retries
_TRANSIENT_BACKOFF_S = 2.0
_MAX_TRANSIENT_RETRIES = 2


def _is_rate_limited(exc: BaseException) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):  # connect/read/write/pool timeouts, conn errors
        return True
    return isinstance(exc, httpx.HTTPStatusError) and 500 <= exc.response.status_code < 600


class ImageGenGate:
    def __init__(
        self,
        *,
        min_interval_s: float = _MIN_INTERVAL_S,
        rate_limit_backoff_s: tuple[float, ...] = _RATE_LIMIT_BACKOFF_S,
        transient_backoff_s: float = _TRANSIENT_BACKOFF_S,
        max_transient_retries: int = _MAX_TRANSIENT_RETRIES,
    ) -> None:
        self._min_interval_s = min_interval_s
        self._rate_limit_backoff_s = rate_limit_backoff_s
        self._transient_backoff_s = transient_backoff_s
        self._max_transient_retries = max_transient_retries
        # Lazily created so a process-level singleton binds to whichever loop first calls
        # run() (same reason api.services.scheduler recreates its asyncio.Event on start()).
        self._lock: asyncio.Lock | None = None
        self._last_finished_at: float = 0.0

    async def run(self, call: Callable[[], Awaitable[_T]]) -> _T:
        """Serialize `call` behind the process-wide gate: wait for the lock (FIFO), honour
        the min inter-call interval, run with 429 + transient-error retry. Re-raises the
        final error once retries are exhausted (the caller broadcasts it)."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            await self._respect_interval()
            try:
                return await self._call_with_retry(call)
            finally:
                self._last_finished_at = asyncio.get_running_loop().time()

    async def _respect_interval(self) -> None:
        elapsed = asyncio.get_running_loop().time() - self._last_finished_at
        wait = self._min_interval_s - elapsed
        if wait > 0:
            await asyncio.sleep(wait)

    async def _call_with_retry(self, call: Callable[[], Awaitable[_T]]) -> _T:
        rate_limit_attempts = 0
        transient_attempts = 0
        while True:
            try:
                return await call()
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # noqa: BLE001 -- every branch re-raises or retries
                if _is_rate_limited(exc):
                    if rate_limit_attempts >= len(self._rate_limit_backoff_s):
                        raise
                    delay = self._rate_limit_backoff_s[rate_limit_attempts]
                    rate_limit_attempts += 1
                    logger.warning(
                        "[image-gen] 429 from provider, backing off {}s (retry {}/{})",
                        delay, rate_limit_attempts, len(self._rate_limit_backoff_s),
                    )
                    await asyncio.sleep(delay)
                    continue
                if _is_transient(exc):
                    if transient_attempts >= self._max_transient_retries:
                        raise
                    transient_attempts += 1
                    logger.warning(
                        "[image-gen] transient provider error, retry {}/{}: {}",
                        transient_attempts, self._max_transient_retries, exc,
                    )
                    await asyncio.sleep(self._transient_backoff_s)
                    continue
                raise  # permanent error (402/400/RuntimeError/...) -- surface immediately


IMAGE_GEN_GATE = ImageGenGate()
