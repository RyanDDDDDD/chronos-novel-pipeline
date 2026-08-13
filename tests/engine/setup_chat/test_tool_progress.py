import pytest
from engine.setup_chat.tool_progress import emit_scope, emit_tool_progress


@pytest.mark.asyncio
async def test_emit_tool_progress_forwards_inside_scope():
    received: list[dict] = []

    async def fake_emit(ev: dict) -> None:
        received.append(ev)

    async with emit_scope(fake_emit):
        await emit_tool_progress("auto_build_setup", "世界观已构建")

    assert received == [
        {"type": "setup_chat_tool", "name": "auto_build_setup", "phase": "progress",
         "label": "世界观已构建"},
    ]


@pytest.mark.asyncio
async def test_emit_tool_progress_is_noop_outside_scope():
    # No emit_scope active -- must not raise, must not do anything observable.
    await emit_tool_progress("auto_build_setup", "不该有任何效果")


@pytest.mark.asyncio
async def test_emit_tool_progress_noop_after_scope_exits():
    received: list[dict] = []

    async def fake_emit(ev: dict) -> None:
        received.append(ev)

    async with emit_scope(fake_emit):
        await emit_tool_progress("x", "in-scope")

    await emit_tool_progress("x", "after-scope-should-not-forward")
    assert received == [
        {"type": "setup_chat_tool", "name": "x", "phase": "progress", "label": "in-scope"},
    ]


@pytest.mark.asyncio
async def test_nested_emit_scopes_do_not_leak_into_each_other():
    """Simulates _drive_stream being called twice in sequence (run_turn then
    _heal_and_maybe_resume's retry) with different emit callables -- each scope's emit_tool_
    progress calls must only ever reach that scope's own emit, never a previous one still
    referenced by a stale closure."""
    first: list[dict] = []
    second: list[dict] = []

    async def emit_a(ev: dict) -> None:
        first.append(ev)

    async def emit_b(ev: dict) -> None:
        second.append(ev)

    async with emit_scope(emit_a):
        await emit_tool_progress("x", "a1")

    async with emit_scope(emit_b):
        await emit_tool_progress("x", "b1")

    assert [e["label"] for e in first] == ["a1"]
    assert [e["label"] for e in second] == ["b1"]
