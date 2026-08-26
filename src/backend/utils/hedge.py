"""Generic delay-hedged execution: run an attempt; if it hasn't produced a result within
`delay` seconds, fire a second concurrent attempt and use whichever succeeds first. Framework-
agnostic (no LangChain/HTTP-specific code) so both llm/retry.py's RetryingChatModel and
domain/search_provider.py's ChronosCloudSearchProvider share this instead of each
reimplementing it. See docs/superpowers/specs/2026-08-26-cloud-auth-search-microservice-design.md's
hedge-utility section for why this was extracted and why the default delay (tuned for external
API calls) differs from LLM calls' 20s (see llm/retry.py::HEDGE_DELAY_S)."""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

T = TypeVar("T")

DEFAULT_DELAY_S = 5.0


async def _cancel_and_discard(task: asyncio.Task) -> None:
    """Cancel a losing race participant and await it so its CancelledError (or whatever it
    happened to raise) is retrieved -- otherwise asyncio logs "exception was never retrieved"
    once the task is garbage collected."""
    task.cancel()
    with contextlib.suppress(BaseException):  # noqa: BLE001 - deliberately discarding the loser
        await task


async def _race_first_success(tasks: set[asyncio.Task]) -> Any:
    """First task to complete WITHOUT raising wins; every other task is cancelled and
    discarded. If every task raises, re-raises the last exception seen."""
    pending = set(tasks)
    last_exc: BaseException | None = None
    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            exc = t.exception()
            if exc is None:
                for p in pending:
                    await _cancel_and_discard(p)
                return t.result()
            last_exc = exc
    assert last_exc is not None
    raise last_exc


async def hedged_call(
    make_attempt: Callable[[], Awaitable[T]],
    *,
    hedge_enabled: bool = False,
    delay: float = DEFAULT_DELAY_S,
) -> T:
    """Run make_attempt() once; if hedge_enabled and it hasn't produced a result (success or
    failure) within `delay` seconds, fire a second concurrent make_attempt() and return
    whichever succeeds first (the loser is cancelled). hedge_enabled=False is a plain
    passthrough -- no extra scheduling, no behavior change from calling make_attempt() directly."""
    if not hedge_enabled:
        return await make_attempt()
    primary = asyncio.ensure_future(make_attempt())
    done, _ = await asyncio.wait({primary}, timeout=delay)
    if primary in done:
        return primary.result()
    hedge = asyncio.ensure_future(make_attempt())
    return cast(T, await _race_first_success({primary, hedge}))
