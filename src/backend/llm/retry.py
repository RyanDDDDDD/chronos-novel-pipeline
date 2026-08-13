"""Shared retry primitives for transient LLM network failures (timeouts, connection resets,
rate limits).

Long-lived provider streams (DeepSeek et al.) occasionally have their underlying TCP connection
reset mid-response by an intermediary (provider edge proxy, local NAT/AV middlebox) -- this
surfaces as httpx.TransportError / openai.APIConnectionError partway through iteration, not as
a clean pre-request failure. It isn't caused by anything in this codebase and can't be fixed
here -- the only recourse is retrying the request.

Separately, shared-pool OpenRouter models (e.g. qwen2.5-vl-72b-instruct) return HTTP 429 /
openai.RateLimitError when *other tenants* saturate the upstream provider's shared quota --
also outside this codebase's control. Unlike a transport drop, an instant retry usually still
hits the same 429, so rate-limit retries get their own (longer) backoff schedule via
RetryingChatModel below.

Separately again: direct API calls to mainland-China-hosted providers see wide, unpredictable
response-time variance (seconds to minutes) with NO exception raised at all -- the connection
stays open, the provider is just slow. Neither mechanism above ever fires for this case.
`hedge_enabled` instances race a delayed duplicate request (HEDGE_DELAY_S) against the original
once it's been pending too long, taking whichever finishes first -- a distinct axis from
error-triggered retry (each side of the race still independently retries its own transport/
rate-limit errors) and only safe for cloud endpoints, never a local single-instance inference
server where a duplicate request only steals compute from the first one. See
docs/superpowers/specs/2026-08-12-llm-call-hedged-request-design.md."""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, cast

from langchain_core.runnables.base import RunnableBindingBase
from langchain_core.runnables.config import RunnableConfig

DEFAULT_RETRIES = 2
DEFAULT_BACKOFF_S: tuple[float, ...] = (2.0, 5.0)

RATE_LIMIT_RETRIES = 2
RATE_LIMIT_BACKOFF_S: tuple[float, ...] = (5.0, 15.0)

HEDGE_DELAY_S = 20.0


def _retryable_excs() -> tuple[type[BaseException], ...]:
    excs: list[type[BaseException]] = [asyncio.TimeoutError]
    try:
        import httpx
        excs += [httpx.TimeoutException, httpx.TransportError]
    except ImportError:
        pass
    try:
        import openai
        excs += [openai.APITimeoutError, openai.APIConnectionError]
    except ImportError:
        pass
    return tuple(excs)


def _rate_limit_excs() -> tuple[type[BaseException], ...]:
    try:
        import openai
        return (openai.RateLimitError,)
    except ImportError:
        return ()


RETRYABLE_TRANSPORT_ERRORS = _retryable_excs()
RATE_LIMIT_ERRORS = _rate_limit_excs()


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


async def _first_chunk(
    gen: AsyncIterator[Any],
) -> tuple[AsyncIterator[Any], Any, BaseException | None]:
    """Pull exactly one item off an async generator, reporting the outcome as data (not by
    raising) so callers can race several of these via asyncio.wait without one side's
    exception cancelling the wait."""
    try:
        chunk = await gen.__anext__()
        return gen, chunk, None
    except StopAsyncIteration:
        return gen, None, None
    except BaseException as e:  # noqa: BLE001 - reported as data, not swallowed
        return gen, None, e


async def _race_first_chunk(
    task_to_gen: dict[asyncio.Task, AsyncIterator[Any]],
) -> tuple[AsyncIterator[Any], Any, BaseException | None]:
    """Streaming counterpart of _race_first_success: first generator to produce a chunk (or
    reach a clean empty end) wins. Every other generator is cancelled AND explicitly
    aclose()'d so its underlying connection is released, not just abandoned."""
    pending = set(task_to_gen)
    last_result: tuple[AsyncIterator[Any], Any, BaseException | None] | None = None
    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            gen, chunk, err = t.result()
            if err is None:
                for p in pending:
                    await _cancel_and_discard(p)
                    with contextlib.suppress(BaseException):  # noqa: BLE001 - best-effort close of the loser
                        await cast(AsyncGenerator[Any, None], task_to_gen[p]).aclose()
                return gen, chunk, None
            last_result = (gen, chunk, err)
    assert last_result is not None
    return last_result


