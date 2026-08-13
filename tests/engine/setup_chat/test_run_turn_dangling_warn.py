"""轮末悬空 tool 调用自愈 + 自动续跑：工具没执行时自动重放意图。"""
import pytest
from langchain_core.messages import AIMessage, HumanMessage


class _NoopAccountant:
    async def record(self, tin, tout, tcached):
        pass


def _dangling_ai() -> AIMessage:
    """模拟被截断的工具调用：.tool_calls 为空但 additional_kwargs 残留原始调用。"""
    m = AIMessage(content="好，写进去：", id="a1")
    m.additional_kwargs = {"tool_calls": [
        {"id": "t1", "type": "function",
         "function": {"name": "write_chapter_skeleton", "arguments": '{"chapter": 1, "sta'}},
    ]}
    return m


class _FakeAgent:
    """开轮 aget_state 干净（预检不触发），流结束后返回带悬空调用的状态（轮末检出）。"""

    def __init__(self):
        self.calls = 0
        self.updates: list = []

    async def astream_events(self, inp, version, config):  # noqa: ANN001
        return
        yield  # pragma: no cover

    async def aget_state(self, config):  # noqa: ANN001
        self.calls += 1

        class _State:
            pass

        s = _State()
        if self.calls == 1:
            s.values = {"messages": [HumanMessage(content="旧", id="h0")]}
        elif self.calls == 2:
            s.values = {"messages": [HumanMessage(content="写", id="h1"), _dangling_ai()]}
        else:
            s.values = {"messages": [HumanMessage(content="写", id="h1")]}
        return s

    async def aupdate_state(self, config, update, **kwargs):  # noqa: ANN001, ARG002
        self.updates.append(update)


@pytest.mark.asyncio
async def test_run_turn_dangling_triggers_auto_resume(monkeypatch, tmp_path):
    import utils.paths as paths

    monkeypatch.setattr(paths, "setup_chat_dir", lambda: str(tmp_path))
    restored: list[set] = []
    monkeypatch.setattr(
        "engine.setup_chat.turn_snapshot.restore_if_matches",
        lambda ids: restored.append(set(ids)) or False,
    )

    from engine.setup_chat.agent import _RESUME_NOTICE, _RESUME_OK_NOTICE, run_turn

    agent = _FakeAgent()
    events: list[dict] = []

    async def emit(ev):  # noqa: ANN001
        events.append(ev)

    await run_turn(agent, "n1", "写", emit, _NoopAccountant())

    notices = [e["content"] for e in events if e["type"] == "setup_chat_notice"]
    assert _RESUME_NOTICE in notices
    assert _RESUME_OK_NOTICE in notices
    assert restored and restored[0] == {"t1"}
    assert agent.updates, "RESUME 修复应整表写回"
    assert [e["type"] for e in events][-1] == "setup_chat_done"


@pytest.mark.asyncio
async def test_resume_capped_at_one_attempt(monkeypatch, tmp_path):
    """resume_attempts>=1 -> PAIR + persistent failure notice, no second resume."""
    import utils.paths as paths

    monkeypatch.setattr(paths, "setup_chat_dir", lambda: str(tmp_path))
    monkeypatch.setattr("engine.setup_chat.turn_snapshot.resume_attempts", lambda: 1)
    monkeypatch.setattr("engine.setup_chat.turn_snapshot.restore_if_matches", lambda ids: True)

    from engine.setup_chat.agent import _RESUME_FAIL_NOTICE, _RESUME_NOTICE, run_turn

    agent = _FakeAgent()
    events: list[dict] = []

    async def emit(ev):  # noqa: ANN001
        events.append(ev)

    await run_turn(agent, "n1", "写", emit, _NoopAccountant())
    notices = [e for e in events if e["type"] == "setup_chat_notice"]
    assert any(n["content"] == _RESUME_FAIL_NOTICE and n.get("persist") for n in notices)
    assert all(n["content"] != _RESUME_NOTICE for n in notices)


@pytest.mark.asyncio
async def test_turn_start_precheck_with_dangling_pairs_not_resumes(monkeypatch, tmp_path):
    """D8: competing user input -> PAIR + persistent notice, no resume of old intent."""
    import utils.paths as paths

    monkeypatch.setattr(paths, "setup_chat_dir", lambda: str(tmp_path))
    monkeypatch.setattr("engine.setup_chat.turn_snapshot.restore_if_matches", lambda ids: True)

    from engine.setup_chat.agent import _RESUME_NOTICE, run_turn

    class _DanglingAtStartAgent(_FakeAgent):
        async def aget_state(self, config):  # noqa: ANN001
            self.calls += 1

            class _State:
                pass

            s = _State()
            if self.calls == 1:
                s.values = {"messages": [HumanMessage(content="写", id="h1"), _dangling_ai()]}
            else:
                s.values = {"messages": [HumanMessage(content="写", id="h1")]}
            return s

    agent = _DanglingAtStartAgent()
    events: list[dict] = []

    async def emit(ev):  # noqa: ANN001
        events.append(ev)

    await run_turn(agent, "n1", "继续", emit, _NoopAccountant())
    notices = [e for e in events if e["type"] == "setup_chat_notice"]
    assert any(n.get("persist") for n in notices)
    assert all(n["content"] != _RESUME_NOTICE for n in notices)


@pytest.mark.asyncio
async def test_exception_path_still_heals(monkeypatch, tmp_path):
    """D10: graph exception -> setup_chat_error AND end-of-turn self-heal both happen."""
    import utils.paths as paths

    monkeypatch.setattr(paths, "setup_chat_dir", lambda: str(tmp_path))
    monkeypatch.setattr("engine.setup_chat.turn_snapshot.restore_if_matches", lambda ids: False)

    from engine.setup_chat.agent import run_turn

    class _ExplodingAgent(_FakeAgent):
        async def astream_events(self, inp, version, config):  # noqa: ANN001
            if inp is not None:
                raise RuntimeError("boom")
            return
            yield  # pragma: no cover

    agent = _ExplodingAgent()
    events: list[dict] = []

    async def emit(ev):  # noqa: ANN001
        events.append(ev)

    await run_turn(agent, "n1", "写", emit, _NoopAccountant())
    types = [e["type"] for e in events]
    assert "setup_chat_error" in types
    assert "setup_chat_notice" in types


@pytest.mark.asyncio
async def test_run_turn_no_warning_on_clean_turn(monkeypatch, tmp_path):
    import utils.paths as paths

    monkeypatch.setattr(paths, "setup_chat_dir", lambda: str(tmp_path))

    from engine.setup_chat.agent import run_turn

    class _CleanAgent(_FakeAgent):
        async def aget_state(self, config):  # noqa: ANN001
            class _State:
                pass

            s = _State()
            s.values = {"messages": [
                HumanMessage(content="写", id="h1"),
                AIMessage(content="写好了。", id="a1"),
            ]}
            return s

    events: list[dict] = []

    async def emit(ev):  # noqa: ANN001
        events.append(ev)

    await run_turn(_CleanAgent(), "n1", "写", emit, _NoopAccountant())
    types = [e["type"] for e in events]
    assert "setup_chat_error" not in types
    assert "setup_chat_notice" not in types
    assert "setup_chat_final" in types and types[-1] == "setup_chat_done"
