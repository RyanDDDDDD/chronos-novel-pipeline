import os

import pytest
from engine.setup_chat.session_record import load_messages


class _FakeAgentState:
    values: dict = {"messages": []}


class _FakeAgent:
    """Minimal stand-in for a built setup-chat agent -- start_setup_chat_turn now calls
    agent.aget_state(config) unconditionally (turn-cancel pre-state capture), so a bare string
    (the old "AGENT" placeholder) no longer suffices here."""

    async def aget_state(self, config):
        return _FakeAgentState()


@pytest.mark.asyncio
async def test_turn_records_user_and_assistant(tmp_path, monkeypatch):
    """Enter user; run_turn emit setup_chat_final and assistant."""
    from api.services import message_hub as mh

    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "n")
    session_dir = str(tmp_path / "n" / "session")
    os.makedirs(session_dir, exist_ok=True)

    hub = mh.MessageHub()
    monkeypatch.setattr(hub, "_ensure_setup_chat_agent", _async_return(_FakeAgent()))
    monkeypatch.setattr(mh, "setup_chat_session_dir", lambda novel_id=None: session_dir, raising=False)

    async def fake_run_turn(agent, novel_id, text, emit, accountant):
        await emit({"type": "setup_chat_token", "delta": "您"})  #Not included in the list
        await emit({"type": "setup_chat_final", "content": "您好，方向？"})
        await emit({"type": "setup_chat_done"})

    monkeypatch.setattr(mh, "run_turn", fake_run_turn, raising=False)

    await hub.start_setup_chat_turn("写校园故事")
    if (_t := hub._setup_chat_tasks.get(mh.active_novel_id())) is not None:
        await _t  #Wait for this round of tasks to finish

    msgs = load_messages(session_dir)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert [m["content"] for m in msgs] == ["写校园故事", "您好，方向？"]


@pytest.mark.asyncio
async def test_history_reads_table_without_agent(tmp_path, monkeypatch):
    from api.services import message_hub as mh
    from engine.setup_chat.session_record import append_user

    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "n")
    session_dir = str(tmp_path / "n" / "session")
    os.makedirs(session_dir, exist_ok=True)
    append_user(session_dir, "历史消息")
    monkeypatch.setattr(mh, "setup_chat_session_dir", lambda novel_id=None: session_dir, raising=False)

    hub = mh.MessageHub()

    def boom():
        raise AssertionError("恢复不该建 agent")

    monkeypatch.setattr(hub, "_ensure_setup_chat_agent", boom)

    out = await hub.setup_chat_history()
    assert [m["content"] for m in out] == ["历史消息"]


def _async_return(val):
    async def _f(*a, **k):
        return val
    return _f
