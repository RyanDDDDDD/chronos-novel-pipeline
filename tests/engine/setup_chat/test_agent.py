import pytest
from engine.setup_chat.agent import build_agent


class _NoopAccountant:
    async def record(self, tin, tout, tcached):
        pass


def test_timeline_tools_registered():
    from engine.setup_chat import tools as t
    for fn in ("read_archive_seed", "read_archive_status", "write_character_archive",
               "read_character_archive"):
        assert hasattr(t, fn), f"{fn} 未定义"


def test_skeleton_tools_registered():
    from engine.setup_chat import tools as t
    for fn in ("read_skeleton_seed", "write_chapter_skeleton"):
        assert hasattr(t, fn), f"{fn} 未定义"


def test_author_manuscript_tool_registered():
    from engine.setup_chat import tools as t
    assert hasattr(t, "read_author_manuscript"), "read_author_manuscript 未定义"


def test_patch_text_fragment_tool_registered():
    from engine.setup_chat import tools as t
    assert hasattr(t, "patch_text_fragment"), "patch_text_fragment 未定义"


def test_agent_registers_split_research_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "engine.setup_chat.agent.setup_chat_checkpoint_path",
        lambda: str(tmp_path / "cp.sqlite"),
    )
    import inspect

    import engine.setup_chat.agent as a
    src = inspect.getsource(a.build_agent)
    #Split into two tools: local recall + networked web (no more single search_research)
    assert "recall_research" in src and "web_search" in src
    assert "search_research" not in src


def test_compose_system_prompt_has_index_not_body():
    from engine.setup_chat.agent import compose_system_prompt
    prompt = compose_system_prompt()
    #Index: skill name + description present
    assert "world-interview" in prompt
    assert "按固定 8 维顺序逐维访谈" in prompt  #from description
    #Progressive disclosure: text details are not entered into the system prompt
    assert "不深挖支线" not in prompt


def test_compose_system_prompt_uses_default_identity_without_pack_override(monkeypatch):
    from engine.setup_chat.agent import _IDENTITY, compose_system_prompt
    monkeypatch.setattr("context.content_packs.active_identity", lambda: None)
    monkeypatch.setattr("engine.modes.author_loop_skill_prefs.load_dialogue_prefs", lambda: {})
    assert compose_system_prompt().startswith(_IDENTITY)


def test_compose_system_prompt_uses_content_pack_identity_override(monkeypatch):
    monkeypatch.setattr("context.content_packs.active_identity", lambda: "SENTINEL身份覆写")
    monkeypatch.setattr("engine.modes.author_loop_skill_prefs.load_dialogue_prefs", lambda: {})
    from engine.setup_chat.agent import compose_system_prompt
    assert compose_system_prompt().startswith("SENTINEL身份覆写")


def test_resolved_default_identity_falls_back_to_neutral_default(monkeypatch):
    from engine.setup_chat.agent import _IDENTITY, resolved_default_identity
    monkeypatch.setattr("context.content_packs.active_identity", lambda: None)
    assert resolved_default_identity() == _IDENTITY


def test_resolved_default_identity_prefers_content_pack_override(monkeypatch):
    from engine.setup_chat.agent import resolved_default_identity
    monkeypatch.setattr("context.content_packs.active_identity", lambda: "PACK身份")
    assert resolved_default_identity() == "PACK身份"


def test_compose_system_prompt_prefers_pipeline_custom_identity_over_pack(monkeypatch):
    monkeypatch.setattr("context.content_packs.active_identity", lambda: "PACK身份")
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"chat_identity": "PIPELINE自定义身份"},
    )
    from engine.setup_chat.agent import compose_system_prompt
    assert compose_system_prompt().startswith("PIPELINE自定义身份")


def test_compose_system_prompt_falls_back_to_pack_when_chat_identity_blank(monkeypatch):
    monkeypatch.setattr("context.content_packs.active_identity", lambda: "PACK身份")
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"chat_identity": "   "},
    )
    from engine.setup_chat.agent import compose_system_prompt
    assert compose_system_prompt().startswith("PACK身份")


