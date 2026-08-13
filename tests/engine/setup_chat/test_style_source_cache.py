from engine.setup_chat import style_source_cache
from engine.setup_chat.novel_import import TextChunk


def test_get_unknown_novel_returns_none():
    assert style_source_cache.get_chunks("no-such-novel") is None


def test_store_then_get_returns_same_chunks():
    chunks = [TextChunk(index=0, text="第一段"), TextChunk(index=1, text="第二段")]

    style_source_cache.store_chunks("novel-a", chunks)

    assert style_source_cache.get_chunks("novel-a") == chunks


def test_get_does_not_clear_entry():
    chunks = [TextChunk(index=0, text="内容")]
    style_source_cache.store_chunks("novel-b", chunks)

    first = style_source_cache.get_chunks("novel-b")
    second = style_source_cache.get_chunks("novel-b")

    assert first == chunks
    assert second == chunks


def test_store_overwrites_existing_entry():
    style_source_cache.store_chunks("novel-c", [TextChunk(index=0, text="旧")])
    style_source_cache.store_chunks("novel-c", [TextChunk(index=0, text="新")])

    result = style_source_cache.get_chunks("novel-c")

    assert result == [TextChunk(index=0, text="新")]
