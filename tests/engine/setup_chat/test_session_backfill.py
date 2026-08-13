import pytest
from engine.setup_chat import checkpoint_reader as cr
from engine.setup_chat.session_record import load_messages


class _M:
    """Fake raw message (duck type, imitating langchain BaseMessage)."""
    def __init__(self, type_, content, tool_calls=None, id=None):
        self.type = type_
        self.content = content
        self.tool_calls = tool_calls or []
        self.id = id


@pytest.mark.asyncio
async def test_backfill_when_missing_projects_checkpoint(tmp_path, monkeypatch):
    session_dir = str(tmp_path / "session")
    persist_dir = str(tmp_path / "setup_chat")

    async def fake_reader(cp, tid):
        return [_M("human", "想写校园故事"), _M("ai", "好的，主角设定？")]

    out = await cr.backfill_if_missing(
        session_dir, "ignored.sqlite", "novel-x",
        persist_dir=persist_dir, reader=fake_reader,
    )
    assert [m["role"] for m in out] == ["user", "assistant"]
    assert [m["content"] for m in out] == ["想写校园故事", "好的，主角设定？"]
    assert load_messages(session_dir) == out  #Already placed


@pytest.mark.asyncio
async def test_backfill_carries_thinking(tmp_path):
    """
The backfill must retain the folded thinking block: tool_calls narrative + final answer → answer with thinking."""
    session_dir = str(tmp_path / "session")
    persist_dir = str(tmp_path / "setup_chat")

    async def fake_reader(cp, tid):
        return [
            _M("human", "写校园故事"),
            _M("ai", "我先查查资料", tool_calls=[{"name": "recall_research", "args": {}, "id": "t1"}]),
            _M("tool", "查到了"),
            _M("ai", "好的，主角设定？"),
        ]

    out = await cr.backfill_if_missing(
        session_dir, "x.sqlite", "n", persist_dir=persist_dir, reader=fake_reader,
    )
    asst = [m for m in out if m["role"] == "assistant"]
    assert len(asst) == 1
    assert asst[0]["content"] == "好的，主角设定？"
    assert asst[0]["thinking"] == "我先查查资料"


@pytest.mark.asyncio
async def test_backfill_noop_when_table_exists(tmp_path):
    from engine.setup_chat.session_record import append_user
    session_dir = str(tmp_path / "session")
    append_user(session_dir, "已有")

    async def boom(cp, tid):
        raise AssertionError("表已存在不该读 checkpoint")

    out = await cr.backfill_if_missing(
        session_dir, "x.sqlite", "n", persist_dir=str(tmp_path), reader=boom,
    )
    assert [m["content"] for m in out] == ["已有"]


@pytest.mark.asyncio
async def test_backfill_empty_checkpoint_caches_empty_result(tmp_path):
    """Regression test: an empty checkpoint used to never get written to messages.json, so
    every subsequent call re-hit the (slow) reader instead of the fast file-exists path."""
    session_dir = str(tmp_path / "session")
    calls = 0

    async def empty_reader(cp, tid):
        nonlocal calls
        calls += 1
        return []

    out = await cr.backfill_if_missing(
        session_dir, "x.sqlite", "n", persist_dir=str(tmp_path), reader=empty_reader,
    )
    assert out == []
    assert load_messages(session_dir) == []
    assert calls == 1

    out2 = await cr.backfill_if_missing(
        session_dir, "x.sqlite", "n", persist_dir=str(tmp_path), reader=empty_reader,
    )
    assert out2 == []
    assert calls == 1  #Second call must take the fast messages.json path, not re-read the checkpoint
