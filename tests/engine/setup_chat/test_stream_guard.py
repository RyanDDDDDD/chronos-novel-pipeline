import pytest
from engine.setup_chat.stream_guard import (
    asuppress_setup_chat_stream,
    is_setup_chat_stream_suppressed,
    should_forward_setup_chat_stream,
    suppress_setup_chat_stream,
)


def test_should_forward_only_when_not_tool_and_not_suppressed():
    assert should_forward_setup_chat_stream(tool_depth=0) is True
    assert should_forward_setup_chat_stream(tool_depth=1) is False


def test_suppress_blocks_forward():
    with suppress_setup_chat_stream():
        assert is_setup_chat_stream_suppressed() is True
        assert should_forward_setup_chat_stream(tool_depth=0) is False
    assert is_setup_chat_stream_suppressed() is False


@pytest.mark.asyncio
async def test_async_suppress_blocks_forward():
    async with asuppress_setup_chat_stream():
        assert should_forward_setup_chat_stream(tool_depth=0) is False
