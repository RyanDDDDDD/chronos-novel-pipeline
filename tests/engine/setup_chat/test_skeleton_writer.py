import pytest

from repo_test_helpers import seed_plot


def _seed_env(plot):
    seed_plot(plot)


_PLOT = [{"chapter": 1, "title": "一", "stages": [
    {"stage_num": 1, "description": "甲乙对峙", "characters": {"甲": {}}},
    {"stage_num": 2, "description": "丙登场", "characters": {"丙": {}}},
]}]

_PLOT_STAGE1_DONE = [{"chapter": 1, "title": "一", "stages": [
    {"stage_num": 1, "description": "甲乙对峙", "characters": {"甲": {}},
     "beats": [{"text": "上一段的拍文", "sensation_notes": []}]},
    {"stage_num": 2, "description": "丙登场", "characters": {"丙": {}}},
]}]

_PLOT_WITH_EXISTING_BEATS = [{"chapter": 1, "title": "一", "stages": [
    {"stage_num": 1, "description": "甲乙对峙", "characters": {"甲": {}},
     "beats": [{"text": "旧拍文", "sensation_notes": []}]},
    {"stage_num": 2, "description": "丙登场", "characters": {"丙": {}}},
]}]


@pytest.mark.asyncio
async def test_generate_stage_beats_revision_without_overview_returns_error_without_llm_call(
    monkeypatch, tmp_path,
):
    from engine.setup_chat import skeleton_writer as sw
    _seed_env(_PLOT_WITH_EXISTING_BEATS)

    async def fail_if_called(system, user, **kwargs):
        raise AssertionError("must not call the LLM when overview is empty on revision")
    monkeypatch.setattr(sw, "_call_llm", fail_if_called)

    result = await sw.generate_stage_beats(1, 1, overview="", is_revision=True)
    assert isinstance(result, str)
    assert "修改意见" in result


@pytest.mark.asyncio
async def test_generate_stage_beats_missing_stage_returns_error(monkeypatch, tmp_path):
    from engine.setup_chat import skeleton_writer as sw
    _seed_env(_PLOT)

    result = await sw.generate_stage_beats(1, 99, overview="", is_revision=False)
    assert isinstance(result, str)
    assert "99" in result


@pytest.mark.asyncio
async def test_generate_stage_beats_first_time_prompts_with_lens_and_extensions(
    monkeypatch, tmp_path,
):
    from engine.setup_chat import skeleton_pipeline as sp
    from engine.setup_chat import skeleton_writer as sw
    _seed_env(_PLOT)
    sp._LENS_CHOSEN[(1, 1)] = ["压迫感"]
    sp._EXT_CHOSEN[(1, 1)] = ["拓展A"]

    captured = {}

    async def fake_call(system, user, **kwargs):
        captured["user"] = user
        return '{"beats": [{"text": "拍0正文", "sensation_notes": []}]}'
    monkeypatch.setattr(sw, "_call_llm", fake_call)

    result = await sw.generate_stage_beats(1, 1, overview="", is_revision=False)
    assert result == [{"text": "拍0正文", "sensation_notes": [], "dialogue_draft": ""}]
    assert "压迫感" in captured["user"]
    assert "拓展A" in captured["user"]


@pytest.mark.asyncio
async def test_generate_stage_beats_first_time_includes_overview_when_given(
    monkeypatch, tmp_path,
):
    from engine.setup_chat import skeleton_pipeline as sp
    from engine.setup_chat import skeleton_writer as sw
    _seed_env(_PLOT)
    sp._LENS_CHOSEN[(1, 1)] = ["a"]
    sp._EXT_CHOSEN[(1, 1)] = []

    captured = {}

    async def fake_call(system, user, **kwargs):
        captured["user"] = user
        return '{"beats": [{"text": "拍0正文", "sensation_notes": []}]}'
    monkeypatch.setattr(sw, "_call_llm", fake_call)

    await sw.generate_stage_beats(1, 1, overview="对话里聊到的额外细节", is_revision=False)
    assert "对话里聊到的额外细节" in captured["user"]


@pytest.mark.asyncio
async def test_generate_stage_beats_feeds_previous_stage_for_continuity(monkeypatch, tmp_path):
    from engine.setup_chat import skeleton_pipeline as sp
    from engine.setup_chat import skeleton_writer as sw
    _seed_env(_PLOT_STAGE1_DONE)
    sp._LENS_CHOSEN[(1, 2)] = ["a"]
    sp._EXT_CHOSEN[(1, 2)] = []

    captured = {}

    async def fake_call(system, user, **kwargs):
        captured["user"] = user
        return '{"beats": [{"text": "拍0正文", "sensation_notes": []}]}'
    monkeypatch.setattr(sw, "_call_llm", fake_call)

    await sw.generate_stage_beats(1, 2, overview="", is_revision=False)
    assert "上一段的拍文" in captured["user"]