def test_compose_system_prompt_states_stage_count_floor(monkeypatch):
    monkeypatch.setattr("context.content_packs.active_identity", lambda: None)
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"target_words": 3000},
    )
    from engine.setup_chat.agent import compose_system_prompt
    prompt = compose_system_prompt()
    assert "3000 字/章" in prompt
    assert "stage 数不得少于 2" in prompt
    assert "拒绝写入" in prompt


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeBoundModel:
    def __init__(self, base: object, tools: list) -> None:
        self.base = base
        self.tools = tools
        self.bind_kwargs: dict | None = None

    def bind(self, **kwargs: object) -> "_FakeBoundModel":
        self.bind_kwargs = kwargs
        return self


class _FakeLlm:
    label = "original"

    def bind_tools(self, tools: list) -> _FakeBoundModel:
        return _FakeBoundModel(self, tools)


def test_bind_chat_model_filters_tools_by_routed_names(monkeypatch):
    from engine.setup_chat.agent import _bind_chat_model
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {}},
    )
    tools = [_FakeTool("a"), _FakeTool("b"), _FakeTool("c")]
    result = _bind_chat_model(_FakeLlm(), tools, {"b"})
    assert [t.name for t in result.tools] == ["b"]


def test_bind_chat_model_uses_all_tools_when_no_routed_names(monkeypatch):
    from engine.setup_chat.agent import _bind_chat_model
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {}},
    )
    tools = [_FakeTool("a"), _FakeTool("b")]
    result = _bind_chat_model(_FakeLlm(), tools, set())
    assert result.tools == tools


def test_bind_chat_model_applies_chat_identity_sampling_params(monkeypatch):
    from engine.setup_chat.agent import _bind_chat_model
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {"chat_identity": {"temperature": 0.3}}},
    )
    result = _bind_chat_model(_FakeLlm(), [], set())
    assert result.bind_kwargs == {"temperature": 0.3}


def test_bind_chat_model_no_bind_call_when_nothing_configured(monkeypatch):
    from engine.setup_chat.agent import _bind_chat_model
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {}},
    )
    result = _bind_chat_model(_FakeLlm(), [], set())
    assert result.bind_kwargs is None


def test_bind_chat_model_swaps_base_llm_for_model_ref(monkeypatch):
    from engine.setup_chat import agent as a

    class _SwappedLlm(_FakeLlm):
        label = "swapped"

    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {"chat_identity": {"model_ref": "custom-1"}}},
    )
    monkeypatch.setattr("domain.model_catalog.resolve_model_entry", lambda ref: object())
    monkeypatch.setattr("llm.factory.get_registry_llm", lambda entry: _SwappedLlm())

    result = a._bind_chat_model(_FakeLlm(), [], set())
    assert result.base.label == "swapped"


def test_compose_system_prompt_includes_novel_title(monkeypatch):
    monkeypatch.setattr("api.services.novels.get_novel_name", lambda nid: "星海彼岸的旅人")
    from engine.setup_chat.agent import compose_system_prompt
    prompt = compose_system_prompt()
    assert "星海彼岸的旅人" in prompt
    assert "rename_novel_title" in prompt


def test_compose_system_prompt_injects_prose_style(monkeypatch):
    """The current novel style card is injected into the system prompt, with the guardrail of "keeping the structure fields simple"."""
    import engine.execution.prose_style as ps
    monkeypatch.setattr(ps, "build_active_prose_style_card", lambda: "【SENTINEL文风卡内容】")
    from engine.setup_chat.agent import compose_system_prompt
    prompt = compose_system_prompt()
    assert "【SENTINEL文风卡内容】" in prompt   #Style card injection
    assert "结构化字段" in prompt              #Guardrails: Keep structure fields simple


@pytest.mark.asyncio
async def test_build_agent_registers_three_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "engine.setup_chat.agent.setup_chat_checkpoint_path",
        lambda: str(tmp_path / "cp.sqlite"),
    )
    agent = await build_agent()
    assert agent is not None  # compiled graph
    await agent.checkpointer.conn.close()  #Turn off the aiosqlite connection to avoid testing. Worker thread alarms after the loop is closed.


@pytest.mark.asyncio
async def test_build_agent_includes_rename_novel_title_tool(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "engine.setup_chat.agent.setup_chat_checkpoint_path",
        lambda: str(tmp_path / "cp.sqlite"),
    )
    agent = await build_agent()
    from engine.setup_chat.agent import all_registered_tools

    tool_names = {t.name for t in all_registered_tools()}
    assert "rename_novel_title" in tool_names
    assert "set_source_franchise" in tool_names
    assert "set_portrait_prompt" in tool_names
    await agent.checkpointer.conn.close()