class RetryingChatModel(RunnableBindingBase):
    """Wraps a LangChain chat-model Runnable so astream/ainvoke transparently retry on
    transient network drops and rate limits -- callers (and .bind()/.bind_tools()
    composition on top) never need to know retry is happening.

    ainvoke: full-response retry is always safe (atomic call, no partial-output risk).
    astream: silent retry only while zero chunks have been yielded yet this attempt --
    once a chunk has reached the caller (who may already have broadcast it further, e.g.
    over a WebSocket) a mid-stream drop raises normally instead of silently restarting,
    since discarding+replaying at this layer would duplicate/corrupt whatever the caller
    already emitted. See docs/superpowers/specs/2026-08-09-llm-call-transparent-retry-design.md.

    hedge_enabled: see module docstring. Only set True for cloud-backed constructions
    (llm/factory.py); local single-instance inference must stay False."""

    hedge_enabled: bool = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self.bound, name)

    async def _ainvoke_attempt(
        self, input: Any, config: RunnableConfig | None, **kwargs: Any,
    ) -> Any:
        transport_attempt = 0
        rate_limit_attempt = 0
        while True:
            try:
                return await super().ainvoke(input, config, **kwargs)
            except RATE_LIMIT_ERRORS:
                if rate_limit_attempt >= RATE_LIMIT_RETRIES:
                    raise
                await asyncio.sleep(
                    RATE_LIMIT_BACKOFF_S[min(rate_limit_attempt, len(RATE_LIMIT_BACKOFF_S) - 1)]
                )
                rate_limit_attempt += 1
            except RETRYABLE_TRANSPORT_ERRORS:
                if transport_attempt >= DEFAULT_RETRIES:
                    raise
                await asyncio.sleep(
                    DEFAULT_BACKOFF_S[min(transport_attempt, len(DEFAULT_BACKOFF_S) - 1)]
                )
                transport_attempt += 1

    async def ainvoke(self, input: Any, config: RunnableConfig | None = None, **kwargs: Any) -> Any:
        if not self.hedge_enabled:
            return await self._ainvoke_attempt(input, config, **kwargs)
        primary = asyncio.ensure_future(self._ainvoke_attempt(input, config, **kwargs))
        done, _ = await asyncio.wait({primary}, timeout=HEDGE_DELAY_S)
        if primary in done:
            return primary.result()
        hedge = asyncio.ensure_future(self._ainvoke_attempt(input, config, **kwargs))
        return await _race_first_success({primary, hedge})

    async def _astream_attempt(
        self, input: Any, config: RunnableConfig | None, **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        transport_attempt = 0
        rate_limit_attempt = 0
        while True:
            yielded_any = False
            # Runtime object is an async generator (has aclose); Runnable.astream's
            # declared return type is only AsyncIterator.
            inner: AsyncGenerator[Any, None] = super().astream(input, config, **kwargs)  # type: ignore[assignment]
            try:
                async for chunk in inner:
                    yielded_any = True
                    yield chunk
                return
            except RATE_LIMIT_ERRORS:
                if yielded_any or rate_limit_attempt >= RATE_LIMIT_RETRIES:
                    raise
                await asyncio.sleep(
                    RATE_LIMIT_BACKOFF_S[min(rate_limit_attempt, len(RATE_LIMIT_BACKOFF_S) - 1)]
                )
                rate_limit_attempt += 1
            except RETRYABLE_TRANSPORT_ERRORS:
                if yielded_any or transport_attempt >= DEFAULT_RETRIES:
                    raise
                await asyncio.sleep(
                    DEFAULT_BACKOFF_S[min(transport_attempt, len(DEFAULT_BACKOFF_S) - 1)]
                )
                transport_attempt += 1
            finally:
                # Unconditional: a no-op once `inner` has already exhausted normally, but the
                # only reliable way to release its connection when this generator itself gets
                # cancelled/aclose()'d while suspended mid-`async for` (Task 3's hedge losers).
                await inner.aclose()

    async def astream(self, input: Any, config: RunnableConfig | None = None, **kwargs: Any):
        if not self.hedge_enabled:
            async for chunk in self._astream_attempt(input, config, **kwargs):
                yield chunk
            return

        primary_gen = self._astream_attempt(input, config, **kwargs)
        primary_task = asyncio.ensure_future(_first_chunk(primary_gen))
        done, _ = await asyncio.wait({primary_task}, timeout=HEDGE_DELAY_S)

        if primary_task in done:
            winner_gen, first_chunk, err = primary_task.result()
        else:
            hedge_gen = self._astream_attempt(input, config, **kwargs)
            hedge_task = asyncio.ensure_future(_first_chunk(hedge_gen))
            winner_gen, first_chunk, err = await _race_first_chunk(
                {primary_task: primary_gen, hedge_task: hedge_gen}
            )

        if err is not None:
            raise err
        if first_chunk is not None:
            yield first_chunk
        async for chunk in winner_gen:
            yield chunk
