import asyncio

import pytest

from engine.story_sandbox.prose_format import strip_prose_preamble


async def _aiter(pieces):
    for p in pieces:
        yield p


@pytest.mark.asyncio
async def test_strip_prose_preamble_drops_noise_before_marker():
    out = []
    async for piece in strip_prose_preamble(
        _aiter(["听懂了，导演。", "以下接续", "正文——", "【正文】：", "他推开门，", "走了进去。"])
    ):
        out.append(piece)
    assert "".join(out) == "他推开门，走了进去。"


@pytest.mark.asyncio
async def test_strip_prose_preamble_handles_marker_split_across_tokens():
    out = []
    async for piece in strip_prose_preamble(_aiter(["好的。", "【正", "文】", "：", "正文内容"])):
        out.append(piece)
    assert "".join(out) == "正文内容"


@pytest.mark.asyncio
async def test_strip_prose_preamble_accepts_ascii_colon():
    out = []
    async for piece in strip_prose_preamble(_aiter(["【正文】:", "正文内容"])):
        out.append(piece)
    assert "".join(out) == "正文内容"


@pytest.mark.asyncio
async def test_strip_prose_preamble_accepts_marker_without_colon():
    # Some model completions drop the required colon and go straight to a paragraph
    # break (e.g. "【正文】\n\n他推开门..."); the marker itself must still be stripped
    # instead of leaking into the visible prose as its own leading line.
    out = []
    async for piece in strip_prose_preamble(_aiter(["【正文】", "\n\n他推开门，", "走了进去。"])):
        out.append(piece)
    assert "".join(out) == "他推开门，走了进去。"


@pytest.mark.asyncio
async def test_strip_prose_preamble_passthrough_when_marker_starts_stream():
    out = []
    async for piece in strip_prose_preamble(_aiter(["【正文】：", "他", "抬起头。"])):
        out.append(piece)
    assert "".join(out) == "他抬起头。"


@pytest.mark.asyncio
async def test_strip_prose_preamble_fails_open_when_marker_never_appears():
    tokens = ["这段没有标记，", "模型没有遵守格式约定，", "但内容依然要完整保留下来，不能丢字。"]
    out = []
    async for piece in strip_prose_preamble(_aiter(tokens)):
        out.append(piece)
    assert "".join(out) == "".join(tokens)


@pytest.mark.asyncio
async def test_strip_prose_preamble_empty_stream_yields_nothing():
    out = []
    async for piece in strip_prose_preamble(_aiter([])):
        out.append(piece)
    assert out == []


@pytest.mark.asyncio
async def test_strip_prose_preamble_flushes_on_paragraph_break_without_waiting_for_more_tokens():
    """A stalled upstream (e.g. a cancelled turn whose token source never yields again) must not
    leave a whole first paragraph stuck in the buffer just because no marker showed up yet --
    guarded_stream's own cancellation-safe flushing depends on paragraph breaks surfacing
    promptly (see tests/api/test_story_sandbox_api.py::
    test_stop_story_sandbox_turn_rolls_back_word_guard, which this regression-guards)."""
    async def _stalls_after_first_chunk():
        yield "他仿佛笑了。\n\n"
        await asyncio.Event().wait()  # never set -- simulates a cancelled/hung stream

    gen = strip_prose_preamble(_stalls_after_first_chunk())
    first = await asyncio.wait_for(gen.__anext__(), timeout=1)
    assert first == "他仿佛笑了。\n\n"