@pytest.mark.asyncio
async def test_build_agent_includes_auto_build_setup_tool(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "engine.setup_chat.agent.setup_chat_checkpoint_path",
        lambda: str(tmp_path / "cp.sqlite"),
    )
    agent = await build_agent()
    from engine.setup_chat.agent import all_registered_tools

    tool_names = {t.name for t in all_registered_tools()}
    assert "auto_build_setup" in tool_names
    await agent.checkpointer.conn.close()


@pytest.mark.asyncio
async def test_build_agent_includes_auto_expand_skeleton_tool(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "engine.setup_chat.agent.setup_chat_checkpoint_path",
        lambda: str(tmp_path / "cp.sqlite"),
    )
    agent = await build_agent()
    from engine.setup_chat.agent import all_registered_tools

    tool_names = {t.name for t in all_registered_tools()}
    assert "auto_expand_skeleton" in tool_names
    await agent.checkpointer.conn.close()


@pytest.mark.asyncio
async def test_build_agent_refreshes_character_args_schema_per_call(monkeypatch, tmp_path):
    """本次修复的核心回归：add_character/edit_character 的 args_schema 此前在进程 import
    时冻结一次，之后 build_agent() 重建多少次都不会变——这条测试要求两次 build_agent()
    之间内容包状态变了，schema 就必须跟着变。"""
    monkeypatch.setattr(
        "engine.setup_chat.agent.setup_chat_checkpoint_path",
        lambda: str(tmp_path / "cp1.sqlite"),
    )
    import context.content_packs as cp
    from engine.setup_chat.tools import add_character

    monkeypatch.setattr(cp, "get_gender_values", lambda: ["male", "female"])
    agent1 = await build_agent()
    desc1 = add_character.args_schema.model_fields["gender"].description
    await agent1.checkpointer.conn.close()

    monkeypatch.setattr(cp, "get_gender_values", lambda: ["male", "female", "xeno"])
    monkeypatch.setattr(
        "engine.setup_chat.agent.setup_chat_checkpoint_path",
        lambda: str(tmp_path / "cp2.sqlite"),
    )
    agent2 = await build_agent()
    desc2 = add_character.args_schema.model_fields["gender"].description
    await agent2.checkpointer.conn.close()

    assert desc1 != desc2
    assert "xeno" not in (desc1 or "")
    assert "xeno" in (desc2 or "")


class _FakeAgent:
    async def astream_events(self, _input, **_kw):
        yield {"event": "on_chat_model_stream",
               "data": {"chunk": type("C", (), {"content": "你好"})()}}
        yield {"event": "on_tool_start", "name": "read_setup_summary", "data": {}}
        yield {"event": "on_tool_end", "name": "read_setup_summary", "data": {}}
        yield {"event": "on_chat_model_stream",
               "data": {"chunk": type("C", (), {"content": "改好了"})()}}

    async def aget_state(self, _cfg):
        ai = type("M", (), {"type": "ai", "content": "改好了", "tool_calls": None})()
        return type("S", (), {"values": {"messages": [ai]}})()


class _FakeAgentWithInternalStream:
    """
Inner LLM streaming output during tool execution should not be pushed to the front end."""

    async def astream_events(self, _input, **_kw):
        yield {"event": "on_chat_model_stream",
               "data": {"chunk": type("C", (), {"content": "先回复"})()}}
        yield {"event": "on_tool_start", "name": "refine_world", "data": {}}
        yield {"event": "on_chat_model_stream",
               "data": {"chunk": type("C", (), {"content": '{"logline":'})()}}
        yield {"event": "on_tool_end", "name": "refine_world", "data": {}}
        yield {"event": "on_chat_model_stream",
               "data": {"chunk": type("C", (), {"content": "改好了"})()}}

    async def aget_state(self, _cfg):
        ai = type("M", (), {"type": "ai", "content": "改好了", "tool_calls": None})()
        return type("S", (), {"values": {"messages": [ai]}})()


