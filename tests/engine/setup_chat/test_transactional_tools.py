"""Tests for TransactionalToolNode (spec D2/D3/D4/D13)."""
import pytest
from engine.setup_chat import author_guard as ag
from engine.setup_chat.transactional_tools import (
    TransactionalToolNode,
    is_write_tool,
)
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode


@tool
def read_setup_summary(target: str) -> str:
    """Fake read tool."""
    return "summary"


@tool
def patch_chapter(chapter: int) -> str:
    """Fake write tool (succeeds)."""
    return "patched"


@tool
def write_plot(chapters: list) -> str:
    """Fake write tool (always fails)."""
    raise RuntimeError("disk exploded")


def _ai(name: str, args: dict, call_id: str = "c1") -> dict:
    return {"messages": [AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": args}])]}


class TestClassification:
    def test_read_prefixes_and_whitelist_are_readonly(self):
        for n in ("read_setup_summary", "read_chapter_skeleton", "query_character_voice",
                  "recall_research", "web_search", "load_skill", "present_choices"):
            assert not is_write_tool(n)

    def test_everything_else_is_write_default_strict(self):
        for n in ("patch_chapter", "construct_world", "some_new_skill_tool"):
            assert is_write_tool(n)


class TestNode:
    @pytest.fixture()
    def snap_calls(self, monkeypatch):
        calls: dict = {"snapshot": [], "restore": []}
        monkeypatch.setattr(
            "engine.setup_chat.transactional_tools.take_snapshot",
            lambda ids, names: calls["snapshot"].append((ids, names)) or True,
        )
        monkeypatch.setattr(
            "engine.setup_chat.transactional_tools.restore_if_matches",
            lambda ids: calls["restore"].append(ids) or True,
        )
        return calls

    @pytest.fixture(autouse=True)
    def mock_tool_node_invoke(self, monkeypatch):
        """LangGraph ToolNode.ainvoke needs graph runtime; mock parent execution."""

        async def _parent_ainvoke(self, input, config=None, **kwargs):  # noqa: ANN001
            msgs = input.get("messages") if isinstance(input, dict) else input
            last = msgs[-1]
            out: list[ToolMessage] = []
            for tc in getattr(last, "tool_calls", None) or []:
                name = str(tc.get("name", ""))
                if name == "write_plot":
                    out.append(ToolMessage(
                        content="err: disk exploded",
                        tool_call_id=str(tc.get("id", "")),
                        status="error",
                    ))
                else:
                    out.append(ToolMessage(content="ok", tool_call_id=str(tc.get("id", ""))))
            return {"messages": out}

        monkeypatch.setattr(ToolNode, "ainvoke", _parent_ainvoke)

    @pytest.mark.asyncio
    async def test_write_tool_snapshots_before_and_no_restore_on_success(self, snap_calls):
        node = TransactionalToolNode([patch_chapter])
        await node.ainvoke(_ai("patch_chapter", {"chapter": 3}))
        assert snap_calls["snapshot"] == [(["c1"], ["patch_chapter"])]
        assert snap_calls["restore"] == []

    @pytest.mark.asyncio
    async def test_read_tool_never_snapshots(self, snap_calls):
        node = TransactionalToolNode([read_setup_summary])
        await node.ainvoke(_ai("read_setup_summary", {"target": "world"}))
        assert snap_calls["snapshot"] == []

    @pytest.mark.asyncio
    async def test_failed_write_tool_restores(self, snap_calls, monkeypatch):
        import engine.setup_chat.plan_runner as pr_mod
        monkeypatch.setattr(pr_mod, "gate_tool_call", lambda name, args: None)
        node = TransactionalToolNode([write_plot], handle_tool_errors=lambda e: f"err: {e}")
        result = await node.ainvoke(_ai("write_plot", {"chapters": []}))
        assert snap_calls["restore"] == [{"c1"}]
        tm = result["messages"][0]
        assert tm.status == "error"

    @pytest.mark.asyncio
    async def test_guard_called_before_snapshot_for_plot_tool(self, snap_calls):
        order: list[str] = []

        async def fake_guard(lo: int, hi: int, reason: str) -> None:
            order.append(f"guard:{lo}-{hi}")

        ag.set_author_guard(fake_guard)
        try:
            node = TransactionalToolNode([patch_chapter])
            snap_calls["snapshot"].clear()
            import engine.setup_chat.transactional_tools as tt
            orig = tt.take_snapshot
            tt.take_snapshot = lambda ids, names: order.append("snapshot") or True  # type: ignore[assignment]
            try:
                await node.ainvoke(_ai("patch_chapter", {"chapter": 3}))
            finally:
                tt.take_snapshot = orig  # type: ignore[assignment]
        finally:
            ag.set_author_guard(None)
        assert order == ["guard:3-3", "snapshot"]

    @pytest.mark.asyncio
    async def test_world_tool_does_not_trigger_guard(self, snap_calls):
        hits: list = []

        async def fake_guard(lo: int, hi: int, reason: str) -> None:
            hits.append((lo, hi))

        ag.set_author_guard(fake_guard)
        try:
            @tool
            def construct_world(features: list) -> str:
                """Fake."""
                return "ok"
            node = TransactionalToolNode([construct_world])
            await node.ainvoke(_ai("construct_world", {"features": []}))
        finally:
            ag.set_author_guard(None)
        assert hits == []


@pytest.mark.asyncio
async def test_gated_call_is_rejected_without_executing(monkeypatch):
    """gate returns rejection → tool body not executed, error ToolMessage returned."""
    executed = []

    @tool
    def construct_world(payload: str) -> str:
        """fake construct."""
        executed.append(payload)
        return "built"

    import engine.setup_chat.plan_runner as pr_mod
    monkeypatch.setattr(pr_mod, "gate_tool_call",
                        lambda name, args: "当前任务是『schema』" if name == "construct_world" else None)

    node = TransactionalToolNode([construct_world])
    ai = AIMessage(content="", tool_calls=[
        {"name": "construct_world", "args": {"payload": "x"}, "id": "call1", "type": "tool_call"},
    ])
    result = await node.ainvoke({"messages": [ai]})
    msgs = result["messages"] if isinstance(result, dict) else result
    tm = next(m for m in msgs if getattr(m, "tool_call_id", "") == "call1")
    assert getattr(tm, "status", None) == "error"
    assert "当前任务" in str(tm.content)
    assert executed == []


@pytest.mark.asyncio
async def test_gated_call_is_logged_to_tool_trace(monkeypatch):
    """Gate rejections never reach ToolNode.ainvoke (no on_tool_start/end fires
    for them), so this is the only place that can log the attempt -- without it
    the turn's trace would silently skip every call the gate blocked."""
    from loguru import logger

    @tool
    def write_chapter_skeleton(chapter: int) -> str:
        """fake."""
        return "written"

    import engine.setup_chat.plan_runner as pr_mod
    monkeypatch.setattr(
        pr_mod, "gate_tool_call",
        lambda name, args: "前置未完成" if name == "write_chapter_skeleton" else None,
    )

    captured: list[str] = []
    sink_id = logger.add(lambda m: captured.append(str(m)), level="INFO")
    try:
        node = TransactionalToolNode([write_chapter_skeleton])
        ai = AIMessage(content="", tool_calls=[
            {"name": "write_chapter_skeleton", "args": {"chapter": 3}, "id": "call1", "type": "tool_call"},
        ])
        await node.ainvoke({"messages": [ai]})
    finally:
        logger.remove(sink_id)

    joined = "\n".join(captured)
    assert "write_chapter_skeleton" in joined
    assert "被拒" in joined
    assert "前置未完成" in joined


@pytest.mark.asyncio
async def test_gated_call_rejected_in_send_api_context_shape(monkeypatch):
    """Production LangGraph dispatches each tool call individually via the Send
    API as {"__type": "tool_call_with_context", "tool_call": {...}, "state": {...}}
    -- not the legacy {"messages": [AIMessage(tool_calls=[...])]} batch shape all
    the other tests here use. Discovered live: gate_tool_call was silently never
    being invoked in production because _last_ai_tool_calls only recognized the
    legacy shape."""
    executed = []

    @tool
    def add_character(given_name: str) -> str:
        """fake add_character."""
        executed.append(given_name)
        return "added"

    import engine.setup_chat.plan_runner as pr_mod
    monkeypatch.setattr(pr_mod, "gate_tool_call",
                        lambda name, args: "「character」现在还不能做" if name == "add_character" else None)

    node = TransactionalToolNode([add_character])
    send_input = {
        "__type": "tool_call_with_context",
        "tool_call": {"name": "add_character", "args": {"given_name": "张三"}, "id": "call1"},
        "state": {"messages": []},
    }
    result = await node.ainvoke(send_input)
    msgs = result["messages"] if isinstance(result, dict) else result
    tm = next(m for m in msgs if getattr(m, "tool_call_id", "") == "call1")
    assert getattr(tm, "status", None) == "error"
    assert "「character」现在还不能做" in str(tm.content)
    assert executed == []


@pytest.mark.asyncio
async def test_ungated_call_still_executes_in_send_api_context_shape(monkeypatch):
    async def _parent_ainvoke(self, input, config=None, **kwargs):  # noqa: ANN001
        tc = input["tool_call"]
        return {"messages": [ToolMessage(content="added", tool_call_id=str(tc.get("id", "")))]}

    monkeypatch.setattr(ToolNode, "ainvoke", _parent_ainvoke)

    @tool
    def add_character(given_name: str) -> str:
        """fake add_character."""
        return "added"

    import engine.setup_chat.plan_runner as pr_mod
    monkeypatch.setattr(pr_mod, "gate_tool_call", lambda name, args: None)
    node = TransactionalToolNode([add_character])
    send_input = {
        "__type": "tool_call_with_context",
        "tool_call": {"name": "add_character", "args": {"given_name": "张三"}, "id": "call1"},
        "state": {"messages": []},
    }
    result = await node.ainvoke(send_input)
    msgs = result["messages"] if isinstance(result, dict) else result
    tm = next(m for m in msgs if getattr(m, "tool_call_id", "") == "call1")
    assert "added" in str(tm.content)


@pytest.mark.asyncio
async def test_ungated_call_still_executes(monkeypatch):
    from langgraph.prebuilt import ToolNode as TGToolNode

    async def _parent_ainvoke(self, input, config=None, **kwargs):  # noqa: ANN001
        msgs = input.get("messages") if isinstance(input, dict) else input
        last = msgs[-1]
        out: list[ToolMessage] = []
        for tc in getattr(last, "tool_calls", None) or []:
            out.append(ToolMessage(content="built", tool_call_id=str(tc.get("id", ""))))
        return {"messages": out}

    monkeypatch.setattr(TGToolNode, "ainvoke", _parent_ainvoke)

    @tool
    def construct_world(payload: str) -> str:
        """fake construct."""
        return "built"

    import engine.setup_chat.plan_runner as pr_mod
    monkeypatch.setattr(pr_mod, "gate_tool_call", lambda name, args: None)
    node = TransactionalToolNode([construct_world])
    ai = AIMessage(content="", tool_calls=[
        {"name": "construct_world", "args": {"payload": "x"}, "id": "call1", "type": "tool_call"},
    ])
    result = await node.ainvoke({"messages": [ai]})
    msgs = result["messages"] if isinstance(result, dict) else result
    tm = next(m for m in msgs if getattr(m, "tool_call_id", "") == "call1")
    assert "built" in str(tm.content)
