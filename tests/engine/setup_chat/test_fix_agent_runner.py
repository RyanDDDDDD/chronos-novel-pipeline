import pytest


class _FakeAIMessage:
    def __init__(self, content, tool_calls: list | None = None):
        self.type = "ai"
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeToolBoundModel:
    def __init__(self, response):
        self._response = response
        self.bound_with: dict | None = None

    def bind(self, **kwargs):
        self.bound_with = kwargs
        return self

    async def ainvoke(self, messages):
        self.messages = messages
        return self._response


class _FakeBaseLlm:
    def __init__(self, response):
        self._response = response
        self.bind_tools_called_with: list | None = None
        self.tool_bound: _FakeToolBoundModel | None = None

    def bind_tools(self, tools):
        self.bind_tools_called_with = tools
        self.tool_bound = _FakeToolBoundModel(self._response)
        return self.tool_bound


class _FakeTool:
    def __init__(self, name):
        self.name = name
        self.calls: list = []

    async def ainvoke(self, args):
        self.calls.append(args)
        return f"{self.name} 已执行"


def _patch_llm_plumbing(monkeypatch, base_llm, *, sampling: dict | None = None) -> None:
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.resolve_node_base_llm",
        lambda llm, node_name, params: base_llm,
    )
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.node_llm_sampling_kwargs",
        lambda base, node_name, params: sampling or {},
    )
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {}},
    )
    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: object())


@pytest.mark.asyncio
async def test_run_single_shot_fix_agent_returns_content_and_executes_tool_calls(monkeypatch):
    from engine.setup_chat import fix_agent_runner as far

    tool = _FakeTool("edit_character")
    response = _FakeAIMessage(
        "已把角色的执念改成了「守护家人」。",
        tool_calls=[{"name": "edit_character", "args": {"name": "甲"}}],
    )
    base_llm = _FakeBaseLlm(response)
    _patch_llm_plumbing(monkeypatch, base_llm)

    result = await far.run_single_shot_fix_agent(
        node_name="character_fix_agent", tools=[tool], prompt="p", task_text="t",
    )

    assert result == "已把角色的执念改成了「守护家人」。"
    assert tool.calls == [{"name": "甲"}]
    assert base_llm.bind_tools_called_with == [tool]


@pytest.mark.asyncio
async def test_run_single_shot_fix_agent_executes_multiple_parallel_tool_calls(monkeypatch):
    """No follow-up turn exists, so a fix touching several independent things (multiple
    world dimensions, multiple failing stages) must be planned as parallel tool_calls in
    the single response and all of them executed."""
    from engine.setup_chat import fix_agent_runner as far

    tone_tool = _FakeTool("set_world_tone")
    faction_tool = _FakeTool("set_world_faction")
    response = _FakeAIMessage(
        "已同时补充了基调与势力设定。",
        tool_calls=[
            {"name": "set_world_tone", "args": {"tone": "压抑"}},
            {"name": "set_world_faction", "args": {"faction": "北境议会"}},
        ],
    )
    base_llm = _FakeBaseLlm(response)
    _patch_llm_plumbing(monkeypatch, base_llm)

    result = await far.run_single_shot_fix_agent(
        node_name="world_fix_agent", tools=[tone_tool, faction_tool], prompt="p", task_text="t",
    )

    assert result == "已同时补充了基调与势力设定。"
    assert tone_tool.calls == [{"tone": "压抑"}]
    assert faction_tool.calls == [{"faction": "北境议会"}]


@pytest.mark.asyncio
async def test_run_single_shot_fix_agent_falls_back_when_content_empty(monkeypatch):
    from engine.setup_chat import fix_agent_runner as far

    tool = _FakeTool("edit_character")
    response = _FakeAIMessage("", tool_calls=[{"name": "edit_character", "args": {}}])
    base_llm = _FakeBaseLlm(response)
    _patch_llm_plumbing(monkeypatch, base_llm)

    result = await far.run_single_shot_fix_agent(
        node_name="character_fix_agent", tools=[tool], prompt="p", task_text="t",
    )
    assert result == "（fix agent 未给出文字总结）"


@pytest.mark.asyncio
async def test_run_single_shot_fix_agent_extracts_text_blocks_from_content_list(monkeypatch):
    """Anthropic with tool calls + thinking active returns content as a list of blocks --
    only "text" blocks belong in the summary, thinking traces must not leak into it."""
    from engine.setup_chat import fix_agent_runner as far

    tool = _FakeTool("edit_character")
    response = _FakeAIMessage(
        [
            {"type": "thinking", "thinking": "内部推理过程，不应出现在总结里"},
            {"type": "text", "text": "已把因果锚点改成了「为亡母复仇」。"},
        ],
        tool_calls=[{"name": "edit_character", "args": {}}],
    )
    base_llm = _FakeBaseLlm(response)
    _patch_llm_plumbing(monkeypatch, base_llm)

    result = await far.run_single_shot_fix_agent(
        node_name="character_fix_agent", tools=[tool], prompt="p", task_text="t",
    )
    assert result == "已把因果锚点改成了「为亡母复仇」。"


@pytest.mark.asyncio
async def test_run_single_shot_fix_agent_ignores_unknown_tool_call_names(monkeypatch):
    from engine.setup_chat import fix_agent_runner as far

    tool = _FakeTool("edit_character")
    response = _FakeAIMessage(
        "改完了。", tool_calls=[{"name": "some_other_tool", "args": {}}],
    )
    base_llm = _FakeBaseLlm(response)
    _patch_llm_plumbing(monkeypatch, base_llm)

    result = await far.run_single_shot_fix_agent(
        node_name="character_fix_agent", tools=[tool], prompt="p", task_text="t",
    )
    assert result == "改完了。"
    assert tool.calls == []


@pytest.mark.asyncio
async def test_run_single_shot_fix_agent_applies_node_sampling_kwargs(monkeypatch):
    from engine.setup_chat import fix_agent_runner as far

    tool = _FakeTool("edit_character")
    response = _FakeAIMessage("改完了。", tool_calls=[])
    base_llm = _FakeBaseLlm(response)
    _patch_llm_plumbing(
        monkeypatch, base_llm,
        sampling={"thinking": {"type": "enabled", "budget_tokens": 16000}},
    )

    await far.run_single_shot_fix_agent(
        node_name="character_fix_agent", tools=[tool], prompt="p", task_text="t",
    )

    assert base_llm.tool_bound.bound_with == {"thinking": {"type": "enabled", "budget_tokens": 16000}}