@pytest.mark.asyncio
async def test_run_turn_maps_events():
    from engine.setup_chat.agent import run_turn
    seen = []

    async def emit(ev):
        seen.append(ev)

    await run_turn(_FakeAgent(), "default", "改一下", emit, _NoopAccountant())
    types = [e["type"] for e in seen]
    assert "setup_chat_token" in types
    assert any(e["type"] == "setup_chat_tool" and e["phase"] == "start" for e in seen)
    assert types[-1] == "setup_chat_done"
    assert any(e["type"] == "setup_chat_final" for e in seen)
    tokens = "".join(e["delta"] for e in seen if e["type"] == "setup_chat_token")
    assert tokens == "你好改好了"


class _FakeAgentWithDistillStream:
    """Simulate the pre_model_hook distillation LLM to generate streaming tokens outside the tool."""

    async def astream_events(self, _input, **_kw):
        yield {"event": "on_chat_model_stream",
               "data": {"chunk": type("C", (), {"content": "- 星黏液简化为粘液\n"})()}}
        yield {"event": "on_chat_model_stream",
               "data": {"chunk": type("C", (), {"content": "- 爱丽丝感染改为意外\n"})()}}
        yield {"event": "on_chat_model_stream",
               "data": {"chunk": type("C", (), {"content": "好的，继续。"})()}}

    async def aget_state(self, _cfg):
        ai = type("M", (), {"type": "ai", "content": "好的，继续。", "tool_calls": None})()
        return type("S", (), {"values": {"messages": [ai]}})()


@pytest.mark.asyncio
async def test_run_turn_suppresses_distill_stream_when_guard_active(monkeypatch):
    """
Distilled streaming output should not be pushed to the frontend within a suppress context (suppressed by pre_model_hook)."""
    from engine.setup_chat import stream_guard
    from engine.setup_chat.agent import run_turn

    async def fake_astream(self, _input, **_kw):
        async with stream_guard.asuppress_setup_chat_stream():
            yield {"event": "on_chat_model_stream",
                   "data": {"chunk": type("C", (), {"content": "- 决策行\n"})()}}
        yield {"event": "on_chat_model_stream",
               "data": {"chunk": type("C", (), {"content": "可见回复"})()}}

    agent = _FakeAgentWithDistillStream()
    agent.astream_events = fake_astream.__get__(agent, type(agent))  # type: ignore[method-assign]
    seen = []

    async def emit(ev):
        seen.append(ev)

    await run_turn(agent, "default", "hi", emit, _NoopAccountant())
    tokens = "".join(e["delta"] for e in seen if e["type"] == "setup_chat_token")
    assert "- 决策行" not in tokens
    assert "可见回复" in tokens


@pytest.mark.asyncio
async def test_run_turn_suppresses_tokens_during_tool():
    from engine.setup_chat.agent import run_turn
    seen = []

    async def emit(ev):
        seen.append(ev)

    await run_turn(_FakeAgentWithInternalStream(), "default", "精修世界观", emit, _NoopAccountant())
    tokens = "".join(e["delta"] for e in seen if e["type"] == "setup_chat_token")
    assert tokens == "先回复改好了"
    assert '{"logline":' not in tokens


class _FakeAgentWithToolError:
    """When the tool reports an error, only on_tool_error (without on_tool_end) is sent; after that, tokens in the same round must be forwarded again."""

    async def astream_events(self, _input, **_kw):
        yield {"event": "on_tool_start", "name": "add_character", "data": {}}
        yield {"event": "on_tool_error", "name": "add_character", "data": {}}
        yield {"event": "on_chat_model_stream",
               "data": {"chunk": type("C", (), {"content": "我重新提交"})()}}

    async def aget_state(self, _cfg):
        ai = type("M", (), {"type": "ai", "content": "我重新提交", "tool_calls": None})()
        return type("S", (), {"values": {"messages": [ai]}})()


@pytest.mark.asyncio
async def test_run_turn_resets_depth_on_tool_error():
    """
When the tool reports an error, go to on_tool_error: tool_depth must be decremented, otherwise the subsequent tokens will be permanently swallowed.
    (This is one of the root causes of "there is no visible output in this round after the tool fails")."""
    from engine.setup_chat.agent import run_turn
    seen = []

    async def emit(ev):
        seen.append(ev)

    await run_turn(_FakeAgentWithToolError(), "default", "建 schema", emit, _NoopAccountant())
    tokens = "".join(e["delta"] for e in seen if e["type"] == "setup_chat_token")
    assert "我重新提交" in tokens
    #The error report should also be given an end to the front end to prevent the tool indicator from turning continuously.
    assert any(e["type"] == "setup_chat_tool" and e["phase"] == "end" for e in seen)