@pytest.mark.asyncio
async def test_generate_stage_beats_revision_prompts_with_existing_beats_and_instruction(
    monkeypatch, tmp_path,
):
    from engine.setup_chat import skeleton_writer as sw
    _seed_env(_PLOT_WITH_EXISTING_BEATS)

    captured = {}

    async def fake_call(system, user, **kwargs):
        captured["user"] = user
        return '{"beats": [{"text": "改后拍文", "sensation_notes": []}]}'
    monkeypatch.setattr(sw, "_call_llm", fake_call)

    result = await sw.generate_stage_beats(1, 1, overview="改成更压抑的基调", is_revision=True)
    assert result == [{"text": "改后拍文", "sensation_notes": [], "dialogue_draft": ""}]
    assert "旧拍文" in captured["user"]
    assert "改成更压抑的基调" in captured["user"]


@pytest.mark.asyncio
async def test_generate_stage_beats_retries_on_parse_failure_then_succeeds(monkeypatch, tmp_path):
    from engine.setup_chat import skeleton_pipeline as sp
    from engine.setup_chat import skeleton_writer as sw
    _seed_env(_PLOT)
    sp._LENS_CHOSEN[(1, 1)] = ["a"]
    sp._EXT_CHOSEN[(1, 1)] = []

    calls = 0

    async def flaky_call(system, user, **kwargs):
        nonlocal calls
        calls += 1
        if calls < 2:
            return "not json"
        return '{"beats": [{"text": "拍0正文", "sensation_notes": []}]}'
    monkeypatch.setattr(sw, "_call_llm", flaky_call)

    result = await sw.generate_stage_beats(1, 1, overview="", is_revision=False)
    assert result == [{"text": "拍0正文", "sensation_notes": [], "dialogue_draft": ""}]
    assert calls == 2


@pytest.mark.asyncio
async def test_generate_stage_beats_gives_up_after_max_attempts(monkeypatch, tmp_path):
    from engine.setup_chat import skeleton_pipeline as sp
    from engine.setup_chat import skeleton_writer as sw
    _seed_env(_PLOT)
    sp._LENS_CHOSEN[(1, 1)] = ["a"]
    sp._EXT_CHOSEN[(1, 1)] = []

    calls = 0

    async def always_bad(system, user, **kwargs):
        nonlocal calls
        calls += 1
        return "not json"
    monkeypatch.setattr(sw, "_call_llm", always_bad)

    result = await sw.generate_stage_beats(1, 1, overview="", is_revision=False)
    assert isinstance(result, str)
    assert calls == 3


@pytest.mark.asyncio
async def test_generate_stage_beats_rejects_empty_beat_text(monkeypatch, tmp_path):
    """A beat with an empty text field should fail BeatArgs validation and retry, not persist
    a blank beat."""
    from engine.setup_chat import skeleton_pipeline as sp
    from engine.setup_chat import skeleton_writer as sw
    _seed_env(_PLOT)
    sp._LENS_CHOSEN[(1, 1)] = ["a"]
    sp._EXT_CHOSEN[(1, 1)] = []

    calls = 0

    async def bad_then_good(system, user, **kwargs):
        nonlocal calls
        calls += 1
        if calls < 2:
            return '{"beats": [{"text": "", "sensation_notes": []}]}'
        return '{"beats": [{"text": "拍0正文", "sensation_notes": []}]}'
    monkeypatch.setattr(sw, "_call_llm", bad_then_good)

    result = await sw.generate_stage_beats(1, 1, overview="", is_revision=False)
    assert result == [{"text": "拍0正文", "sensation_notes": [], "dialogue_draft": ""}]
    assert calls == 2


def test_skeleton_writer_system_prompt_demands_clean_output_no_meta_tags():
    """This constraint used to live in skeleton-expansion/SKILL.md (chat's own instructions,
    tested by test_skills.py::test_skeleton_skills_demand_clean_output_no_meta_tags, now
    removed in favor of this test) -- it moved here because chat no longer composes the prose
    itself, the internal generator does."""
    from engine.setup_chat import skeleton_writer as sw
    assert "纯净" in sw._SKELETON_WRITER_SYS
    assert "标签" in sw._SKELETON_WRITER_SYS


@pytest.mark.asyncio
async def test_call_llm_routes_through_skeleton_writer_node(monkeypatch):
    from engine.setup_chat import skeleton_writer as sw

    class _FakeResp:
        content = "beats-json"

    class _FakeLLM:
        async def ainvoke(self, _messages):
            return _FakeResp()

    bind_calls: list[tuple[str, dict]] = []

    def fake_bind_node_llm(llm, agent, params):
        bind_calls.append((agent, params))
        return _FakeLLM()

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: object())
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {"skeleton_writer": {"enable_thinking": False}}},
    )
    monkeypatch.setattr("engine.modes.author_loop_skill_prefs.bind_node_llm", fake_bind_node_llm)

    out = await sw._call_llm("sys", "user")
    assert out == "beats-json"
    assert bind_calls == [("skeleton_writer", {"skeleton_writer": {"enable_thinking": False}})]
