"""Set conversation streaming gating: Inner LLM (memory distillation, etc.) must not be pushed to the frontend."""
from __future__ import annotations

import contextvars
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import TypeVar

T = TypeVar("T")

_suppress_front_stream: contextvars.ContextVar[int] = contextvars.ContextVar(
    "setup_chat_suppress_front_stream",
    default=0,
)


def is_setup_chat_stream_suppressed() -> bool:
    return _suppress_front_stream.get() > 0


def should_forward_setup_chat_stream(*, tool_depth: int) -> bool:
    """Streaming token visible to the main agent: non-in-tool and non-internal LLM (distillation, etc.)."""
    return tool_depth == 0 and not is_setup_chat_stream_suppressed()


@contextmanager
def suppress_setup_chat_stream() -> Iterator[None]:
    token = _suppress_front_stream.set(_suppress_front_stream.get() + 1)
    try:
        yield
    finally:
        _suppress_front_stream.reset(token)


@asynccontextmanager
async def asuppress_setup_chat_stream() -> AsyncIterator[None]:
    token = _suppress_front_stream.set(_suppress_front_stream.get() + 1)
    try:
        yield
    finally:
        _suppress_front_stream.reset(token)
