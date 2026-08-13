"""Cross-layer bridge for a long-running @tool function (e.g. auto_build_setup) to push
progress events to the frontend without threading `emit` through every function signature
in its call chain. Same ContextVar pattern as stream_guard.py -- asyncio Task creation
copies the current context, so this propagates correctly whether LangGraph awaits the tool
coroutine directly or schedules it via gather/create_task."""
from __future__ import annotations

import contextvars
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

EmitFn = Callable[[dict], Awaitable[None]]

_current_emit: contextvars.ContextVar[EmitFn | None] = contextvars.ContextVar(
    "setup_chat_tool_progress_emit", default=None,
)


@asynccontextmanager
async def emit_scope(emit: EmitFn) -> AsyncIterator[None]:
    token = _current_emit.set(emit)
    try:
        yield
    finally:
        _current_emit.reset(token)


async def emit_tool_progress(name: str, label: str) -> None:
    """No-op outside emit_scope (e.g. a unit test calling build_characters() directly with no
    turn context) -- progress reporting is best-effort, never a hard dependency."""
    emit = _current_emit.get()
    if emit is not None:
        await emit({"type": "setup_chat_tool", "name": name, "phase": "progress", "label": label})
