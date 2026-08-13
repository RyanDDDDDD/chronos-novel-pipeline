"""Integration: None-input resume re-plans from a repaired checkpoint (spec D6)."""
import aiosqlite
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

CALLS: list[dict] = []


@tool
def patch_chapter(chapter: int) -> str:
    """Fake write tool recording invocations."""
    CALLS.append({"chapter": chapter})
    return "patched"


class _ResumeFake(BaseChatModel):
    """Returns tool call on first invoke, final answer on second."""

    model_calls: int = 0

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN003
        self.model_calls += 1
        if self.model_calls == 1:
            msg = AIMessage(content="", tool_calls=[
                {"id": "c2", "name": "patch_chapter", "args": {"chapter": 3}},
            ])
        else:
            msg = AIMessage(content="补跑完成")
        return ChatResult(generations=[ChatGeneration(message=msg)])

    @property
    def _llm_type(self) -> str:
        return "resume-fake"


@pytest.mark.asyncio
async def test_none_input_resume_reissues_tool(tmp_path, monkeypatch):
    monkeypatch.setattr("utils.paths.active_novel_dir", lambda: str(tmp_path / "novel"))
    CALLS.clear()
    from engine.setup_chat.agent import _drive_stream
    from engine.setup_chat.memory import RepairMode, ensure_checkpoint_messages_valid
    from engine.setup_chat.transactional_tools import TransactionalToolNode
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.prebuilt import create_react_agent

    model = _ResumeFake()
    conn = await aiosqlite.connect(str(tmp_path / "cp.sqlite"))
    saver = AsyncSqliteSaver(conn)
    await saver.setup()
    agent = create_react_agent(model, tools=TransactionalToolNode([patch_chapter]), checkpointer=saver)
    config = {"configurable": {"thread_id": "t1"}}

    await agent.aupdate_state(
        config,
        {"messages": [
            HumanMessage(content="改第3章", id="h1"),
            AIMessage(content="", id="a1",
                      tool_calls=[{"id": "c1", "name": "patch_chapter", "args": {"chapter": 3}}]),
        ]},
        as_node="agent",
    )
    report = await ensure_checkpoint_messages_valid(agent, config, str(tmp_path), mode=RepairMode.RESUME)
    assert report.changed and report.dangling_ids == {"c1"}

    events: list[dict] = []

    async def emit(ev):  # noqa: ANN001
        events.append(ev)

    class _NoopAccountant:
        async def record(self, tin, tout, tcached):
            pass

    await _drive_stream(agent, None, config, emit, str(tmp_path), _NoopAccountant())
    assert CALLS == [{"chapter": 3}]
    state = await agent.aget_state(config)
    final = state.values["messages"][-1]
    assert final.content == "补跑完成"
    await conn.close()