class _FakeAgentForToolLog:
    async def astream_events(self, _input, **_kw):
        yield {"event": "on_tool_start", "name": "add_character",
               "data": {"input": {"given_name": "甲", "role": "主角"}}}
        yield {"event": "on_tool_end", "name": "add_character",
               "data": {"output": type("TM", (), {"content": "已添加角色「甲」。"})()}}

    async def aget_state(self, _cfg):
        ai = type("M", (), {"type": "ai", "content": "好了", "tool_calls": None})()
        return type("S", (), {"values": {"messages": [ai]}})()


@pytest.mark.asyncio
async def test_run_turn_logs_tool_calls_backend():
    """
To see the tool call log in the background: name + input parameters + results in loguru (do not enter ws/front-end)."""
    from engine.setup_chat.agent import run_turn
    from loguru import logger

    captured: list[str] = []
    sink_id = logger.add(lambda m: captured.append(str(m)), level="INFO")
    seen = []

    async def emit(ev):
        seen.append(ev)

    try:
        await run_turn(_FakeAgentForToolLog(), "default", "加角色", emit, _NoopAccountant())
    finally:
        logger.remove(sink_id)

    joined = "".join(captured)
    assert "回合" in joined  #Turn start/end markers (tool_trace grouping)
    assert "add_character" in joined  #Tool name
    assert "甲" in joined  #Enter the log
    assert "已添加角色" in joined  #The result is entered in the log
    #But args/result should not be mixed into ws events sent to the front end (only with name/phase)
    tool_evs = [e for e in seen if e["type"] == "setup_chat_tool"]
    assert tool_evs and all(set(e) == {"type", "name", "phase"} for e in tool_evs)


class _FakeAgentStalledTurn:
    """There is no new assistant reply in this round (state ends with human), and there are old assistant messages from the previous round earlier."""

    async def astream_events(self, _input, **_kw):
        #In this round, only tools were run and there was no visible assistant token.
        yield {"event": "on_tool_start", "name": "generate_one_chapter", "data": {}}
        yield {"event": "on_tool_end", "name": "generate_one_chapter", "data": {}}

    async def aget_state(self, _cfg):
        msgs = [
            type("M", (), {"type": "ai", "content": "上一轮：第一章已写入完成", "tool_calls": None})(),
            type("M", (), {"type": "human", "content": "你好", "tool_calls": None})(),
        ]
        return type("S", (), {"values": {"messages": msgs}})()


class _FakeAgentPresentChoices:
    async def astream_events(self, _input, **_kw):
        yield {"event": "on_tool_start", "name": "present_choices",
               "data": {"input": {"question": "选哪个？", "options": ["甲", "乙"]}}}
        yield {"event": "on_tool_end", "name": "present_choices", "data": {}}

    async def aget_state(self, _cfg):
        ai = type("M", (), {"type": "ai", "content": "请选择", "tool_calls": None})()
        return type("S", (), {"values": {"messages": [ai]}})()


@pytest.mark.asyncio
async def test_run_turn_emits_choice_event():
    from engine.setup_chat.agent import run_turn
    seen = []

    async def emit(ev):
        seen.append(ev)

    await run_turn(_FakeAgentPresentChoices(), "default", "帮我选", emit, _NoopAccountant())
    choice = [e for e in seen if e["type"] == "setup_chat_choice"]
    assert choice and choice[0]["question"] == "选哪个？"
    assert choice[0]["options"] == ["甲", "乙"]


@pytest.mark.asyncio
async def test_run_turn_suppresses_choice_event_in_auto_mode(monkeypatch):
    from engine.setup_chat import mode
    monkeypatch.setattr(mode, "_AUTO", True)
    from engine.setup_chat.agent import run_turn
    seen = []

    async def emit(ev):
        seen.append(ev)

    await run_turn(_FakeAgentPresentChoices(), "default", "帮我选", emit, _NoopAccountant())
    choice = [e for e in seen if e["type"] == "setup_chat_choice"]
    assert choice == []


class _FakeAgentCapturesConfig:
    """Records the config kwarg astream_events was called with, so the test can
    assert on recursion_limit without needing a real LangGraph agent."""

    def __init__(self):
        self.seen_config: dict | None = None

    async def astream_events(self, _input, **kw):
        self.seen_config = kw.get("config")
        return
        yield  # pragma: no cover - makes this an async generator

    async def aget_state(self, _cfg):
        return type("S", (), {"values": {"messages": []}})()


@pytest.mark.asyncio
async def test_run_turn_uses_default_recursion_limit_in_manual_mode(monkeypatch):
    from engine.setup_chat import mode
    monkeypatch.setattr(mode, "_AUTO", False)
    from engine.setup_chat.agent import run_turn
    from engine.setup_chat.hooks import SETUP_CHAT_RECURSION_LIMIT

    fake = _FakeAgentCapturesConfig()

    async def emit(ev):
        pass

    await run_turn(fake, "default", "你好", emit, _NoopAccountant())
    assert fake.seen_config["recursion_limit"] == SETUP_CHAT_RECURSION_LIMIT


@pytest.mark.asyncio
async def test_run_turn_uses_bumped_recursion_limit_in_auto_mode(monkeypatch):
    from engine.setup_chat import mode
    monkeypatch.setattr(mode, "_AUTO", True)
    from engine.setup_chat.agent import run_turn

    fake = _FakeAgentCapturesConfig()

    async def emit(ev):
        pass

    await run_turn(fake, "default", "你好", emit, _NoopAccountant())
    assert fake.seen_config["recursion_limit"] == 256


@pytest.mark.asyncio
async def test_run_turn_no_final_when_turn_has_no_fresh_assistant():
    """
When there is no new assistant reply in this round, the old reply from the previous round must not be re-sent as the result of this round (the root cause is repeatedly displayed on the front end)."""
    from engine.setup_chat.agent import run_turn
    seen = []

    async def emit(ev):
        seen.append(ev)

    await run_turn(_FakeAgentStalledTurn(), "default", "你好", emit, _NoopAccountant())
    finals = [e for e in seen if e["type"] == "setup_chat_final"]
    assert finals == []  #Do not resend old replies
    assert any(e["type"] == "setup_chat_done" for e in seen)  #But still ends normally


@pytest.mark.asyncio
async def test_drive_stream_records_usage_on_chat_model_end():
    """on_chat_model_end must feed the accountant, not just on_chat_model_stream/on_tool_*."""
    from engine.setup_chat.agent import _drive_stream

    class _FakeAgentEmitsUsage:
        async def astream_events(self, _input, **_kw):
            yield {"event": "on_chat_model_stream",
                   "data": {"chunk": type("C", (), {"content": "hi"})()}}
            yield {
                "event": "on_chat_model_end",
                "data": {"output": type("M", (), {
                    "usage_metadata": {"input_tokens": 10, "output_tokens": 5, "input_token_details": {}},
                })()},
            }

    recorded = []

    class _RecordingAccountant:
        async def record(self, tin, tout, tcached):
            recorded.append((tin, tout, tcached))

    seen = []

    async def emit(ev):
        seen.append(ev)

    await _drive_stream(
        _FakeAgentEmitsUsage(), {"messages": []}, {"configurable": {"thread_id": "n1"}},
        emit, "persist", _RecordingAccountant(),
    )
    assert recorded == [(10, 5, 0)]


@pytest.mark.asyncio
async def test_drive_stream_makes_emit_reachable_via_tool_progress(monkeypatch):
    """A tool executed inside astream_events must be able to call emit_tool_progress and have
    it reach this call's own `emit` -- proves _drive_stream wraps the streaming loop in
    emit_scope(emit)."""
    from engine.setup_chat.agent import _drive_stream
    from engine.setup_chat.tool_progress import emit_tool_progress

    received: list[dict] = []

    async def fake_emit(ev: dict) -> None:
        received.append(ev)

    class _FakeAgent:
        async def astream_events(self, inp, version, config):
            # Simulate a tool node calling emit_tool_progress mid-stream, the way
            # auto_build_setup's internal orchestration would.
            await emit_tool_progress("auto_build_setup", "世界观已构建")
            return
            yield  # pragma: no cover -- makes this an async generator

    await _drive_stream(_FakeAgent(), {}, {}, fake_emit, "unused-persist-dir", _NoopAccountant())

    progress_events = [e for e in received if e.get("phase") == "progress"]
    assert progress_events == [
        {"type": "setup_chat_tool", "name": "auto_build_setup", "phase": "progress",
         "label": "世界观已构建"},
    ]
