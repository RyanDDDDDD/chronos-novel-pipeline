import asyncio
import json

import pytest
from engine.story_sandbox import graph as g
from engine.story_sandbox.graph import (
    _guard_list,
    _guard_scene_dict,
    _guard_state_dict,
    close_checkpointer,
    run_turn,
)
from engine.story_sandbox.state import LEGACY_BRANCH_ID, SandboxStepType, seed_state

_EDGE_甲乙 = {
    "from": "甲", "to": "乙", "nature": "结拜", "relationship_anchor": "",
    "from_ref_terms": [], "to_ref_terms": [],
}


@pytest.fixture(autouse=True)
def _isolated_checkpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "utils.paths.story_sandbox_checkpoint_path", lambda: str(tmp_path / "cp.sqlite"),
    )
    monkeypatch.setattr(
        "engine.story_sandbox.prompt.build_sandbox_system_prompt",
        # kwargs stringified into the return so tests can still assert on what the caller (a
        # prose node) fed in -- e.g. character_states -- without this stub knowing how the real
        # progress block formats it. Returns (prompt, opening_names) to match the real function's
        # tuple contract; opening_names is always {"甲"} here so tests exercising an opening turn
        # (which excludes those names from the dynamic cast block) see a stable exclude set.
        lambda chapter, is_opening, **kwargs: (f"系统提示 {kwargs}", {"甲"} if is_opening else set()),
    )
    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.cards.render_character_card",
        lambda name, chapter, stage, *, include_persona=True: f"角色：{name}",
    )
    monkeypatch.setattr("engine.setup.chat_summary.render_world_chat", lambda wb: "")
    monkeypatch.setattr(
        "engine.story_sandbox.cast.render_dynamic_cast_block",
        lambda active_cast, *, chapter, exclude=None: "",
    )
    monkeypatch.setattr(
        "engine.story_sandbox.state.seed_state",
        lambda: {
            "turns": [], "rolling_summary": "", "suggestions": [],
            "character_states": {"甲": {"psychology": "内向"}},
            "scene_state": {}, "character_profile": {}, "recall_cooldown": {}, "active_cast": {},
            "relationship_overlay": {}, "background_cast": [],
        },
    )
    monkeypatch.setattr(
        "engine.memory_recall.recall.recall_relevant_context",
        lambda text, **kwargs: ("", kwargs.get("cooldown") or {}, []),
    )
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.build_character_vocab",
        lambda: {"甲", "乙"},
    )
    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: ["甲"])
    monkeypatch.setattr(
        "engine.story_sandbox.cast.resolve_character_cards",
        lambda chapter, names: [{"name": n, "card": f"角色：{n}"} for n in names],
    )
    yield
    import asyncio

    # asyncio.run() (not get_event_loop()) -- when this file runs alongside other test files in
    # a full suite run, pytest-asyncio's own function-scoped loop for this test can already be
    # gone by the time this autouse fixture's teardown runs, and get_event_loop() raises "no
    # current event loop" in that case. asyncio.run() always creates its own loop instead of
    # depending on any ambient "current" one.
    asyncio.run(close_checkpointer())


async def _write_turn(_system: str, _packet: str) -> str:
    return "甲抬起头，看向窗外。"


async def _call_llm(system: str, _user: str) -> str:
    if "剧情摘要助手" in system:
        return "折叠后的摘要"
    if "事件摘要助手" in system:
        return (
            '{"event": "甲抬起头", "time": "对峙之后", "location": "书房", '
            '"characters": ["甲"], "entities": []}'
        )
    if "走向建议" in system:
        return '["建议一", "建议二"]'
    if "场景当前的状态" in system or "场景推演出开场时的初始状态" in system:
        return '{"description": "昏暗的书房"}'
    if "根据这段正文内容" in system or "根据导演指令" in system:
        return '{"角色": ["甲"], "路人": []}'
    return '{"甲": {"psychology": "逐渐大胆"}}'


async def _identity_guard_text(s: str) -> str:
    return s


FORBIDDEN = "违规词"
REPLACEMENT = "替换后"


async def _replace_forbidden_guard(s: str) -> str:
    return s.replace(FORBIDDEN, REPLACEMENT) if FORBIDDEN in s else s


@pytest.mark.asyncio
async def test_guard_state_dict_rewrites_matching_field_only():
    async def guard_text(s: str) -> str:
        return s.replace("违规词", "替换后") if "违规词" in s else s

    states = {
        "角色A": {"psychology": "带着违规词的心理", "posture": "正常体态"},
        "角色B": {"psychology": "正常心理"},
    }
    result = await _guard_state_dict(states, guard_text)
    assert result["角色A"]["psychology"] == "带着替换后的心理"
    assert result["角色A"]["posture"] == "正常体态"
    assert result["角色B"] == states["角色B"]


@pytest.mark.asyncio
async def test_guard_scene_dict_skips_empty_and_non_str():
    async def guard_text(s: str) -> str:
        return "改写后"

    scene = {"description": "", "atmosphere": "有内容"}
    result = await _guard_scene_dict(scene, guard_text)
    assert result["description"] == ""
    assert result["atmosphere"] == "改写后"


@pytest.mark.asyncio
async def test_guard_list_preserves_order_and_length():
    async def guard_text(s: str) -> str:
        return s.upper() if s == "b" else s

    result = await _guard_list(["a", "b", "c"], guard_text)
    assert result == ["a", "B", "c"]


def test_locate_fragment_finds_unique_match():
    from engine.story_sandbox.graph import _locate_fragment

    prose = "甲抬起头，看向窗外。"
    start, end = _locate_fragment(prose, "看向窗外", 0)
    assert prose[start:end] == "看向窗外"


def test_locate_fragment_disambiguates_repeated_text_by_anchor_offset():
    from engine.story_sandbox.graph import _locate_fragment

    prose = "他笑了笑。她也笑了笑，转身走了。"
    first = prose.index("笑了笑")
    second = prose.index("笑了笑", first + 1)
    start, end = _locate_fragment(prose, "笑了笑", second)
    assert (start, end) == (second, second + len("笑了笑"))


def test_locate_fragment_raises_when_text_not_found():
    from engine.story_sandbox.graph import _locate_fragment

    with pytest.raises(ValueError):
        _locate_fragment("甲抬起头。", "乙站起来", 0)


def test_locate_fragment_raises_on_empty_text():
    from engine.story_sandbox.graph import _locate_fragment

    with pytest.raises(ValueError):
        _locate_fragment("甲抬起头。", "", 0)


def test_build_selection_rewrite_prompt_includes_style_card_prose_and_fragment():
    from engine.story_sandbox.graph import _build_selection_rewrite_prompt

    system, user = _build_selection_rewrite_prompt(
        "本书文风：克制、留白", "甲抬起头，看向窗外。", "看向窗外", "语气再冷淡一点",
    )
    assert "本书文风：克制、留白" in system
    assert "【修改后的片段】：" in system
    assert "甲抬起头，看向窗外。" in user
    assert "看向窗外" in user
    assert "语气再冷淡一点" in user


def test_build_selection_rewrite_prompt_blank_feedback_gets_placeholder():
    from engine.story_sandbox.graph import _build_selection_rewrite_prompt

    _, user = _build_selection_rewrite_prompt("", "甲抬起头。", "抬起头", "")
    assert "（未填写，按你的判断改一版）" in user


def test_build_selection_rewrite_prompt_skips_style_section_when_no_card():
    from engine.story_sandbox.graph import _build_selection_rewrite_prompt

    system, _ = _build_selection_rewrite_prompt("", "甲抬起头。", "抬起头", "")
    assert "文风" not in system


def test_extract_rewritten_fragment_strips_marker_and_preamble():
    from engine.story_sandbox.graph import _extract_rewritten_fragment

    raw = "好的，这是根据您的要求重写后的段落：\n【修改后的片段】：望向远方"
    assert _extract_rewritten_fragment(raw) == "望向远方"


def test_extract_rewritten_fragment_accepts_half_width_colon():
    from engine.story_sandbox.graph import _extract_rewritten_fragment

    assert _extract_rewritten_fragment("【修改后的片段】: 望向远方") == "望向远方"


def test_extract_rewritten_fragment_fails_open_when_marker_missing():
    from engine.story_sandbox.graph import _extract_rewritten_fragment

    assert _extract_rewritten_fragment("  望向远方  ") == "望向远方"


async def _drain(gen):
    """Collect an async-generator run_turn()/rewrite_last_round() call into the old
    (text, suggestions, character_states, initial_states) shape -- for tests that only care
    about the final bundled result, not per-step timing."""
    text = ""
    suggestions: list[str] = []
    states: dict = {}
    initial_states = None
    async for step in gen:
        if step["type"] == SandboxStepType.INITIAL_STATE:
            initial_states = step.get("states")
        elif step["type"] == SandboxStepType.PROSE:
            text = step["text"]
        elif step["type"] == SandboxStepType.STATE:
            states = step["states"]
        elif step["type"] == SandboxStepType.SUGGESTIONS:
            suggestions = step["options"]
    return text, suggestions, states, initial_states


def _with_llms(llm, guard_text=_identity_guard_text):
    """Expand one fake LLM into the per-node call_llm kwargs plus the per-node guard_text
    kwargs that run_turn/rewrite_last_round expect."""
    return dict(
        call_llm_derive_char=llm,
        call_llm_derive_scene=llm,
        call_llm_summary_fold=llm, call_llm_event_extract=llm,
        call_llm_profile_mutate=llm,
        call_llm_suggest=llm,
        call_llm_identify=llm,
        guard_text_derive_char=guard_text,
        guard_text_derive_scene=guard_text,
        guard_text_summary_fold=guard_text, guard_text_event_extract=guard_text,
        guard_text_profile_mutate=guard_text,
        guard_text_suggest=guard_text,
    )


def _make_identify_stub(cast_result, passersby=None):
    if passersby is None:
        passersby = []
    async def _stub(instruction, roster, call_llm):
        return (cast_result, passersby)
    return _stub


@pytest.mark.asyncio
async def test_init_char_uses_identify_result_for_cards(monkeypatch):
    from engine.story_sandbox.graph import _build_init_char_node

    monkeypatch.setattr(
        "engine.memory_recall.entity_index.build_character_vocab", lambda: {"甲", "乙"},
    )
    monkeypatch.setattr(
        "engine.story_sandbox.cast_identify.resolve_present_roster",
        _make_identify_stub(["甲"]),
    )
    seen_names = {}

    def _fake_resolve_cards(chapter, names):
        seen_names["names"] = names
        return [{"name": n, "card": f"角色：{n}"} for n in names]

    monkeypatch.setattr("engine.story_sandbox.cast.resolve_character_cards", _fake_resolve_cards)

    async def _derive_initial_states(cards, instruction, call_llm):
        return {c["name"]: {} for c in cards}

    monkeypatch.setattr(
        "engine.story_sandbox.graph.derive_initial_states", _derive_initial_states,
    )

    node = _build_init_char_node(0, "写甲登场", _call_llm, object(), _identity_guard_text)
    result = await node({})
    assert seen_names["names"] == ["甲"]
    assert result["known_roster_fallback_this_turn"] == []
    assert "甲" in result["initial_states_this_turn"]


@pytest.mark.asyncio
async def test_init_char_falls_back_to_roster_when_nobody_identified(monkeypatch):
    from engine.story_sandbox.graph import _build_init_char_node

    monkeypatch.setattr(
        "engine.memory_recall.entity_index.build_character_vocab", lambda: {"甲", "乙"},
    )
    monkeypatch.setattr(
        "engine.story_sandbox.cast_identify.resolve_present_roster",
        _make_identify_stub([]),
    )

    async def _derive_initial_states(cards, instruction, call_llm):
        return {}

    monkeypatch.setattr(
        "engine.story_sandbox.graph.derive_initial_states", _derive_initial_states,
    )

    node = _build_init_char_node(0, "随便写个开场", _call_llm, object(), _identity_guard_text)
    result = await node({})
    assert sorted(result["known_roster_fallback_this_turn"]) == ["乙", "甲"]
    assert result["initial_states_this_turn"] == {}


@pytest.mark.asyncio
async def test_init_char_no_fallback_when_identify_unavailable_and_scan_empty(monkeypatch):
    from engine.story_sandbox.graph import _build_init_char_node

    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: [])

    async def _derive_initial_states(cards, instruction, call_llm):
        return {}

    monkeypatch.setattr(
        "engine.story_sandbox.graph.derive_initial_states", _derive_initial_states,
    )

    node = _build_init_char_node(0, "随便写个开场", _call_llm, None, _identity_guard_text)
    result = await node({})
    assert result["known_roster_fallback_this_turn"] == []
    assert result["initial_states_this_turn"] == {}


@pytest.mark.asyncio
async def test_init_char_identify_unavailable_falls_back_to_deterministic_scan(monkeypatch):
    """No call_llm_identify (identify layer inactive) must still ground initial_states in
    whoever scan_characters(instruction) deterministically finds -- chapter and free mode share
    this exact fallback now, no more per-mode branching."""
    from engine.story_sandbox.graph import _build_init_char_node

    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: ["甲"] if "甲" in text else [],
    )
    seen_names = {}

    def _fake_resolve_cards(chapter, names):
        seen_names["names"] = names
        return [{"name": n, "card": f"角色：{n}"} for n in names]

    monkeypatch.setattr("engine.story_sandbox.cast.resolve_character_cards", _fake_resolve_cards)

    async def _derive_initial_states(cards, instruction, call_llm):
        return {c["name"]: {} for c in cards}

    monkeypatch.setattr(
        "engine.story_sandbox.graph.derive_initial_states", _derive_initial_states,
    )

    node = _build_init_char_node(1, "甲登场", _call_llm, None, _identity_guard_text)
    result = await node({})
    assert seen_names["names"] == ["甲"]
    assert "甲" in result["initial_states_this_turn"]


@pytest.mark.asyncio
async def test_init_char_chapter_and_free_mode_share_identical_card_resolution(monkeypatch):
    """Regression: chapter mode (chapter > 0) must go through the exact same
    resolve_present_roster -> resolve_character_cards path as free mode -- no more
    resolve_stage1_cast-derived pre-filtered card list."""
    from engine.story_sandbox.graph import _build_init_char_node

    monkeypatch.setattr(
        "engine.memory_recall.entity_index.build_character_vocab", lambda: {"甲", "乙"},
    )
    monkeypatch.setattr(
        "engine.story_sandbox.cast_identify.resolve_present_roster",
        _make_identify_stub(["甲"]),
    )
    calls = []

    def _fake_resolve_cards(chapter, names):
        calls.append(names)
        return [{"name": n, "card": f"角色：{n}"} for n in names]

    monkeypatch.setattr("engine.story_sandbox.cast.resolve_character_cards", _fake_resolve_cards)

    async def _derive_initial_states(cards, instruction, call_llm):
        return {c["name"]: {} for c in cards}

    monkeypatch.setattr(
        "engine.story_sandbox.graph.derive_initial_states", _derive_initial_states,
    )

    node = _build_init_char_node(1, "写甲登场", _call_llm, object(), _identity_guard_text)
    result = await node({})
    assert calls == [["甲"]]
    assert result["known_roster_fallback_this_turn"] == []
    assert "甲" in result["initial_states_this_turn"]


@pytest.mark.asyncio
async def test_init_char_node_includes_passerby_in_states_and_passerby_names(monkeypatch):
    monkeypatch.setattr(
        "engine.story_sandbox.cast_identify.resolve_present_roster",
        _make_identify_stub(["高木柔柔"], ["路边大爷"]),
    )
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.build_character_vocab", lambda: {"高木柔柔"},
    )
    monkeypatch.setattr(
        "engine.story_sandbox.cast.resolve_character_cards",
        lambda chapter, names: [{"name": n, "card": f"角色：{n}"} for n in names],
    )

    async def _derive_initial_states(cards, instruction, call_llm):
        return {"高木柔柔": {"psychology": "警惕"}, "路边大爷": {"psychology": "疑惑"}}

    monkeypatch.setattr(
        "engine.story_sandbox.graph.derive_initial_states", _derive_initial_states,
    )

    from engine.story_sandbox.graph import _build_init_char_node

    node = _build_init_char_node(0, "柔柔路过菜摊，跟卖菜的大爷搭话", _call_llm, object(), _identity_guard_text)
    result = await node({})
    assert "高木柔柔" in result["initial_states_this_turn"]
    assert "路边大爷" in result["initial_states_this_turn"]
    assert result["passerby_names"] == ["路边大爷"]


@pytest.mark.asyncio
async def test_init_scene_free_mode_passes_geography_names_as_known_locations(monkeypatch):
    from engine.story_sandbox.graph import _build_init_scene_node

    monkeypatch.setattr(
        "engine.setup.chat_summary.render_world_chat", lambda wb: "自由模式世界观",
    )
    monkeypatch.setattr(
        "engine.setup.chat_summary.geography_names", lambda wb: ["废弃车站", "青云观"],
    )
    seen = {}

    async def _derive_initial_scene_state(instruction, world_summary, known_locations, call_llm):
        seen["instruction"] = instruction
        seen["world_summary"] = world_summary
        seen["known_locations"] = known_locations
        return {"description": "废弃车站"}

    monkeypatch.setattr(
        "engine.story_sandbox.graph.derive_initial_scene_state", _derive_initial_scene_state,
    )

    node = _build_init_scene_node(0, "甲乙在废弃车站重逢", _call_llm, _identity_guard_text)
    result = await node({})
    assert seen["instruction"] == "甲乙在废弃车站重逢"
    assert seen["world_summary"] == "自由模式世界观"
    assert seen["known_locations"] == ["废弃车站", "青云观"]
    assert result["initial_scene_state_this_turn"] == {"description": "废弃车站"}


@pytest.mark.asyncio
async def test_init_scene_chapter_mode_never_passes_known_locations(monkeypatch):
    from engine.story_sandbox.graph import _build_init_scene_node

    monkeypatch.setattr(
        "engine.setup.chat_summary.render_world_chat", lambda wb: "章节模式世界观",
    )
    monkeypatch.setattr(
        "engine.setup.chat_summary.geography_names", lambda wb: ["废弃车站", "青云观"],
    )
    seen = {}

    async def _derive_initial_scene_state(instruction, world_summary, known_locations, call_llm):
        seen["known_locations"] = known_locations
        return {"description": "书房"}

    monkeypatch.setattr(
        "engine.story_sandbox.graph.derive_initial_scene_state", _derive_initial_scene_state,
    )

    node = _build_init_scene_node(1, "甲乙在书房对峙", _call_llm, _identity_guard_text)
    await node({})
    assert seen["known_locations"] == []


@pytest.mark.asyncio
async def test_run_turn_uses_distinct_call_llm_per_node():
    """Regression: each call_llm_* must fire only for its own graph node — not cross-wired."""
    # Seed an opening turn first so the measured turn uses the non-opening graph (no
    # init_char/init_scene reuse of derive_* bindings, which would double those counts).
    await _drain(run_turn(
        "novel-distinct-llm", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm),
    ))

    calls: dict[str, int] = {}

    def _tracker(node: str):
        async def _c(system: str, user: str) -> str:
            calls[node] = calls.get(node, 0) + 1
            if node == "summary_fold":
                return "折叠后的摘要"
            if node == "event_extract":
                return (
                    '{"event": "甲抬起头", "time": "对峙之后", "location": "书房", '
                    '"characters": ["甲"], "entities": []}'
                )
            if node == "suggest":
                # Full target count so suggest_directions does not retry a second call.
                return '["建议一", "建议二", "建议三", "建议四"]'
            return await _call_llm(system, user)
        return _c

    async for _ in run_turn(
        "novel-distinct-llm", 1, "指令", write_turn=_write_turn,
        call_llm_derive_char=_tracker("derive_char"),
        call_llm_derive_scene=_tracker("derive_scene"),
        call_llm_summary_fold=_tracker("summary_fold"), call_llm_event_extract=_tracker("event_extract"),
        call_llm_profile_mutate=_tracker("profile_mutate"),
        call_llm_suggest=_tracker("suggest"),
        guard_text_derive_char=_identity_guard_text,
        guard_text_derive_scene=_identity_guard_text,
        guard_text_summary_fold=_identity_guard_text, guard_text_event_extract=_identity_guard_text,
        guard_text_profile_mutate=_identity_guard_text,
        guard_text_suggest=_identity_guard_text,
    ):
        pass

    assert calls.get("derive_char") == 1
    assert calls.get("derive_scene") == 1
    assert calls.get("summary_fold") == 1
    assert calls.get("event_extract") == 1
    assert calls.get("profile_mutate") == 1
    assert calls.get("suggest") == 1


@pytest.mark.asyncio
async def test_run_turn_bundles_state_and_suggestions_into_the_round():
    text, suggestions, character_states, _ = await _drain(run_turn(
        "novel-1", 1, "继续", write_turn=_write_turn, **_with_llms(_call_llm),
    ))
    assert text == "甲抬起头，看向窗外。"
    assert suggestions == ["建议一", "建议二"]
    assert character_states["甲"]["psychology"] == "逐渐大胆"

    from engine.story_sandbox.graph import peek_state
    state = await peek_state("novel-1", 1)
    assert state["character_states"] == character_states
    assert state["suggestions"] == ["建议一", "建议二"]
    round_id = state["turns"][0]["id"]
    assert isinstance(round_id, str) and round_id
    turn = state["turns"][0]
    assert turn["instruction"] == "继续"
    assert turn["prose"] == "甲抬起头，看向窗外。"
    assert turn["character_states"] == {"甲": {"psychology": "逐渐大胆"}}
    assert turn["suggestions"] == ["建议一", "建议二"]
    assert turn["initial_states"] == {"甲": {"psychology": "逐渐大胆"}}
    assert turn["scene_state"] == {"description": "昏暗的书房"}
    assert turn["initial_scene_state"] == {"description": "昏暗的书房"}
    assert turn["event_log_entries"][0]["summary"] == "甲抬起头"
    assert turn["profile_mutation"] is None
    assert turn["relationship_mutation"] is None
    assert turn["rolling_summary_after"] == "折叠后的摘要"
    assert turn["recall_context"] == ""
    assert turn["recalled_settings"] == []


@pytest.mark.asyncio
async def test_run_turn_yields_prose_then_state_then_suggestions_in_order():
    steps = [step["type"] async for step in run_turn(
        "novel-derive", 1, "继续", write_turn=_write_turn, **_with_llms(_call_llm),
    )]
    assert steps[0] == SandboxStepType.INITIAL_STATE
    assert steps[1] == SandboxStepType.PROSE
    assert steps[-1] == SandboxStepType.SUGGESTIONS
    assert set(steps) == {
        SandboxStepType.INITIAL_STATE, SandboxStepType.PROSE, SandboxStepType.STATE,
        SandboxStepType.EVENT_LOG, SandboxStepType.PROFILE_MUTATION,
        SandboxStepType.SUGGESTIONS,
    }


@pytest.mark.asyncio
async def test_run_turn_derive_state_call_happens_before_suggest_directions_call():
    call_order: list[str] = []

    async def _tracking_llm(system, _user):
        if "为每个角色推演出登场时的初始状态" in system:
            return '{"甲": {"psychology": "逐渐大胆"}}'
        if "剧情摘要助手" in system:
            return "折叠后的摘要"
        if "事件摘要助手" in system:
            return '{"event": "", "entities": []}'
        if "走向建议" in system:
            call_order.append("suggest")
            return '["建议一", "建议二", "建议三", "建议四"]'
        if "场景当前的状态" in system or "场景推演出开场时的初始状态" in system:
            return '{}'
        call_order.append("derive")
        return '{"甲": {"psychology": "逐渐大胆"}}'

    await _drain(run_turn(
        "novel-order", 1, "继续", write_turn=_write_turn, **_with_llms(_tracking_llm),
    ))
    assert call_order[-1] == "suggest", "suggest must come after all derive calls"
    assert all(c == "derive" for c in call_order[:-1]), "all calls before suggest should be derive"


@pytest.mark.asyncio
async def test_run_turn_partial_steps_survive_a_later_step_failing():
    async def _failing_llm(system, _user):
        if "初始状态" in system:
            return '{"甲": {"psychology": "外冷内热"}}'
        if "场景" in system:
            return '{}'
        if "剧情摘要助手" in system:
            raise RuntimeError("boom")
        if "事件摘要助手" in system:
            return '{"event": "", "entities": []}'
        return '{}'

    received: list[str] = []
    with pytest.raises(RuntimeError):
        async for step in run_turn(
            "novel-partial", 1, "第一轮", write_turn=_write_turn, **_with_llms(_failing_llm),
        ):
            received.append(step["type"])
    assert SandboxStepType.PROSE in received
    assert SandboxStepType.SUGGESTIONS not in received


@pytest.mark.asyncio
async def test_run_turn_keeps_full_round_history_across_many_turns():
    for i in range(3):
        await _drain(run_turn("novel-2", 1, f"指令{i}", write_turn=_write_turn, **_with_llms(_call_llm)))

    from engine.story_sandbox.graph import peek_state
    state = await peek_state("novel-2", 1)
    # Full round history must survive every round's own fold -- the history endpoint
    # reconstructs a page refresh's timeline from `turns` directly
    # (message_hub.py::story_sandbox_history), so trimming it here used to make older rounds
    # vanish/reshuffle on refresh (regression).
    assert len(state["turns"]) == 3
    assert [t["instruction"] for t in state["turns"]] == ["指令0", "指令1", "指令2"]
    assert state["rolling_summary"] == "折叠后的摘要"
    assert state["turns"][0]["character_states"] == {"甲": {"psychology": "逐渐大胆"}}
    assert state["turns"][0]["suggestions"] == ["建议一", "建议二"]


# ── resolve_cast node ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_cast_node_carries_active_cast_forward_unchanged(monkeypatch):
    monkeypatch.setattr(
        "engine.story_sandbox.cast.resolve_related_cast",
        lambda present, overlay: ["丙"] if "甲" in present else [],
    )
    from engine.story_sandbox.graph import _build_resolve_cast_node

    node = _build_resolve_cast_node(1)
    result = await node({
        "active_cast": {"甲": 1, "乙": 0}, "relationship_overlay": {}, "background_cast": [],
    })
    assert result == {
        "active_cast": {"甲": 1, "乙": 0},
        "related_cast_this_turn": ["丙"],
    }


@pytest.mark.asyncio
async def test_resolve_cast_node_excludes_already_present_names_from_related_cast(monkeypatch):
    monkeypatch.setattr(
        "engine.story_sandbox.cast.resolve_related_cast",
        lambda present, overlay: sorted(present) + ["丙"],
    )
    from engine.story_sandbox.graph import _build_resolve_cast_node

    node = _build_resolve_cast_node(1)
    result = await node({"active_cast": {"甲": 0}, "relationship_overlay": {}, "background_cast": []})
    assert result["related_cast_this_turn"] == ["丙"]


@pytest.mark.asyncio
async def test_resolve_cast_node_folds_background_cast_into_related_cast(monkeypatch):
    monkeypatch.setattr("engine.story_sandbox.cast.resolve_related_cast", lambda present, overlay: [])
    from engine.story_sandbox.graph import _build_resolve_cast_node

    node = _build_resolve_cast_node(1)
    result = await node({
        "active_cast": {"甲": 0}, "relationship_overlay": {}, "background_cast": ["丁", "甲"],
    })
    assert result["related_cast_this_turn"] == ["丁"]


@pytest.mark.asyncio
async def test_resolve_cast_opening_node_folds_initial_states_into_active_cast(monkeypatch):
    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: [])
    monkeypatch.setattr("engine.story_sandbox.cast.resolve_related_cast", lambda present, overlay: [])
    from engine.story_sandbox.graph import _build_resolve_cast_opening_node

    node = _build_resolve_cast_opening_node(1, "开场")
    result = await node({
        "initial_states_this_turn": {"甲": {"psychology": "困惑"}},
        "turns": [], "active_cast": {}, "relationship_overlay": {},
    })
    assert result["active_cast"] == {"甲": 0}
    assert result["related_cast_this_turn"] == []


@pytest.mark.asyncio
async def test_resolve_cast_rewrite_node_carries_active_cast_forward_unchanged(monkeypatch):
    monkeypatch.setattr("engine.story_sandbox.cast.resolve_related_cast", lambda present, overlay: [])
    from engine.story_sandbox.graph import _build_resolve_cast_rewrite_node

    node = _build_resolve_cast_rewrite_node(1)
    result = await node({"active_cast": {"甲": 0}, "relationship_overlay": {}, "background_cast": []})
    assert result == {"active_cast": {"甲": 0}, "related_cast_this_turn": []}


@pytest.mark.asyncio
async def test_resolve_cast_node_logs_perf_timing(monkeypatch):
    from loguru import logger

    monkeypatch.setattr("engine.story_sandbox.cast.resolve_related_cast", lambda present, overlay: [])
    from engine.story_sandbox.graph import _build_resolve_cast_node

    captured: list[str] = []
    sink_id = logger.add(lambda m: captured.append(str(m)), level="INFO")
    try:
        node = _build_resolve_cast_node(1)
        await node({"active_cast": {}, "relationship_overlay": {}, "background_cast": []})
    finally:
        logger.remove(sink_id)
    assert any("resolve_cast" in m and "COMPLETED" in m for m in captured)


@pytest.mark.asyncio
async def test_derive_char_node_present_names_get_closed_set_state_update(monkeypatch):
    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: ["甲"])
    monkeypatch.setattr("engine.memory_recall.entity_index.build_character_vocab", lambda: {"甲"})

    async def call_identify(_system, _user):
        return '{"角色": ["甲"], "路人": []}'

    async def call_derive(_system, user):
        assert "甲" in user
        return '{"甲": {"psychology": "警惕"}}'

    from engine.story_sandbox.graph import _build_derive_char_node

    node = _build_derive_char_node(1, call_derive, call_identify, guard_text=_identity_guard_text)
    result = await node({
        "final_text": "甲挥了挥手", "baseline_states": {"甲": {"psychology": "平静"}},
        "active_cast": {}, "turns": [],
    })
    assert result["character_states"] == {"甲": {"psychology": "警惕"}}
    assert result["active_cast"] == {"甲": 0}
    assert result["passerby_names"] == []
    assert result["background_cast"] == []


@pytest.mark.asyncio
async def test_derive_char_node_classifies_non_vocab_names_as_passerby(monkeypatch):
    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: [])
    monkeypatch.setattr("engine.memory_recall.entity_index.build_character_vocab", lambda: {"高木柔柔"})
    monkeypatch.setattr(
        "engine.story_sandbox.cast.resolve_character_cards",
        lambda chapter, names: [{"name": n, "card": f"【{n}】"} for n in names],
    )

    async def call_identify(_system, _user):
        return '{"角色": [], "路人": ["路边大爷"]}'

    async def call_derive(_system, _user):
        return '{"路边大爷": {"psychology": "麻木"}}'

    from engine.story_sandbox.graph import _build_derive_char_node

    node = _build_derive_char_node(1, call_derive, call_identify, guard_text=_identity_guard_text)
    result = await node({
        "final_text": "一个卖菜大爷", "baseline_states": {}, "active_cast": {}, "turns": [],
    })
    assert result["passerby_names"] == ["路边大爷"]
    assert result["character_states"] == {"路边大爷": {"psychology": "麻木"}}


@pytest.mark.asyncio
async def test_derive_char_node_drops_passerby_that_aged_out_of_active_cast(monkeypatch):
    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: [])
    monkeypatch.setattr("engine.memory_recall.entity_index.build_character_vocab", lambda: set())

    async def call_identify(_system, _user):
        return '{"角色": [], "路人": []}'

    async def call_derive(_system, _user):
        raise AssertionError("no one present, should not be called")

    from engine.story_sandbox.graph import _build_derive_char_node

    node = _build_derive_char_node(1, call_derive, call_identify, guard_text=_identity_guard_text)
    result = await node({
        "final_text": "空荡荡的房间", "baseline_states": {}, "active_cast": {"路人甲": 0}, "turns": [{}, {}, {}],
    })
    assert "路人甲" not in result["active_cast"]
    assert result["passerby_names"] == []


@pytest.mark.asyncio
async def test_derive_char_node_ac_hit_not_confirmed_present_becomes_background_cast(monkeypatch):
    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: ["张三", "甲"])
    monkeypatch.setattr("engine.memory_recall.entity_index.build_character_vocab", lambda: {"张三", "甲"})

    async def call_identify(_system, _user):
        return '{"角色": ["甲"], "路人": []}'

    async def call_derive(_system, _user):
        return '{"甲": {"psychology": "警惕"}}'

    from engine.story_sandbox.graph import _build_derive_char_node

    node = _build_derive_char_node(1, call_derive, call_identify, guard_text=_identity_guard_text)
    result = await node({
        "final_text": "他想起小时候欺负过他的张三，甲挥了挥手",
        "baseline_states": {"甲": {}}, "active_cast": {}, "turns": [],
    })
    assert "张三" not in result["character_states"]
    assert "张三" not in result["active_cast"]
    assert result["background_cast"] == ["张三"]


@pytest.mark.asyncio
async def test_derive_char_node_has_baseline_miss_carries_forward_without_llm_call(monkeypatch):
    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: [])
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.build_character_vocab", lambda: {"甲", "乙"},
    )

    async def call_identify(_system, _user):
        return '{"角色": ["甲", "乙"], "路人": []}'

    async def call_derive(_system, _user):
        return '{"甲": {"psychology": "警惕"}}'

    from engine.story_sandbox.graph import _build_derive_char_node

    node = _build_derive_char_node(1, call_derive, call_identify, guard_text=_identity_guard_text)
    result = await node({
        "final_text": "甲乙同框", "active_cast": {},
        "baseline_states": {"甲": {"psychology": "平静"}, "乙": {"psychology": "冷漠"}},
        "turns": [],
    })
    assert result["character_states"]["甲"] == {"psychology": "警惕"}
    assert result["character_states"]["乙"] == {"psychology": "冷漠"}


@pytest.mark.asyncio
async def test_derive_char_node_no_baseline_miss_triggers_one_narrow_retry(monkeypatch):
    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: [])
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.build_character_vocab", lambda: {"新人甲", "新人乙"},
    )
    monkeypatch.setattr(
        "engine.story_sandbox.cast.resolve_character_cards",
        lambda chapter, names: [{"name": n, "card": f"【{n}】"} for n in names],
    )

    async def call_identify(_system, _user):
        return '{"角色": ["新人甲", "新人乙"], "路人": []}'

    calls = {"n": 0}

    async def call_derive(_system, user):
        calls["n"] += 1
        if calls["n"] == 1:
            assert "新人甲" in user and "新人乙" in user
            return '{"新人甲": {"psychology": "紧张"}}'
        assert "新人乙" in user and "新人甲" not in user
        return '{"新人乙": {"psychology": "好奇"}}'

    from engine.story_sandbox.graph import _build_derive_char_node

    node = _build_derive_char_node(1, call_derive, call_identify, guard_text=_identity_guard_text)
    result = await node({
        "final_text": "两个新角色登场", "baseline_states": {}, "active_cast": {}, "turns": [],
    })
    assert calls["n"] == 2
    assert result["character_states"]["新人甲"] == {"psychology": "紧张"}
    assert result["character_states"]["新人乙"] == {"psychology": "好奇"}


@pytest.mark.asyncio
async def test_derive_char_node_empty_roster_degrades_to_ac_scan_as_present(monkeypatch):
    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: ["甲"])
    monkeypatch.setattr("engine.memory_recall.entity_index.build_character_vocab", lambda: set())

    async def call_identify(_system, _user):
        raise AssertionError("roster empty, identify must not be called")

    async def call_derive(_system, user):
        return '{"甲": {"psychology": "警惕"}}'

    from engine.story_sandbox.graph import _build_derive_char_node

    node = _build_derive_char_node(1, call_derive, call_identify, guard_text=_identity_guard_text)
    result = await node({
        "final_text": "甲登场", "baseline_states": {"甲": {}}, "active_cast": {}, "turns": [],
    })
    assert result["active_cast"] == {"甲": 0}
    assert result["background_cast"] == []


# ── dialogue_draft node ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dialogue_draft_node_skips_when_call_llm_is_none():
    from engine.story_sandbox.graph import _build_dialogue_draft_node

    node = _build_dialogue_draft_node(1, "继续", None)
    result = await node({"turns": [], "character_states": {}, "active_cast": {"甲": 0}})
    assert result == {"dialogue_draft_this_turn": ""}


@pytest.mark.asyncio
async def test_dialogue_draft_node_skips_when_no_roster(monkeypatch):
    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: [])
    from engine.story_sandbox.graph import _build_dialogue_draft_node

    calls = []

    async def _llm(_system, _user):
        calls.append(1)
        return "不该被调用"

    node = _build_dialogue_draft_node(1, "继续", _llm)
    result = await node({"turns": [], "character_states": {}, "active_cast": {}})
    assert result == {"dialogue_draft_this_turn": ""}
    assert calls == []


@pytest.mark.asyncio
async def test_dialogue_draft_node_calls_llm_with_resolved_cards(monkeypatch):
    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: [])
    monkeypatch.setattr(
        "engine.story_sandbox.cast.resolve_character_cards",
        lambda chapter, names: [{"name": n, "card": f"角色：{n}"} for n in names],
    )
    from engine.story_sandbox.graph import _build_dialogue_draft_node

    seen = {}

    async def _llm(system, user):
        seen["system"] = system
        seen["user"] = user
        return "甲：你来了。"

    node = _build_dialogue_draft_node(1, "去质问甲", _llm)
    result = await node({
        "turns": [], "character_states": {"甲": {"psychology": "紧张"}}, "active_cast": {"甲": 0},
    })
    assert result == {"dialogue_draft_this_turn": "甲：你来了。"}
    assert "角色：甲" in seen["system"]
    assert "紧张" in seen["system"]
    assert "去质问甲" in seen["user"]


@pytest.mark.asyncio
async def test_dialogue_draft_node_defaults_turn_count_to_present_plus_one(monkeypatch):
    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: [])
    monkeypatch.setattr(
        "engine.story_sandbox.cast.resolve_character_cards",
        lambda chapter, names: [{"name": n, "card": f"角色：{n}"} for n in names],
    )
    monkeypatch.setattr("api.services.novels.get_sandbox_dialogue_turn_count", lambda nid: None)
    from engine.story_sandbox.graph import _build_dialogue_draft_node

    seen = {}

    async def _llm(system, _user):
        seen["system"] = system
        return ""

    node = _build_dialogue_draft_node(1, "继续", _llm)
    await node({
        "turns": [], "character_states": {}, "active_cast": {"甲": 0, "乙": 0, "丙": 0},
    })
    # 3 present + 1 = 4, deliberately not equal to draft_dialogue's default of 3,
    # so this test can't pass before the node is wired.
    assert "目标写出约 4 行台词" in seen["system"]


@pytest.mark.asyncio
async def test_dialogue_draft_node_uses_configured_turn_count(monkeypatch):
    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: [])
    monkeypatch.setattr(
        "engine.story_sandbox.cast.resolve_character_cards",
        lambda chapter, names: [{"name": n, "card": f"角色：{n}"} for n in names],
    )
    monkeypatch.setattr("api.services.novels.get_sandbox_dialogue_turn_count", lambda nid: 8)
    from engine.story_sandbox.graph import _build_dialogue_draft_node

    seen = {}

    async def _llm(system, _user):
        seen["system"] = system
        return ""

    node = _build_dialogue_draft_node(1, "继续", _llm)
    await node({"turns": [], "character_states": {}, "active_cast": {"甲": 0}})
    assert "目标写出约 8 行台词" in seen["system"]  # configured value takes priority over "1 present + 1"


@pytest.mark.asyncio
async def test_dialogue_draft_opening_node_uses_initial_states_for_roster(monkeypatch):
    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: [])
    monkeypatch.setattr(
        "engine.story_sandbox.cast.resolve_character_cards",
        lambda chapter, names: [{"name": n, "card": f"角色：{n}"} for n in names],
    )
    from engine.story_sandbox.graph import _build_dialogue_draft_opening_node

    seen = {}

    async def _llm(system, _user):
        seen["system"] = system
        return "甲：这里是哪？"

    node = _build_dialogue_draft_opening_node(1, "开场", _llm)
    result = await node({
        "initial_states_this_turn": {"甲": {"psychology": "困惑"}},
        "active_cast": {"甲": 0},
    })
    assert result == {"dialogue_draft_this_turn": "甲：这里是哪？"}
    assert "角色：甲" in seen["system"]


@pytest.mark.asyncio
async def test_dialogue_draft_opening_node_defaults_turn_count_to_present_plus_one(monkeypatch):
    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: [])
    monkeypatch.setattr(
        "engine.story_sandbox.cast.resolve_character_cards",
        lambda chapter, names: [{"name": n, "card": f"角色：{n}"} for n in names],
    )
    monkeypatch.setattr("api.services.novels.get_sandbox_dialogue_turn_count", lambda nid: None)
    from engine.story_sandbox.graph import _build_dialogue_draft_opening_node

    seen = {}

    async def _llm(system, _user):
        seen["system"] = system
        return ""

    node = _build_dialogue_draft_opening_node(1, "开场", _llm)
    await node({
        "initial_states_this_turn": {"甲": {"psychology": "困惑"}},
        "active_cast": {"甲": 0},
    })
    assert "目标写出约 2 行台词" in seen["system"]  # 1 present + 1


@pytest.mark.asyncio
async def test_dialogue_draft_rewrite_node_uses_baseline_states_from_previous_round(monkeypatch):
    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: [])
    monkeypatch.setattr(
        "engine.story_sandbox.cast.resolve_character_cards",
        lambda chapter, names: [{"name": n, "card": f"角色：{n}"} for n in names],
    )
    from engine.story_sandbox.graph import _build_dialogue_draft_rewrite_node

    seen = {}

    async def _llm(system, user):
        seen["system"] = system
        seen["user"] = user
        return "甲：（冷笑）你还敢来。"

    node = _build_dialogue_draft_rewrite_node(1, _llm)
    state = {
        "turns": [{
            "instruction": "甲质问乙", "prose": "甲皱眉。",
            "character_states": {"甲": {"psychology": "愤怒"}},
            "initial_states": None,
        }],
        "active_cast": {"甲": 0},
    }
    result = await node(state)
    assert result == {"dialogue_draft_this_turn": "甲：（冷笑）你还敢来。"}
    assert "甲质问乙" in seen["user"]
    assert "愤怒" in seen["system"]


@pytest.mark.asyncio
async def test_dialogue_draft_rewrite_node_defaults_turn_count_to_present_plus_one(monkeypatch):
    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: [])
    monkeypatch.setattr(
        "engine.story_sandbox.cast.resolve_character_cards",
        lambda chapter, names: [{"name": n, "card": f"角色：{n}"} for n in names],
    )
    monkeypatch.setattr("api.services.novels.get_sandbox_dialogue_turn_count", lambda nid: None)
    from engine.story_sandbox.graph import _build_dialogue_draft_rewrite_node

    seen = {}

    async def _llm(system, _user):
        seen["system"] = system
        return ""

    node = _build_dialogue_draft_rewrite_node(1, _llm)
    state = {
        "turns": [{
            "instruction": "甲质问乙", "prose": "甲皱眉。",
            "character_states": {"甲": {"psychology": "愤怒"}},
            "initial_states": None,
        }],
        "active_cast": {"甲": 0},
    }
    await node(state)
    assert "目标写出约 2 行台词" in seen["system"]  # 1 present + 1


@pytest.mark.asyncio
async def test_dialogue_draft_feeds_into_prose_system_prompt_on_non_opening_turn():
    # Seed an opening turn first so the measured turn uses the non-opening graph.
    await _drain(run_turn(
        "novel-dialogue-draft", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm),
    ))

    seen_system = {}

    async def _capture_write_turn(system: str, _packet: str) -> str:
        seen_system["system"] = system
        return "甲抬起头，看向窗外。"

    async def _dialogue_draft_llm(_system, _user):
        return "甲：（皱眉）你又来了。"

    await _drain(run_turn(
        "novel-dialogue-draft", 1, "继续", write_turn=_capture_write_turn,
        **_with_llms(_call_llm), call_llm_dialogue_draft=_dialogue_draft_llm,
    ))
    assert "甲：（皱眉）你又来了。" in seen_system["system"]


@pytest.mark.asyncio
async def test_dialogue_draft_feeds_into_prose_system_prompt_on_opening_turn():
    seen_system = {}

    async def _capture_write_turn(system: str, _packet: str) -> str:
        seen_system["system"] = system
        return "正文"

    async def _dialogue_draft_llm(_system, _user):
        return "甲：（自言自语）这里是哪？"

    await _drain(run_turn(
        "novel-dialogue-draft-opening", 1, "开场", write_turn=_capture_write_turn,
        **_with_llms(_call_llm), call_llm_dialogue_draft=_dialogue_draft_llm,
    ))
    assert "甲：（自言自语）这里是哪？" in seen_system["system"]


@pytest.mark.asyncio
async def test_known_roster_fallback_feeds_into_prose_system_prompt_on_free_mode_opening_turn(
    monkeypatch,
):
    monkeypatch.setattr(
        "engine.story_sandbox.cast_identify.resolve_present_roster",
        _make_identify_stub([]),
    )
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.build_character_vocab", lambda: {"甲", "乙"},
    )
    monkeypatch.setattr("engine.setup.chat_summary.render_world_chat", lambda wb: "")

    seen_system = {}

    async def _capture_write_turn(system: str, _packet: str) -> str:
        seen_system["system"] = system
        return "正文"

    await _drain(run_turn(
        "novel-known-roster-fallback", 0, "随便写个开场", write_turn=_capture_write_turn,
        **_with_llms(_call_llm),
    ))
    assert "known_roster_fallback" in seen_system["system"]
    assert "甲" in seen_system["system"] and "乙" in seen_system["system"]


@pytest.mark.asyncio
async def test_instruction_grounding_feeds_graph_and_briefs_on_roster_fallback_opening(
    monkeypatch,
):
    monkeypatch.setattr(
        "engine.story_sandbox.cast_identify.resolve_present_roster",
        _make_identify_stub([]),
    )
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.build_character_vocab", lambda: {"甲", "乙", "丙"},
    )
    monkeypatch.setattr("engine.story_sandbox.cast._protagonist_names", lambda: {"甲"})
    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {"g0": {"members": ["甲", "乙", "丙"], "type": "家人", "priority": 1}},
                 "edges": {}},
    )
    monkeypatch.setattr("engine.setup.chat_summary.render_world_chat", lambda wb: "")
    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.cards.render_related_character_brief",
        lambda name, chapter, stage, **kw: f"【{name}】简卡",
    )

    seen_system = {}

    async def _capture_write_turn(system: str, _packet: str) -> str:
        seen_system["system"] = system
        return "正文"

    await _drain(run_turn(
        "novel-instruction-grounding", 0, "描述主角一家的日常生活",
        write_turn=_capture_write_turn, **_with_llms(_call_llm),
    ))
    system = seen_system["system"]
    assert "known_roster_fallback" in system
    assert "instruction_grounding_graph" in system
    assert "instruction_grounding_briefs" in system
    assert "关联角色简卡" in system
    assert "【甲】简卡" in system and "【乙】简卡" in system


@pytest.mark.asyncio
async def test_run_turn_folds_every_round_with_its_own_text():
    fold_calls: list[str] = []

    async def _counting_llm(system: str, user: str) -> str:
        if "剧情摘要助手" in system:
            fold_calls.append(user)
            return "折叠后的摘要"
        if "事件摘要助手" in system:
            return '{"event": "甲事件", "entities": []}'
        return await _call_llm(system, user)

    for i in range(4):
        await _drain(run_turn("novel-3", 1, f"指令{i}", write_turn=_write_turn, **_with_llms(_counting_llm)))

    from engine.story_sandbox.graph import peek_state
    state = await peek_state("novel-3", 1)
    assert len(state["turns"]) == 4
    assert len(fold_calls) == 4
    for i, call in enumerate(fold_calls):
        assert f"指令{i}" in call
        for j in range(4):
            if j != i:
                assert f"指令{j}" not in call


@pytest.mark.asyncio
async def test_run_turn_attaches_event_log_entry_directly_to_its_own_round():
    """No more retroactive splice -- the entry shows up on turns[0] after just one turn, not
    delayed until a later round ages it out of the verbatim window."""
    async def _event_llm(system: str, user: str) -> str:
        if "剧情摘要助手" in system:
            return "新摘要"
        if "事件摘要助手" in system:
            return '{"event": "甲发现了玉佩", "time": "指令0之后", "entities": ["甲"]}'
        return await _call_llm(system, user)

    await _drain(run_turn(
        "novel-event-persist", 1, "指令0", write_turn=_write_turn, **_with_llms(_event_llm),
    ))

    from engine.story_sandbox.graph import peek_state
    state = await peek_state("novel-event-persist", 1)
    entry = state["turns"][0]["event_log_entries"][0]
    assert entry["summary"] == "甲发现了玉佩"
    assert entry["time"] == "指令0之后"
    assert entry["turn_index"] == 0


@pytest.mark.asyncio
async def test_run_turn_event_log_step_yields_once_with_merged_pair():
    async def call_llm_summary_fold(system: str, user: str) -> str:
        return "来自 summary_fold 的摘要"

    async def call_llm_event_extract(system: str, user: str) -> str:
        return '{"event": "来自 event_extract 的事件", "time": "之后", "entities": ["甲"]}'

    steps = [step async for step in run_turn(
        "novel-event-merge", 1, "指令0", write_turn=_write_turn,
        call_llm_derive_char=_call_llm, call_llm_derive_scene=_call_llm,
        call_llm_summary_fold=call_llm_summary_fold, call_llm_event_extract=call_llm_event_extract,
        call_llm_profile_mutate=_call_llm, call_llm_suggest=_call_llm,
        guard_text_derive_char=_identity_guard_text, guard_text_derive_scene=_identity_guard_text,
        guard_text_summary_fold=_identity_guard_text, guard_text_event_extract=_identity_guard_text,
        guard_text_profile_mutate=_identity_guard_text, guard_text_suggest=_identity_guard_text,
    )]
    event_steps = [s for s in steps if s["type"] == SandboxStepType.EVENT_LOG]
    assert len(event_steps) == 1
    assert event_steps[0]["rolling_summary"] == "来自 summary_fold 的摘要"
    assert event_steps[0]["entries"][0]["summary"] == "来自 event_extract 的事件"


@pytest.mark.asyncio
async def test_run_turn_suggest_uses_summary_fold_rolling_summary_after():
    async def call_llm_summary_fold(system: str, user: str) -> str:
        return "summary_fold 产出"

    async def call_llm_event_extract(system: str, user: str) -> str:
        return '{"event": "某事件", "entities": []}'

    await _drain(run_turn(
        "novel-summary-after", 1, "指令0", write_turn=_write_turn,
        call_llm_derive_char=_call_llm, call_llm_derive_scene=_call_llm,
        call_llm_summary_fold=call_llm_summary_fold, call_llm_event_extract=call_llm_event_extract,
        call_llm_profile_mutate=_call_llm, call_llm_suggest=_call_llm,
        guard_text_derive_char=_identity_guard_text, guard_text_derive_scene=_identity_guard_text,
        guard_text_summary_fold=_identity_guard_text, guard_text_event_extract=_identity_guard_text,
        guard_text_profile_mutate=_identity_guard_text, guard_text_suggest=_identity_guard_text,
    ))

    from engine.story_sandbox.graph import peek_state
    state = await peek_state("novel-summary-after", 1)
    assert state["turns"][0]["rolling_summary_after"] == "summary_fold 产出"
    assert state["rolling_summary"] == "summary_fold 产出"


@pytest.mark.asyncio
async def test_reset_chapter_restores_fresh_seed_after_several_turns():
    from engine.story_sandbox.graph import peek_state, reset_chapter

    for i in range(3):
        await _drain(run_turn("novel-4", 1, f"指令{i}", write_turn=_write_turn, **_with_llms(_call_llm)))
    mid_state = await peek_state("novel-4", 1)
    assert mid_state["turns"] != []

    await reset_chapter("novel-4", 1)
    reset_state = await peek_state("novel-4", 1)
    assert reset_state == {
        "turns": [], "rolling_summary": "", "suggestions": [],
        "character_states": {"甲": {"psychology": "内向"}},
        "scene_state": {}, "character_profile": {}, "recall_cooldown": {}, "active_cast": {},
        "relationship_overlay": {}, "background_cast": [],
    }


@pytest.mark.asyncio
async def test_reset_chapter_does_not_affect_other_chapters():
    from engine.story_sandbox.graph import peek_state, reset_chapter

    await _drain(run_turn("novel-5", 1, "第一章的指令", write_turn=_write_turn, **_with_llms(_call_llm)))
    await _drain(run_turn("novel-5", 2, "第二章的指令", write_turn=_write_turn, **_with_llms(_call_llm)))

    await reset_chapter("novel-5", 1)

    ch1 = await peek_state("novel-5", 1)
    ch2 = await peek_state("novel-5", 2)
    assert ch1["turns"] == []
    assert ch2["turns"][0]["instruction"] == "第二章的指令"


@pytest.mark.asyncio
async def test_reset_chapter_clears_persisted_memory_for_that_chapter_only(monkeypatch):
    from engine.story_sandbox.graph import reset_chapter

    deleted_chapters: list[tuple[int, str]] = []
    deleted_vector_chapters: list[tuple[int, str]] = []

    async def _fake_delete_entries(chapter, branch_id=None):
        deleted_chapters.append((chapter, branch_id))

    async def _fake_delete_chapter(chapter, branch_id=None):
        deleted_vector_chapters.append((chapter, branch_id))

    monkeypatch.setattr(
        "engine.story_sandbox.graph.delete_entries_for_chapter",
        _fake_delete_entries,
    )
    monkeypatch.setattr(
        "engine.story_sandbox.graph.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"delete_chapter": staticmethod(_fake_delete_chapter)})(),
    )

    await reset_chapter("novel-6", 3)
    await g.wait_for_pending_sandbox_cleanup()

    assert deleted_chapters == [(3, LEGACY_BRANCH_ID)]
    assert deleted_vector_chapters == [(3, LEGACY_BRANCH_ID)]


@pytest.mark.asyncio
async def test_peek_state_on_brand_new_thread_returns_seed():
    from engine.story_sandbox.graph import peek_state
    state = await peek_state("novel-3", 1)
    assert state["turns"] == []
    assert state["suggestions"] == []
    assert state["character_states"] == {"甲": {"psychology": "内向"}}


@pytest.mark.asyncio
async def test_regenerate_suggestions_overwrites_only_the_last_round():
    from engine.story_sandbox.graph import peek_state, regenerate_suggestions

    await _drain(run_turn("novel-6", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))
    await _drain(run_turn("novel-6", 1, "第二轮", write_turn=_write_turn, **_with_llms(_call_llm)))

    async def _new_suggest_llm(system, _user):
        if "走向建议" in system:
            return '["新建议A", "新建议B"]'
        return '{"甲": {"psychology": "逐渐大胆"}}'

    new_suggestions = await regenerate_suggestions(
        "novel-6", 1, _new_suggest_llm, guard_text=_identity_guard_text,
    )
    assert new_suggestions == ["新建议A", "新建议B"]

    state = await peek_state("novel-6", 1)
    assert state["turns"][0]["suggestions"] == ["建议一", "建议二"]
    assert state["turns"][1]["suggestions"] == ["新建议A", "新建议B"]
    assert state["suggestions"] == ["新建议A", "新建议B"]


@pytest.mark.asyncio
async def test_rewrite_profile_mutation_overwrites_last_round_mutations():
    from engine.story_sandbox.graph import peek_state, rewrite_profile_mutation

    await _drain(run_turn("novel-pm-rewrite", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))

    async def _mutate_llm(_system, _user):
        return '{"甲": {"race": "恶魔"}}'

    profile_mutation, relationship_mutation, round_index = await rewrite_profile_mutation(
        "novel-pm-rewrite", 1, "将种族修正为恶魔",
        call_llm_profile_mutate=_mutate_llm, guard_text=_identity_guard_text,
    )
    assert round_index == 0
    assert profile_mutation == {"甲": {"race": "恶魔"}}
    assert relationship_mutation is None

    state = await peek_state("novel-pm-rewrite", 1)
    assert state["turns"][-1]["profile_mutation"] == {"甲": {"race": "恶魔"}}


@pytest.mark.asyncio
async def test_regenerate_suggestions_returns_empty_list_with_no_rounds():
    from engine.story_sandbox.graph import regenerate_suggestions

    result = await regenerate_suggestions("novel-7", 1, _call_llm, guard_text=_identity_guard_text)
    assert result == []


@pytest.mark.asyncio
async def test_regenerate_suggestions_forwards_hint_to_suggest_directions():
    from engine.story_sandbox.graph import regenerate_suggestions

    await _drain(run_turn("novel-8", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))

    seen = {}

    async def _hint_aware_llm(system, user):
        if "走向建议" in system:
            seen["user"] = user
            return '["新建议A"]'
        return '{"甲": {"psychology": "逐渐大胆"}}'

    await regenerate_suggestions(
        "novel-8", 1, _hint_aware_llm, hint="往乙这边的反应上靠一点",
        guard_text=_identity_guard_text,
    )
    assert "往乙这边的反应上靠一点" in seen["user"]


@pytest.mark.asyncio
async def test_regenerate_suggestions_runs_fresh_recall_with_hint_and_prose(monkeypatch):
    from engine.story_sandbox.graph import peek_state, regenerate_suggestions

    recall_calls: list[dict] = []

    def spy_recall(text, **kwargs):
        recall_calls.append({"text": text, **kwargs})
        return (
            "## 相关历史/设定回收\n- 设定条目", {},
            [{"category": "races", "name": "人族", "desc": "凡躯"}],
        )

    monkeypatch.setattr("engine.memory_recall.recall.recall_relevant_context", spy_recall)

    await _drain(run_turn(
        "novel-regen-recall", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm),
    ))
    recall_calls.clear()

    async def _suggest_llm(system, user):
        if "走向建议" in system:
            assert "## 相关历史/设定回收" in system
            return '["新建议A"]'
        return '{"甲": {"psychology": "逐渐大胆"}}'

    await regenerate_suggestions(
        "novel-regen-recall", 1, _suggest_llm, hint="往元气体系上靠",
        guard_text=_identity_guard_text,
    )
    assert len(recall_calls) == 1
    assert "第一轮" in recall_calls[0]["text"]
    assert "往元气体系上靠" in recall_calls[0]["text"]
    assert "甲抬起头" in recall_calls[0]["text"]
    assert recall_calls[0]["turn_index"] == 0

    state = await peek_state("novel-regen-recall", 1)
    assert "## 相关历史/设定回收" in state["turns"][-1]["recall_context"]
    assert state["turns"][-1]["recalled_settings"] == [
        {"category": "races", "name": "人族", "desc": "凡躯"},
    ]


@pytest.mark.asyncio
async def test_rewrite_profile_mutation_runs_fresh_recall_with_feedback(monkeypatch):
    from engine.story_sandbox.graph import rewrite_profile_mutation

    recall_calls: list[dict] = []
    llm_users: list[str] = []

    def spy_recall(text, **kwargs):
        recall_calls.append({"text": text, **kwargs})
        return "## 相关历史/设定回收\n- 设定条目", {}, []

    monkeypatch.setattr("engine.memory_recall.recall.recall_relevant_context", spy_recall)

    await _drain(run_turn(
        "novel-pm-recall", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm),
    ))
    recall_calls.clear()

    async def _mutate_llm(_system, user):
        llm_users.append(user)
        return '{"甲": {"race": "恶魔"}}'

    await rewrite_profile_mutation(
        "novel-pm-recall", 1, "结合元气设定修正种族",
        call_llm_profile_mutate=_mutate_llm, guard_text=_identity_guard_text,
    )
    assert len(recall_calls) == 1
    assert "结合元气设定修正种族" in recall_calls[0]["text"]
    assert "## 相关历史/设定回收" in llm_users[0]


@pytest.mark.asyncio
async def test_rewrite_selection_splices_replacement_into_prose_and_persists():
    from engine.story_sandbox.graph import peek_state, rewrite_selection

    await _drain(run_turn("novel-sel-1", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))
    # _write_turn always returns "甲抬起头，看向窗外。" -- rewrite the "看向窗外" fragment.

    async def _sel_llm(_system: str, _user: str) -> str:
        return "望向远方"

    new_prose = await rewrite_selection(
        "novel-sel-1", 1, "看向窗外", 0, "",
        call_llm=_sel_llm, guard_text=_identity_guard_text,
    )
    assert new_prose == "甲抬起头，望向远方。"

    state = await peek_state("novel-sel-1", 1)
    assert state["turns"][0]["prose"] == "甲抬起头，望向远方。"
    assert state["turns"][0]["instruction"] == "第一轮"


@pytest.mark.asyncio
async def test_rewrite_selection_strips_preamble_before_the_output_marker():
    """A model that ignores the "no preamble" instruction and still wraps its answer in
    out-of-character chatter ("好的，这是根据您的要求重写后的段落：") must not leak that chatter
    into the persisted prose -- only the text after `【修改后的片段】：` should survive."""
    from engine.story_sandbox.graph import peek_state, rewrite_selection

    await _drain(run_turn("novel-sel-11", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))

    async def _sel_llm(_system: str, _user: str) -> str:
        return "好的，这是根据您的要求重写后的段落：\n【修改后的片段】：望向远方"

    new_prose = await rewrite_selection(
        "novel-sel-11", 1, "看向窗外", 0, "",
        call_llm=_sel_llm, guard_text=_identity_guard_text,
    )
    assert new_prose == "甲抬起头，望向远方。"

    state = await peek_state("novel-sel-11", 1)
    assert state["turns"][0]["prose"] == "甲抬起头，望向远方。"


@pytest.mark.asyncio
async def test_rewrite_selection_does_not_touch_earlier_rounds():
    from engine.story_sandbox.graph import peek_state, rewrite_selection

    await _drain(run_turn("novel-sel-3", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))

    async def _second_write_turn(_system: str, _packet: str) -> str:
        return "乙站起身，走向门口。"

    await _drain(run_turn(
        "novel-sel-3", 1, "第二轮", write_turn=_second_write_turn, **_with_llms(_call_llm),
    ))

    async def _sel_llm(_system: str, _user: str) -> str:
        return "望向远方"

    await rewrite_selection(
        "novel-sel-3", 1, "走向门口", 0, "",
        call_llm=_sel_llm, guard_text=_identity_guard_text,
    )

    state = await peek_state("novel-sel-3", 1)
    assert state["turns"][0]["prose"] == "甲抬起头，看向窗外。"  # untouched
    assert state["turns"][1]["prose"] == "乙站起身，望向远方。"


@pytest.mark.asyncio
async def test_rewrite_selection_raises_when_no_rounds_exist():
    from engine.story_sandbox.graph import rewrite_selection

    async def _sel_llm(_system: str, _user: str) -> str:
        return "不会被调用"

    with pytest.raises(ValueError):
        await rewrite_selection(
            "novel-sel-4", 1, "任意文字", 0, "",
            call_llm=_sel_llm, guard_text=_identity_guard_text,
        )


@pytest.mark.asyncio
async def test_rewrite_selection_raises_when_text_not_found_and_leaves_prose_untouched():
    from engine.story_sandbox.graph import peek_state, rewrite_selection

    await _drain(run_turn("novel-sel-5", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))

    async def _sel_llm(_system: str, _user: str) -> str:
        return "不会被调用"

    with pytest.raises(ValueError):
        await rewrite_selection(
            "novel-sel-5", 1, "根本不存在的文字", 0, "",
            call_llm=_sel_llm, guard_text=_identity_guard_text,
        )

    state = await peek_state("novel-sel-5", 1)
    assert state["turns"][0]["prose"] == "甲抬起头，看向窗外。"


@pytest.mark.asyncio
async def test_rewrite_selection_passes_replacement_through_guard_text():
    from engine.story_sandbox.graph import peek_state, rewrite_selection

    await _drain(run_turn("novel-sel-6", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))

    async def _sel_llm(_system: str, _user: str) -> str:
        return f"望向{FORBIDDEN}"

    await rewrite_selection(
        "novel-sel-6", 1, "看向窗外", 0, "",
        call_llm=_sel_llm, guard_text=_replace_forbidden_guard,
    )

    state = await peek_state("novel-sel-6", 1)
    assert state["turns"][0]["prose"] == f"甲抬起头，望向{REPLACEMENT}。"


@pytest.mark.asyncio
async def test_run_turn_assigns_a_stable_id_to_each_new_round():
    from engine.story_sandbox.graph import peek_state

    await _drain(run_turn("novel-sel-7", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))

    async def _second_write_turn(_system: str, _packet: str) -> str:
        return "乙站起身，走向门口。"

    await _drain(run_turn(
        "novel-sel-7", 1, "第二轮", write_turn=_second_write_turn, **_with_llms(_call_llm),
    ))

    state = await peek_state("novel-sel-7", 1)
    assert state["turns"][0]["id"]
    assert state["turns"][1]["id"]
    assert state["turns"][0]["id"] != state["turns"][1]["id"]


@pytest.mark.asyncio
async def test_rewrite_selection_targets_round_by_id_even_when_it_is_not_the_last_round():
    from engine.story_sandbox.graph import peek_state, rewrite_selection

    await _drain(run_turn("novel-sel-8", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))

    async def _second_write_turn(_system: str, _packet: str) -> str:
        return "乙站起身，走向门口。"

    await _drain(run_turn(
        "novel-sel-8", 1, "第二轮", write_turn=_second_write_turn, **_with_llms(_call_llm),
    ))
    first_round_id = (await peek_state("novel-sel-8", 1))["turns"][0]["id"]

    async def _sel_llm(_system: str, _user: str) -> str:
        return "望向远方"

    # Targets round 0 explicitly even though round 1 is now turns[-1] -- this is the case a
    # selection-rewrite queued while round 1 was still generating must land correctly on.
    new_prose = await rewrite_selection(
        "novel-sel-8", 1, "看向窗外", 0, "",
        call_llm=_sel_llm, guard_text=_identity_guard_text, round_id=first_round_id,
    )
    assert new_prose == "甲抬起头，望向远方。"

    state = await peek_state("novel-sel-8", 1)
    assert state["turns"][0]["prose"] == "甲抬起头，望向远方。"
    assert state["turns"][1]["prose"] == "乙站起身，走向门口。"  # untouched


@pytest.mark.asyncio
async def test_rewrite_selection_raises_when_round_id_no_longer_exists():
    from engine.story_sandbox.graph import rewrite_selection

    await _drain(run_turn("novel-sel-9", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))

    async def _sel_llm(_system: str, _user: str) -> str:
        return "不会被调用"

    with pytest.raises(ValueError):
        await rewrite_selection(
            "novel-sel-9", 1, "看向窗外", 0, "",
            call_llm=_sel_llm, guard_text=_identity_guard_text, round_id="不存在的round-id",
        )


@pytest.mark.asyncio
async def test_peek_state_backfills_a_missing_round_id_and_persists_it():
    """Rounds checkpointed before round-id targeting shipped lack the field -- peek_state (the
    history endpoint's read path) must lazily assign and persist one, same convention as
    setup_chat_history's checkpoint backfill, so a later rewrite_selection call sees the same id
    peek_state already handed the frontend."""
    from engine.story_sandbox.graph import _compile_noop_graph, ensure_checkpointer, peek_state

    await _drain(run_turn("novel-sel-10", 1, "第一轮", branch_id=LEGACY_BRANCH_ID, write_turn=_write_turn, **_with_llms(_call_llm)))

    checkpointer = await ensure_checkpointer("novel-sel-10")
    graph = _compile_noop_graph(checkpointer)
    config = {"configurable": {"thread_id": "novel-sel-10:1"}}
    existing = await graph.aget_state(config)
    legacy_turns = [{**existing.values["turns"][0]}]
    del legacy_turns[0]["id"]
    await graph.aupdate_state(config, {"turns": legacy_turns})

    first_state = await peek_state("novel-sel-10", 1, branch_id=LEGACY_BRANCH_ID)
    backfilled_id = first_state["turns"][0]["id"]
    assert backfilled_id

    second_state = await peek_state("novel-sel-10", 1, branch_id=LEGACY_BRANCH_ID)
    assert second_state["turns"][0]["id"] == backfilled_id


@pytest.mark.asyncio
async def test_rewrite_last_round_preserves_the_rounds_id():
    from engine.story_sandbox.graph import peek_state, rewrite_last_round

    await _drain(run_turn("novel-sel-11", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))
    original_id = (await peek_state("novel-sel-11", 1))["turns"][0]["id"]

    async def _rewrite_write_turn(_system, _packet):
        return "甲缓缓抬起头，目光冷淡。"

    await _drain(await rewrite_last_round(
        "novel-sel-11", 1, "语气再冷淡一点", write_turn=_rewrite_write_turn, **_with_llms(_call_llm),
    ))

    state = await peek_state("novel-sel-11", 1)
    assert state["turns"][0]["id"] == original_id


@pytest.mark.asyncio
async def test_regenerate_suggestions_routes_slash_hint_to_skill_agent(monkeypatch):
    from engine.setup_chat import skills
    from engine.story_sandbox.graph import regenerate_suggestions

    await _drain(run_turn("novel-40", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))

    monkeypatch.setattr(skills, "list_skill_index", lambda dirs: [
        {"name": "example-action-skill", "description": "", "kind": "plot-extension", "source": "builtin"},
    ])
    monkeypatch.setattr(skills, "load_skill_body", lambda name, dirs: "占位技能正文")

    seen = {}

    async def _fake_skill_agent(system, user, tools):
        seen["system"] = system
        seen["user"] = user
        return '["动作候选一", "动作候选二"]'

    result = await regenerate_suggestions(
        "novel-40", 1, _call_llm,
        hint="/example-action-skill 两人在船上",
        run_skill_agent=_fake_skill_agent,
        guard_text=_identity_guard_text,
    )
    assert result == ["动作候选一", "动作候选二"]
    assert "两人在船上" in seen["user"]


@pytest.mark.asyncio
async def test_regenerate_suggestions_slash_hint_gets_related_cast_from_relationship_graph(
    monkeypatch,
):
    """Same present-vs-related split as suggest_directions, but for the run_skill_agent branch
    (a /skill-name hint) -- run_skill_suggestion must also see related_cards, not just cards."""
    from engine.setup_chat import skills
    from engine.story_sandbox.graph import regenerate_suggestions

    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {"甲→角色甲": {
            "from": "甲", "to": "角色甲", "nature": "主人/奴隶", "relationship_anchor": "",
            "from_ref_terms": [], "to_ref_terms": ["废物"],
        }}},
    )
    await _drain(run_turn("novel-43", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))

    monkeypatch.setattr(skills, "list_skill_index", lambda dirs: [
        {"name": "example-action-skill", "description": "", "kind": "plot-extension", "source": "builtin"},
    ])
    monkeypatch.setattr(skills, "load_skill_body", lambda name, dirs: "占位技能正文")

    seen = {}

    async def _fake_skill_agent(system, user, tools):
        seen["user"] = user
        return "[]"

    await regenerate_suggestions(
        "novel-43", 1, _call_llm,
        hint="/example-action-skill 两人在船上",
        run_skill_agent=_fake_skill_agent,
        guard_text=_identity_guard_text,
    )
    assert "相关角色档案" in seen["user"]
    assert "角色甲" in seen["user"]
    assert "默认不要让他们出现或行动" in seen["user"]


@pytest.mark.asyncio
async def test_regenerate_suggestions_falls_back_to_plain_suggest_when_no_skill_agent(monkeypatch):
    from engine.setup_chat import skills
    from engine.story_sandbox.graph import regenerate_suggestions

    await _drain(run_turn("novel-41", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))

    monkeypatch.setattr(skills, "list_skill_index", lambda dirs: [
        {"name": "example-action-skill", "description": "", "kind": "plot-extension", "source": "builtin"},
    ])

    # run_skill_agent not provided -> even a matching /skill-name hint must fall back to plain
    # suggest_directions rather than crash.
    result = await regenerate_suggestions(
        "novel-41", 1, _call_llm, hint="/example-action-skill 两人在船上",
        guard_text=_identity_guard_text,
    )
    assert result == ["建议一", "建议二"]


@pytest.mark.asyncio
async def test_regenerate_suggestions_unregistered_slash_name_uses_plain_suggest(monkeypatch):
    from engine.setup_chat import skills
    from engine.story_sandbox.graph import regenerate_suggestions

    await _drain(run_turn("novel-42", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))

    monkeypatch.setattr(skills, "list_skill_index", lambda dirs: [])

    async def _fake_skill_agent(system, user, tools):
        raise AssertionError("should not be called for an unregistered skill name")

    result = await regenerate_suggestions(
        "novel-42", 1, _call_llm, hint="/not-a-skill 继续",
        run_skill_agent=_fake_skill_agent,
        guard_text=_identity_guard_text,
    )
    assert result == ["建议一", "建议二"]


@pytest.mark.asyncio
async def test_regenerate_suggestions_gets_related_cast_from_relationship_graph(monkeypatch):
    """剧情选项重新生成 (regenerate_suggestions) is a standalone entry point, separate from
    run_turn's own suggest node -- it needs the same present-vs-related split so a character
    only connected to someone present via the relationship graph is grounding-only context,
    not someone the regenerated suggestions can have act (mirrors
    test_run_turn_suggest_directions_gets_related_cast_from_relationship_graph)."""
    from engine.story_sandbox.graph import regenerate_suggestions

    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {"甲→角色甲": {
            "from": "甲", "to": "角色甲", "nature": "主人/奴隶", "relationship_anchor": "",
            "from_ref_terms": [], "to_ref_terms": ["废物"],
        }}},
    )

    await _drain(run_turn("novel-regen-related-cast", 1, "继续", write_turn=_write_turn, **_with_llms(_call_llm)))

    seen = {}

    async def _suggest_aware_llm(system, user):
        if "走向建议" in system:
            seen["system"] = system
            return "[]"
        return await _call_llm(system, user)

    await regenerate_suggestions(
        "novel-regen-related-cast", 1, _suggest_aware_llm, guard_text=_identity_guard_text,
    )
    assert "相关角色档案" in seen["system"]
    assert "角色甲" in seen["system"]
    assert "默认不要让他们出现或行动" in seen["system"]


@pytest.mark.asyncio
async def test_run_turn_calls_initial_derivation_only_on_the_opening_turn():
    calls = []

    async def _tracking_llm(system, _user):
        if "根据导演指令" in system or "根据这段正文内容" in system:
            return '{"角色": ["甲"], "路人": []}'
        if "为每个角色推演出登场时的初始状态" in system:
            calls.append("init")
            return '{"甲": {"psychology": "外冷内热"}}'
        if "走向建议" in system:
            return '["建议一"]'
        if "场景当前的状态" in system or "场景推演出开场时的初始状态" in system:
            return '{}'
        return '{"甲": {"psychology": "逐渐大胆"}}'

    await _drain(run_turn("novel-9", 1, "第一轮", write_turn=_write_turn, **_with_llms(_tracking_llm)))
    await _drain(run_turn("novel-9", 1, "第二轮", write_turn=_write_turn, **_with_llms(_tracking_llm)))

    assert calls == ["init"]


@pytest.mark.asyncio
async def test_run_turn_opening_system_prompt_reflects_initial_states():
    seen = {}

    async def _tracking_write_turn(system, _packet):
        seen["system"] = system
        return "甲抬起头。"

    async def _init_llm(system, _user):
        if "初始状态" in system:
            return '{"甲": {"psychology": "外冷内热"}}'
        if "走向建议" in system:
            return '["建议一"]'
        return '{"甲": {"psychology": "外冷内热"}}'

    await _drain(run_turn("novel-10", 1, "第一轮", write_turn=_tracking_write_turn, **_with_llms(_init_llm)))
    assert "外冷内热" in seen["system"]


@pytest.mark.asyncio
async def test_run_turn_emits_initial_state_step_before_prose_completes():
    steps = [step async for step in run_turn(
        "novel-11", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm),
    )]
    initial_state_step = next(s for s in steps if s["type"] == SandboxStepType.INITIAL_STATE)
    assert initial_state_step["states"] == {"甲": {"psychology": "逐渐大胆"}}
    prose_index = next(i for i, s in enumerate(steps) if s["type"] == SandboxStepType.PROSE)
    initial_state_index = next(
        i for i, s in enumerate(steps) if s["type"] == SandboxStepType.INITIAL_STATE
    )
    assert initial_state_index < prose_index


@pytest.mark.asyncio
async def test_run_turn_has_no_initial_state_step_on_a_later_turn():
    await _drain(run_turn("novel-12", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))
    steps = [step async for step in run_turn(
        "novel-12", 1, "第二轮", write_turn=_write_turn, **_with_llms(_call_llm),
    )]
    assert not any(s["type"] == SandboxStepType.INITIAL_STATE for s in steps)


@pytest.mark.asyncio
async def test_run_turn_bundles_initial_states_into_the_opening_round_only():
    from engine.story_sandbox.graph import peek_state

    await _drain(run_turn("novel-13", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))
    await _drain(run_turn("novel-13", 1, "第二轮", write_turn=_write_turn, **_with_llms(_call_llm)))

    state = await peek_state("novel-13", 1)
    assert state["turns"][0]["initial_states"] == {"甲": {"psychology": "逐渐大胆"}}
    assert state["turns"][1]["initial_states"] is None


@pytest.mark.asyncio
async def test_rewrite_last_round_replaces_prose_but_keeps_instruction():
    from engine.story_sandbox.graph import peek_state, rewrite_last_round

    await _drain(run_turn("novel-20", 1, "甲乙对峙", write_turn=_write_turn, **_with_llms(_call_llm)))

    async def _rewrite_write_turn(_system, _packet):
        return "甲缓缓抬起头，目光冷淡。"

    final_text, suggestions, states, _ = await _drain(await rewrite_last_round(
        "novel-20", 1, "语气再冷淡一点", write_turn=_rewrite_write_turn, **_with_llms(_call_llm),
    ))
    assert final_text == "甲缓缓抬起头，目光冷淡。"

    state = await peek_state("novel-20", 1)
    assert len(state["turns"]) == 1
    assert state["turns"][0]["instruction"] == "甲乙对峙"
    assert state["turns"][0]["prose"] == "甲缓缓抬起头，目光冷淡。"
    assert state["turns"][0]["character_states"] == states
    assert state["turns"][0]["suggestions"] == suggestions
    assert state["character_states"] == states
    assert state["suggestions"] == suggestions


@pytest.mark.asyncio
async def test_rewrite_last_round_keeps_turn_count_and_recomputes_rolling_summary():
    from engine.story_sandbox.graph import peek_state, rewrite_last_round

    for i in range(3):
        await _drain(run_turn("novel-21", 1, f"指令{i}", write_turn=_write_turn, **_with_llms(_call_llm)))
    mid_state = await peek_state("novel-21", 1)
    assert len(mid_state["turns"]) == 3
    assert mid_state["rolling_summary"] == "折叠后的摘要"

    await _drain(await rewrite_last_round(
        "novel-21", 1, "反馈", write_turn=_write_turn, **_with_llms(_call_llm),
    ))

    state = await peek_state("novel-21", 1)
    assert len(state["turns"]) == 3
    # Recomputed (not skipped) -- this mock always folds to the same text regardless of input,
    # so the value happens not to visibly change here; the test below proves the recompute
    # actually uses fresh input by using a mock that differentiates before/after rewrite.
    assert state["rolling_summary"] == "折叠后的摘要"


@pytest.mark.asyncio
async def test_rewrite_last_round_recomputes_rolling_summary_and_replaces_event_entry():
    from engine.memory_recall.event_log import load_event_log
    from engine.story_sandbox.graph import peek_state, rewrite_last_round

    async def _event_llm(system: str, user: str) -> str:
        if "剧情摘要助手" in system:
            return "原摘要"
        if "事件摘要助手" in system:
            return '{"event": "甲说了谎", "entities": ["甲"]}'
        return await _call_llm(system, user)

    await _drain(run_turn(
        "novel-rewrite-event", 1, "指令0", write_turn=_write_turn, **_with_llms(_event_llm),
    ))
    original_entry_id = (
        await peek_state("novel-rewrite-event", 1)
    )["turns"][0]["event_log_entries"][0]["id"]

    async def _rewritten_event_llm(system: str, user: str) -> str:
        if "剧情摘要助手" in system:
            return "改口后的摘要"
        if "事件摘要助手" in system:
            return '{"event": "甲坦白了真相", "entities": ["甲"]}'
        return await _call_llm(system, user)

    await _drain(await rewrite_last_round(
        "novel-rewrite-event", 1, "改成坦白", write_turn=_write_turn, **_with_llms(_rewritten_event_llm),
    ))

    state = await peek_state("novel-rewrite-event", 1)
    assert state["rolling_summary"] == "改口后的摘要"
    new_entry = state["turns"][0]["event_log_entries"][0]
    assert new_entry["summary"] == "甲坦白了真相"
    assert new_entry["id"] != original_entry_id

    saved = load_event_log()
    matching = [e for e in saved["entries"] if e["id"] == new_entry["id"]]
    assert len(matching) == 1
    assert not any(e["id"] == original_entry_id for e in saved["entries"])


@pytest.mark.asyncio
async def test_archiving_a_rewritten_round_reflects_the_rewrite_not_the_stale_original(
    monkeypatch,
):
    """Regression test for the staleness bug: a round's entry is only archived once the NEXT
    round begins (see event_log.py::_archive_previous_round) -- so if the round gets rewritten
    before that happens, what eventually gets embedded into vector memory is the rewritten
    content, never the discarded original."""
    from engine.story_sandbox.graph import rewrite_last_round

    archived: list[dict] = []

    async def _fake_archive(entries):
        archived.extend(entries)
        return len(entries)

    monkeypatch.setattr(
        "engine.memory_recall.event_log.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"archive": staticmethod(_fake_archive)})(),
    )

    async def _event_llm(system: str, user: str) -> str:
        if "剧情摘要助手" in system:
            return "原摘要"
        if "事件摘要助手" in system:
            return '{"event": "甲说了谎", "entities": ["甲"]}'
        return await _call_llm(system, user)

    await _drain(run_turn(
        "novel-rewrite-archive", 1, "指令0", write_turn=_write_turn, **_with_llms(_event_llm),
    ))
    assert archived == []  # opening round: nothing to archive yet

    async def _rewritten_event_llm(system: str, user: str) -> str:
        if "剧情摘要助手" in system:
            return "改口后的摘要"
        if "事件摘要助手" in system:
            return '{"event": "甲坦白了真相", "entities": ["甲"]}'
        return await _call_llm(system, user)

    await _drain(await rewrite_last_round(
        "novel-rewrite-archive", 1, "改成坦白",
        write_turn=_write_turn, **_with_llms(_rewritten_event_llm),
    ))
    assert archived == []  # rewrite itself never archives

    await _drain(run_turn(
        "novel-rewrite-archive", 1, "指令1", write_turn=_write_turn, **_with_llms(_call_llm),
    ))

    assert len(archived) == 1
    assert archived[0]["summary"] == "甲坦白了真相"


@pytest.mark.asyncio
async def test_rewrite_last_round_reruns_state_derivation_and_suggestions():
    from engine.story_sandbox.graph import rewrite_last_round

    await _drain(run_turn("novel-22", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))

    async def _new_llm(system, _user):
        if "根据导演指令" in system or "根据这段正文内容" in system:
            return '{"角色": ["甲"], "路人": []}'
        if "走向建议" in system:
            return '["新建议A"]'
        if "场景当前的状态" in system:
            return '{}'
        return '{"甲": {"psychology": "焦躁不安"}}'

    _, suggestions, states, _ = await _drain(await rewrite_last_round(
        "novel-22", 1, "反馈", write_turn=_write_turn, **_with_llms(_new_llm),
    ))
    assert suggestions == ["新建议A"]
    assert states["甲"]["psychology"] == "焦躁不安"


@pytest.mark.asyncio
async def test_rewrite_last_round_of_opening_round_does_not_re_derive_initial_states(monkeypatch):
    from engine.story_sandbox.graph import rewrite_last_round

    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: ["甲"],
    )

    calls = []

    async def _tracking_llm(system, _user):
        if "根据导演指令" in system or "根据这段正文内容" in system:
            return '{"角色": ["甲"], "路人": []}'
        if "为每个角色推演出登场时的初始状态" in system:
            calls.append("init")
            return '{"甲": {"psychology": "外冷内热"}}'
        if "走向建议" in system:
            return '["建议一"]'
        if "场景当前的状态" in system or "场景推演出开场时的初始状态" in system:
            return '{}'
        return '{"甲": {"psychology": "逐渐大胆"}}'

    await _drain(run_turn("novel-23", 1, "第一轮", write_turn=_write_turn, **_with_llms(_tracking_llm)))
    assert calls == ["init"]

    await _drain(await rewrite_last_round(
        "novel-23", 1, "反馈", write_turn=_write_turn, **_with_llms(_tracking_llm),
    ))
    assert calls == ["init"]


@pytest.mark.asyncio
async def test_rewrite_last_round_non_opening_round_uses_previous_rounds_states_as_baseline(monkeypatch):
    from engine.story_sandbox.graph import peek_state, rewrite_last_round
    from engine.story_sandbox.state_derive import derive_character_states as original_derive

    await _drain(run_turn("novel-24", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))
    await _drain(run_turn("novel-24", 1, "第二轮", write_turn=_write_turn, **_with_llms(_call_llm)))
    first_round_states = (await peek_state("novel-24", 1))["turns"][0]["character_states"]

    seen = {}

    async def _spy_derive(current_states, final_text, call_llm, present=None):
        seen["baseline"] = current_states
        return await original_derive(current_states, final_text, call_llm, present=present)

    monkeypatch.setattr("engine.story_sandbox.graph.derive_character_states", _spy_derive)

    await _drain(await rewrite_last_round(
        "novel-24", 1, "反馈", write_turn=_write_turn, **_with_llms(_call_llm),
    ))
    assert seen["baseline"] == first_round_states


@pytest.mark.asyncio
async def test_rewrite_last_round_packet_includes_previous_prose_and_feedback():
    from engine.story_sandbox.graph import rewrite_last_round

    await _drain(run_turn("novel-25", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))

    seen = {}

    async def _tracking_write_turn(_system, packet):
        seen["packet"] = packet
        return "重写后的正文。"

    await _drain(await rewrite_last_round(
        "novel-25", 1, "语气再冷淡一点", write_turn=_tracking_write_turn, **_with_llms(_call_llm),
    ))
    assert "甲抬起头，看向窗外。" in seen["packet"]
    assert "语气再冷淡一点" in seen["packet"]
    assert "第一轮" in seen["packet"]


@pytest.mark.asyncio
async def test_rewrite_last_round_raises_when_no_rounds_exist():
    from engine.story_sandbox.graph import rewrite_last_round

    with pytest.raises(ValueError):
        await rewrite_last_round(
            "novel-26", 1, "反馈", write_turn=_write_turn, **_with_llms(_call_llm),
        )


@pytest.mark.asyncio
async def test_rewrite_last_round_yields_prose_then_state_then_suggestions_in_order():
    from engine.story_sandbox.graph import rewrite_last_round

    await _drain(run_turn("novel-27", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))
    steps = [step["type"] async for step in await rewrite_last_round(
        "novel-27", 1, "反馈", write_turn=_write_turn, **_with_llms(_call_llm),
    )]
    assert steps[0] == SandboxStepType.PROSE
    assert steps[-1] == SandboxStepType.SUGGESTIONS
    assert set(steps) == {
        SandboxStepType.PROSE, SandboxStepType.STATE,
        SandboxStepType.EVENT_LOG, SandboxStepType.PROFILE_MUTATION,
        SandboxStepType.SUGGESTIONS,
    }


@pytest.mark.asyncio
async def test_run_turn_marks_previous_round_with_submitted_directions():
    from engine.story_sandbox.graph import peek_state

    await _drain(run_turn("novel-30", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))
    await _drain(run_turn(
        "novel-30", 1, "- 建议一", write_turn=_write_turn, **_with_llms(_call_llm),
        submitted_directions=["建议一"],
    ))

    state = await peek_state("novel-30", 1)
    assert state["turns"][0]["submitted_directions"] == ["建议一"]
    assert state["turns"][1].get("submitted_directions") is None


@pytest.mark.asyncio
async def test_run_turn_marks_previous_round_before_prose_streams():
    """The mark must be checkpointed before the new turn's graph even starts running --
    not deferred until this turn's prose node (its next-paragraph write) finishes -- so a
    concurrent history read (e.g. a remounted frontend tab) sees the previous round as
    submitted right away, not only once the next segment of prose is done."""
    from engine.story_sandbox.graph import peek_state

    await _drain(run_turn("novel-33", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))

    write_started = asyncio.Event()
    release_write = asyncio.Event()

    async def _slow_write_turn(_system: str, _packet: str) -> str:
        write_started.set()
        await release_write.wait()
        return "甲抬起头，看向窗外。"

    task = asyncio.create_task(_drain(run_turn(
        "novel-33", 1, "- 建议一", write_turn=_slow_write_turn, **_with_llms(_call_llm),
        submitted_directions=["建议一"],
    )))
    try:
        await asyncio.wait_for(write_started.wait(), timeout=5)
        state = await peek_state("novel-33", 1)
        assert state["turns"][0]["submitted_directions"] == ["建议一"]
    finally:
        release_write.set()
        await task


@pytest.mark.asyncio
async def test_run_turn_ignores_submitted_directions_not_in_previous_suggestions():
    from engine.story_sandbox.graph import peek_state

    await _drain(run_turn("novel-31", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))
    await _drain(run_turn(
        "novel-31", 1, "乱写的指令", write_turn=_write_turn, **_with_llms(_call_llm),
        submitted_directions=["不存在的建议"],
    ))

    state = await peek_state("novel-31", 1)
    assert state["turns"][0].get("submitted_directions") is None


@pytest.mark.asyncio
async def test_run_turn_opening_turn_ignores_submitted_directions_with_no_prior_round():
    from engine.story_sandbox.graph import peek_state

    await _drain(run_turn(
        "novel-32", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm),
        submitted_directions=["建议一"],
    ))
    state = await peek_state("novel-32", 1)
    assert len(state["turns"]) == 1
    assert state["turns"][0].get("submitted_directions") is None


@pytest.mark.asyncio
async def test_run_turn_derives_initial_scene_state_on_opening_turn():
    from engine.story_sandbox.graph import peek_state

    await _drain(run_turn("novel-50", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))
    state = await peek_state("novel-50", 1)
    assert state["turns"][0]["initial_scene_state"] == {"description": "昏暗的书房"}
    assert state["scene_state"] == {"description": "昏暗的书房"}


@pytest.mark.asyncio
async def test_run_turn_does_not_rederive_initial_scene_state_on_later_turns():
    from engine.story_sandbox.graph import peek_state

    calls = []

    async def _tracking_llm(system, _user):
        if "场景推演出开场时的初始状态" in system:
            calls.append("init_scene")
            return '{"description": "昏暗的书房"}'
        if "场景当前的状态" in system:
            return '{"description": "凌乱的书房"}'
        if "走向建议" in system:
            return '["建议一"]'
        return '{"甲": {"psychology": "逐渐大胆"}}'

    await _drain(run_turn("novel-51", 1, "第一轮", write_turn=_write_turn, **_with_llms(_tracking_llm)))
    await _drain(run_turn("novel-51", 1, "第二轮", write_turn=_write_turn, **_with_llms(_tracking_llm)))
    assert calls == ["init_scene"]
    state = await peek_state("novel-51", 1)
    assert state["turns"][1]["initial_scene_state"] is None
    assert state["scene_state"] == {"description": "凌乱的书房"}


@pytest.mark.asyncio
async def test_run_turn_evolves_scene_state_every_turn():
    from engine.story_sandbox.graph import peek_state

    call_n = {"n": 0}

    async def _evolving_llm(system, _user):
        if "场景推演出开场时的初始状态" in system:
            return '{"description": "昏暗的书房"}'
        if "场景当前的状态" in system:
            call_n["n"] += 1
            return f'{{"description": "第{call_n["n"]}轮后的书房"}}'
        if "走向建议" in system:
            return '["建议一"]'
        return '{"甲": {"psychology": "逐渐大胆"}}'

    await _drain(run_turn("novel-52", 1, "第一轮", write_turn=_write_turn, **_with_llms(_evolving_llm)))
    await _drain(run_turn("novel-52", 1, "第二轮", write_turn=_write_turn, **_with_llms(_evolving_llm)))
    state = await peek_state("novel-52", 1)
    assert state["turns"][0]["scene_state"] == {"description": "第1轮后的书房"}
    assert state["turns"][1]["scene_state"] == {"description": "第2轮后的书房"}


@pytest.mark.asyncio
async def test_run_turn_initial_state_step_carries_initial_scene_state():
    steps = [step async for step in run_turn(
        "novel-53", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm),
    )]
    initial_state_step = next(s for s in steps if s["type"] == SandboxStepType.INITIAL_STATE)
    assert initial_state_step["scene_state"] == {"description": "昏暗的书房"}


@pytest.mark.asyncio
async def test_run_turn_state_step_carries_scene_state():
    steps = [step async for step in run_turn(
        "novel-54", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm),
    )]
    state_step = next(s for s in steps if s["type"] == SandboxStepType.STATE)
    assert state_step["scene_state"] == {"description": "昏暗的书房"}


@pytest.mark.asyncio
async def test_rewrite_last_round_reruns_scene_derivation():
    from engine.story_sandbox.graph import rewrite_last_round

    await _drain(run_turn("novel-55", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))

    async def _new_llm(system, _user):
        if "场景当前的状态" in system:
            return '{"description": "被打翻的书房"}'
        if "走向建议" in system:
            return '["新建议A"]'
        return '{"甲": {"psychology": "焦躁不安"}}'

    steps = [step async for step in await rewrite_last_round(
        "novel-55", 1, "反馈", write_turn=_write_turn, **_with_llms(_new_llm),
    )]
    state_step = next(s for s in steps if s["type"] == SandboxStepType.STATE)
    assert state_step["scene_state"] == {"description": "被打翻的书房"}


@pytest.mark.asyncio
async def test_derive_char_and_derive_scene_run_concurrently_not_sequentially():
    """Concurrency check: asyncio.Event cross-wait -- sequential await would deadlock."""
    import asyncio

    char_started = asyncio.Event()
    scene_started = asyncio.Event()

    async def _tracking_llm(system, _user):
        if "走向建议" in system:
            return '["建议一"]'
        if "场景" in system or "环境" in system:
            scene_started.set()
            await asyncio.wait_for(char_started.wait(), timeout=1)
            return '{"description": "昏暗"}'
        char_started.set()
        await asyncio.wait_for(scene_started.wait(), timeout=1)
        return '{"甲": {"psychology": "警惕"}}'

    await _drain(run_turn(
        "novel-parallel", 1, "继续", write_turn=_write_turn, **_with_llms(_tracking_llm),
    ))


@pytest.mark.asyncio
async def test_init_char_and_init_scene_run_concurrently_on_opening_turn():
    import asyncio

    char_started = asyncio.Event()
    scene_started = asyncio.Event()

    async def _tracking_llm(system, _user):
        if "根据导演指令" in system or "根据这段正文内容" in system:
            return '{"角色": ["甲"], "路人": []}'
        if "走向建议" in system:
            return '["建议一"]'
        if "初始" in system and ("场景" in system or "环境" in system):
            scene_started.set()
            await asyncio.wait_for(char_started.wait(), timeout=1)
            return '{"description": "昏暗"}'
        if "初始" in system:
            char_started.set()
            await asyncio.wait_for(scene_started.wait(), timeout=1)
            return '{"甲": {"psychology": "警惕"}}'
        return '{"甲": {"psychology": "警惕"}}'

    await _drain(run_turn(
        "novel-parallel-init", 1, "第一轮", write_turn=_write_turn, **_with_llms(_tracking_llm),
    ))


@pytest.mark.asyncio
async def test_dialogue_draft_and_recall_run_concurrently_on_normal_turn(monkeypatch):
    """Concurrency check: threading.Event cross-wait -- sequential execution would deadlock."""
    import threading

    await _drain(run_turn(
        "novel-parallel-recall", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm),
    ))

    draft_started = threading.Event()
    recall_started = threading.Event()

    async def _dialogue_draft_llm(_system, _user):
        draft_started.set()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: recall_started.wait(1))
        return "甲：（台词）"

    def spy_recall(_text, **_kwargs):
        recall_started.set()
        if not draft_started.wait(timeout=1):
            raise TimeoutError("dialogue_draft did not start before recall finished waiting")
        return "", _kwargs.get("cooldown") or {}, []

    monkeypatch.setattr("engine.memory_recall.recall.recall_relevant_context", spy_recall)

    await _drain(run_turn(
        "novel-parallel-recall", 1, "继续", write_turn=_write_turn, **_with_llms(_call_llm),
        call_llm_dialogue_draft=_dialogue_draft_llm,
    ))


@pytest.mark.asyncio
async def test_dialogue_draft_and_recall_run_concurrently_on_opening_turn(monkeypatch):
    import threading

    draft_started = threading.Event()
    recall_started = threading.Event()

    async def _tracking_llm(system, _user):
        if "走向建议" in system:
            return '["建议一"]'
        if "初始" in system and ("场景" in system or "环境" in system):
            return '{"description": "昏暗"}'
        if "初始" in system:
            return '{"甲": {"psychology": "警惕"}}'
        return '{"甲": {"psychology": "警惕"}}'

    async def _dialogue_draft_llm(_system, _user):
        draft_started.set()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: recall_started.wait(1))
        return "甲：（台词）"

    def spy_recall(_text, **_kwargs):
        recall_started.set()
        if not draft_started.wait(timeout=1):
            raise TimeoutError("dialogue_draft did not start before recall finished waiting")
        return "", _kwargs.get("cooldown") or {}, []

    monkeypatch.setattr("engine.memory_recall.recall.recall_relevant_context", spy_recall)

    await _drain(run_turn(
        "novel-parallel-recall-opening", 1, "第一轮", write_turn=_write_turn,
        **_with_llms(_tracking_llm), call_llm_dialogue_draft=_dialogue_draft_llm,
    ))


@pytest.mark.asyncio
async def test_opening_graph_prose_fires_exactly_once_with_resolve_cast_in_chain(monkeypatch):
    """Regression guard for the exact OR-trigger hazard spec 2.4 warns about."""
    calls = []

    async def _counting_write_turn(system, packet):
        calls.append(1)
        return "甲：你好。"

    await _drain(run_turn(
        "novel-resolve-cast-single-fire", 1, "开场", write_turn=_counting_write_turn,
        **_with_llms(_call_llm),
    ))
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_dialogue_draft_and_recall_run_concurrently_on_rewrite_turn(monkeypatch):
    import threading

    await _drain(run_turn(
        "novel-parallel-recall-rewrite", 1, "指令0", write_turn=_write_turn, **_with_llms(_call_llm),
    ))
    await _drain(run_turn(
        "novel-parallel-recall-rewrite", 1, "指令1", write_turn=_write_turn, **_with_llms(_call_llm),
    ))

    draft_started = threading.Event()
    recall_started = threading.Event()

    async def _dialogue_draft_llm(_system, _user):
        draft_started.set()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: recall_started.wait(1))
        return "甲：（台词）"

    def spy_recall(_text, **_kwargs):
        recall_started.set()
        if not draft_started.wait(timeout=1):
            raise TimeoutError("dialogue_draft did not start before recall finished waiting")
        return "", _kwargs.get("cooldown") or {}, []

    monkeypatch.setattr("engine.memory_recall.recall.recall_relevant_context", spy_recall)

    from engine.story_sandbox.graph import rewrite_last_round
    await _drain(await rewrite_last_round(
        "novel-parallel-recall-rewrite", 1, "重写反馈", write_turn=_write_turn,
        **_with_llms(_call_llm), call_llm_dialogue_draft=_dialogue_draft_llm,
    ))


@pytest.mark.asyncio
async def test_run_turn_aborts_without_partial_commit_when_one_derive_sibling_fails():
    from engine.story_sandbox.derivation_retry import DerivationValidationError
    from engine.story_sandbox.graph import peek_state

    async def _failing_llm(system, _user):
        if "根据导演指令" in system or "根据这段正文内容" in system:
            return '{"角色": ["甲"], "路人": []}'
        if "走向建议" in system:
            return '["建议一"]'
        if "场景" in system or "环境" in system:
            return "不是JSON"
        return '{"甲": {"psychology": "警惕"}}'

    before = await peek_state("novel-atomic", 1)
    with pytest.raises(DerivationValidationError):
        async for _ in run_turn(
            "novel-atomic", 1, "第一轮", write_turn=_write_turn, **_with_llms(_failing_llm),
        ):
            pass
    after = await peek_state("novel-atomic", 1)
    assert after == before


@pytest.mark.asyncio
async def test_run_turn_initial_state_step_reflects_both_init_nodes_once_both_land():
    steps = [step async for step in run_turn(
        "novel-init-carry", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm),
    )]
    initial_state_step = next(s for s in steps if s["type"] == SandboxStepType.INITIAL_STATE)
    assert initial_state_step["states"] == {"甲": {"psychology": "逐渐大胆"}}
    assert initial_state_step["scene_state"] == {"description": "昏暗的书房"}


def test_normal_graph_wires_summary_fold_and_event_extract_nodes():
    import inspect

    from engine.story_sandbox import graph as g
    src = inspect.getsource(g._compile_graph)
    assert 'add_node("summary_fold"' in src
    assert 'add_node("event_extract"' in src
    assert 'add_edge("prose", "summary_fold")' in src
    assert 'add_edge("prose", "event_extract")' in src
    assert 'add_edge("event_extract", "profile_mutate")' in src


def test_opening_graph_wires_summary_fold_and_event_extract_nodes():
    import inspect

    from engine.story_sandbox import graph as g
    src = inspect.getsource(g._compile_opening_graph)
    assert 'add_node("summary_fold"' in src
    assert 'add_node("event_extract"' in src
    assert 'add_edge("prose", "summary_fold")' in src
    assert 'add_edge("prose", "event_extract")' in src
    assert 'add_edge("event_extract", "profile_mutate")' in src


def test_rewrite_graph_wires_summary_fold_and_event_extract_nodes():
    import inspect

    from engine.story_sandbox import graph as g
    src = inspect.getsource(g._compile_rewrite_graph)
    assert 'add_node("summary_fold"' in src
    assert 'add_node("event_extract"' in src
    assert 'add_edge("prose_rewrite", "summary_fold")' in src
    assert 'add_edge("prose_rewrite", "event_extract")' in src
    assert 'add_edge("event_extract", "profile_mutate")' in src


@pytest.mark.asyncio
async def test_run_turn_persists_recall_context_onto_its_own_round(monkeypatch):
    monkeypatch.setattr(
        "engine.memory_recall.recall.recall_relevant_context",
        lambda text, **kwargs: (f"## 相关历史/设定回收\n- 关于「{text}」的召回", {}, []),
    )

    from engine.story_sandbox.graph import peek_state

    await _drain(run_turn("novel-recall", 1, "提到玉佩", write_turn=_write_turn, **_with_llms(_call_llm)))
    state = await peek_state("novel-recall", 1)
    assert state["turns"][0]["recall_context"] == "## 相关历史/设定回收\n- 关于「提到玉佩」的召回"


@pytest.mark.asyncio
async def test_run_turn_prose_step_carries_recall_context(monkeypatch):
    monkeypatch.setattr(
        "engine.memory_recall.recall.recall_relevant_context", lambda text, **kwargs: ("召回内容", {}, []),
    )
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: ["乙"] if "乙" in text else [],
    )

    steps = [step async for step in run_turn(
        "novel-recall-2", 1, "乙登场了", write_turn=_write_turn, **_with_llms(_call_llm),
    )]
    prose_step = next(s for s in steps if s["type"] == SandboxStepType.PROSE)
    assert prose_step["recall_context"] == "召回内容"
    assert "乙" in prose_step["active_cast"]


@pytest.mark.asyncio
async def test_run_turn_state_step_carries_derive_char_corrected_active_cast(monkeypatch):
    """derive_char's identify call detects characters that scan_characters missed and folds
    them into active_cast on the state step."""
    await _drain(run_turn(
        "novel-mid-scene-cast", 1, "甲独自在书房", write_turn=_write_turn, **_with_llms(_call_llm),
    ))

    async def call_llm_identify(system: str, _user: str) -> str:
        if "根据这段正文内容" in system or "根据导演指令" in system:
            return '{"角色": ["乙"], "路人": []}'
        return await _call_llm(system, _user)

    async def call_llm_derive_char(system: str, _user: str) -> str:
        return '{"乙": {"psychology": "刚刚推门而入"}}'

    steps = [step async for step in run_turn(
        "novel-mid-scene-cast", 1, "乙突然推门而入", write_turn=_write_turn,
        **{**_with_llms(_call_llm), "call_llm_derive_char": call_llm_derive_char,
           "call_llm_identify": call_llm_identify},
    )]
    state_step = next(s for s in steps if s["type"] == SandboxStepType.STATE)
    assert "乙" in state_step["active_cast"]


@pytest.mark.asyncio
async def test_rewrite_last_round_prose_step_carries_active_cast(monkeypatch):
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: ["乙"] if "乙" in text else [],
    )

    from engine.story_sandbox.graph import rewrite_last_round

    await _drain(run_turn(
        "novel-rewrite-cast", 1, "乙登场了", write_turn=_write_turn, **_with_llms(_call_llm),
    ))
    steps = [step async for step in await rewrite_last_round(
        "novel-rewrite-cast", 1, "反馈", write_turn=_write_turn, **_with_llms(_call_llm),
    )]
    prose_step = next(s for s in steps if s["type"] == SandboxStepType.PROSE)
    # "甲" (stage1 roster) carries over from the opening turn's seeded active_cast.
    assert prose_step["active_cast"] == ["乙", "甲"]


@pytest.mark.asyncio
async def test_rewrite_last_round_recomputes_recall_context(monkeypatch):
    from engine.story_sandbox.graph import peek_state, rewrite_last_round

    monkeypatch.setattr(
        "engine.memory_recall.recall.recall_relevant_context", lambda text, **kwargs: ("重写前的召回", {}, []),
    )
    await _drain(run_turn("novel-recall-3", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm)))

    monkeypatch.setattr(
        "engine.memory_recall.recall.recall_relevant_context", lambda text, **kwargs: ("重写后的召回", {}, []),
    )
    await _drain(await rewrite_last_round(
        "novel-recall-3", 1, "反馈", write_turn=_write_turn, **_with_llms(_call_llm),
    ))

    state = await peek_state("novel-recall-3", 1)
    assert state["turns"][0]["recall_context"] == "重写后的召回"


def test_normal_graph_wires_profile_mutate_node():
    import inspect

    from engine.story_sandbox import graph as g
    src = inspect.getsource(g._compile_graph)
    assert 'add_edge("event_extract", "profile_mutate")' in src
    assert '["derive_char", "derive_scene", "profile_mutate", "summary_fold"], "suggest"' in src
    assert 'add_edge("event_extract", "suggest")' not in src


def test_opening_graph_wires_profile_mutate_node():
    import inspect

    from engine.story_sandbox import graph as g
    src = inspect.getsource(g._compile_opening_graph)
    assert 'add_edge("event_extract", "profile_mutate")' in src
    assert '["derive_char", "derive_scene", "profile_mutate", "summary_fold"], "suggest"' in src


def test_rewrite_graph_wires_profile_mutate_node():
    import inspect

    from engine.story_sandbox import graph as g
    src = inspect.getsource(g._compile_rewrite_graph)
    assert 'add_edge("event_extract", "profile_mutate")' in src
    assert '["derive_char", "derive_scene", "profile_mutate", "summary_fold"], "suggest_rewrite"' in src


@pytest.mark.asyncio
async def test_run_turn_attaches_profile_mutation_directly_to_its_own_round(monkeypatch):

    async def _event_and_mutate_llm(system: str, user: str) -> str:
        if "剧情摘要助手" in system:
            return "新摘要"
        if "事件摘要助手" in system:
            return '{"event": "甲变身了", "time": "指令0之后", "entities": ["甲"]}'
        if "档案资料发生了实质性变化" in system:
            return '{"甲": {"race": "精灵"}}'
        return await _call_llm(system, user)

    text, suggestions, states, _ = await _drain(run_turn(
        "novel-profile-mutate", 1, "指令0", write_turn=_write_turn, **_with_llms(_event_and_mutate_llm),
    ))

    from engine.story_sandbox.graph import peek_state
    state = await peek_state("novel-profile-mutate", 1)
    assert state["turns"][0]["profile_mutation"] == {"甲": {"race": "精灵"}}
    assert state["character_profile"] == {}


@pytest.mark.asyncio
async def test_run_turn_profile_mutation_is_none_when_no_event_this_turn():
    async def _no_event_llm(system: str, user: str) -> str:
        if "剧情摘要助手" in system:
            return "新摘要"
        if "事件摘要助手" in system:
            return '{"event": "", "time": "", "entities": []}'
        return await _call_llm(system, user)

    await _drain(run_turn(
        "novel-profile-no-event", 1, "指令0", write_turn=_write_turn, **_with_llms(_no_event_llm),
    ))

    from engine.story_sandbox.graph import peek_state
    state = await peek_state("novel-profile-no-event", 1)
    assert state["turns"][0]["profile_mutation"] is None
    assert state["character_profile"] == {}


@pytest.mark.asyncio
async def test_run_turn_relationship_mutation_deferred_by_one_round_through_real_graph(
    monkeypatch,
):
    """End-to-end (through the real compiled graph, not a hand-built state dict): a relationship
    edge profile_mutate proposes on round N must not enter the confirmed relationship_overlay
    until round N+1 commits it -- mirrors the existing profile_mutation deferred-commit coverage
    (test_run_turn_attaches_profile_mutation_directly_to_its_own_round), extended to the
    relationship-edge side channel this feature adds."""
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters", lambda text: ["甲", "乙"],
    )

    async def _relationship_llm(system: str, user: str) -> str:
        if "剧情摘要助手" in system:
            return "新摘要"
        if "事件摘要助手" in system:
            return '{"event": "甲乙结拜", "time": "指令0之后", "entities": ["甲", "乙"]}'
        if "档案资料发生了实质性变化" in system:
            return json.dumps({"$relationships": [_EDGE_甲乙]}, ensure_ascii=False)
        return await _call_llm(system, user)

    await _drain(run_turn(
        "novel-relationship-mutate", 1, "指令0", write_turn=_write_turn,
        **_with_llms(_relationship_llm),
    ))

    from engine.story_sandbox.graph import peek_state
    state = await peek_state("novel-relationship-mutate", 1)
    assert state["turns"][0]["relationship_mutation"] == {"甲→乙": _EDGE_甲乙}
    assert state["relationship_overlay"] == {}  # not yet committed

    async def _no_op_llm(system: str, user: str) -> str:
        if "剧情摘要助手" in system:
            return ""
        if "事件摘要助手" in system:
            return '{"event": "", "time": "", "entities": []}'
        if "档案资料发生了实质性变化" in system:
            return "{}"
        return await _call_llm(system, user)

    await _drain(run_turn(
        "novel-relationship-mutate", 1, "指令1", write_turn=_write_turn, **_with_llms(_no_op_llm),
    ))
    state = await peek_state("novel-relationship-mutate", 1)
    assert state["relationship_overlay"] == {"甲→乙": _EDGE_甲乙}  # now committed


@pytest.mark.asyncio
async def test_run_turn_committed_relationship_overlay_surfaces_related_cast_without_disk_write(
    monkeypatch,
):
    """The committed overlay (see the deferred-commit test above) must feed the same
    resolve_related_cast path a base-graph edge would -- and never touches
    relationship_edges.jsonl, since load_graph is mocked to return an empty graph here yet the
    related name still resolves purely from state."""
    from engine.story_sandbox.cast import resolve_related_cast

    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph", lambda: {"groups": {}, "edges": {}},
    )
    overlay = {"甲→乙": _EDGE_甲乙}
    assert resolve_related_cast({"甲"}, overlay) == ["乙"]


@pytest.mark.asyncio
async def test_recall_node_passes_prior_prose_and_turn_index_to_recall(monkeypatch):
    calls: list[dict] = []

    def spy_recall(text, **kwargs):
        calls.append({"text": text, **kwargs})
        return "", kwargs.get("cooldown") or {}, []

    monkeypatch.setattr("engine.memory_recall.recall.recall_relevant_context", spy_recall)

    await _drain(run_turn(
        "novel-recall-spy", 1, "第一段指令", write_turn=_write_turn, **_with_llms(_call_llm),
    ))
    assert calls[0]["prior_prose"] == ""  # opening round has no prior round
    assert calls[0]["turn_index"] == 0

    await _drain(run_turn(
        "novel-recall-spy", 1, "第二段指令", write_turn=_write_turn, **_with_llms(_call_llm),
    ))
    assert calls[1]["prior_prose"] == "甲抬起头，看向窗外。"  # _write_turn's fixed output
    assert calls[1]["turn_index"] == 1


@pytest.mark.asyncio
async def test_recall_rewrite_node_uses_turns_minus_two_as_prior_prose_and_len_minus_one_as_turn_index(
    monkeypatch,
):
    calls: list[dict] = []

    def spy_recall(text, **kwargs):
        calls.append({"text": text, **kwargs})
        return "", kwargs.get("cooldown") or {}, []

    monkeypatch.setattr("engine.memory_recall.recall.recall_relevant_context", spy_recall)

    await _drain(run_turn(
        "novel-rewrite-recall-spy", 1, "指令0", write_turn=_write_turn, **_with_llms(_call_llm),
    ))
    await _drain(run_turn(
        "novel-rewrite-recall-spy", 1, "指令1", write_turn=_write_turn, **_with_llms(_call_llm),
    ))
    calls.clear()

    from engine.story_sandbox.graph import rewrite_last_round
    await _drain(await rewrite_last_round(
        "novel-rewrite-recall-spy", 1, "重写反馈", write_turn=_write_turn, **_with_llms(_call_llm),
    ))
    assert calls[0]["turn_index"] == 1  # len(turns)=2 at rewrite time, rewriting index 1
    assert calls[0]["prior_prose"] == "甲抬起头，看向窗外。"  # turns[-2]'s prose


@pytest.mark.asyncio
async def test_recall_cooldown_persists_across_rounds_via_checkpointer(monkeypatch):
    monkeypatch.setattr(
        "engine.memory_recall.recall.recall_relevant_context",
        lambda text, **kwargs: ("", {**(kwargs.get("cooldown") or {}), "event:x": kwargs["turn_index"]}, []),
    )
    await _drain(run_turn(
        "novel-cooldown-persist", 1, "指令0", write_turn=_write_turn, **_with_llms(_call_llm),
    ))
    from engine.story_sandbox.graph import peek_state
    state = await peek_state("novel-cooldown-persist", 1)
    assert state["recall_cooldown"] == {"event:x": 0}


@pytest.mark.asyncio
async def test_rewrite_is_not_self_suppressed_by_its_own_round_cooldown(monkeypatch):
    """Regression: a round's own original-write cooldown mark must not gate its own rewrite --
    only cooldown set by strictly earlier rounds should still apply. Stub mirrors
    recall.py::recall_relevant_context's real cooldown-gating contract (item is recalled iff
    turn_index - cooldown.get(item, -COOLDOWN_TURNS) >= COOLDOWN_TURNS) for a single tracked
    item, so this exercises the cooldown-filtering the rewrite node itself does before calling
    recall_relevant_context, not just what recall_relevant_context does internally."""
    COOLDOWN_TURNS = 10
    ITEM = "event:x"

    def stub_recall(text, **kwargs):
        cooldown = kwargs.get("cooldown") or {}
        turn_index = kwargs["turn_index"]
        recalled = turn_index - cooldown.get(ITEM, -COOLDOWN_TURNS) >= COOLDOWN_TURNS
        updated = dict(cooldown)
        if recalled:
            updated[ITEM] = turn_index
        return (ITEM if recalled else ""), updated, []

    monkeypatch.setattr("engine.memory_recall.recall.recall_relevant_context", stub_recall)

    await _drain(run_turn(
        "novel-rewrite-cooldown-self", 1, "指令0", write_turn=_write_turn, **_with_llms(_call_llm),
    ))
    from engine.story_sandbox.graph import peek_state
    state = await peek_state("novel-rewrite-cooldown-self", 1)
    # Sanity: the opening round's own write did recall the item and record its own cooldown mark.
    assert state["turns"][0]["recall_context"] == ITEM
    assert state["recall_cooldown"] == {ITEM: 0}

    from engine.story_sandbox.graph import rewrite_last_round
    await _drain(await rewrite_last_round(
        "novel-rewrite-cooldown-self", 1, "重写反馈", write_turn=_write_turn, **_with_llms(_call_llm),
    ))
    state = await peek_state("novel-rewrite-cooldown-self", 1)
    # Without the fix, the rewrite's turn_index equals the original write's (both are round 0),
    # so the item's own just-recorded cooldown mark (0 - 0 = 0 < COOLDOWN_TURNS) would suppress
    # it here.
    assert state["turns"][0]["recall_context"] == ITEM


@pytest.mark.asyncio
async def test_rewrite_still_respects_cooldown_from_a_genuinely_earlier_round(monkeypatch):
    """Companion to the self-suppression regression above: cooldown marks set by an EARLIER
    round (not the one being rewritten) must still gate the rewrite normally -- the fix only
    exempts a round's own cooldown mark, not all cooldown history."""
    COOLDOWN_TURNS = 10
    ITEM = "event:x"

    def stub_recall(text, **kwargs):
        cooldown = kwargs.get("cooldown") or {}
        turn_index = kwargs["turn_index"]
        recalled = turn_index - cooldown.get(ITEM, -COOLDOWN_TURNS) >= COOLDOWN_TURNS
        updated = dict(cooldown)
        if recalled:
            updated[ITEM] = turn_index
        return (ITEM if recalled else ""), updated, []

    monkeypatch.setattr("engine.memory_recall.recall.recall_relevant_context", stub_recall)

    # Round 0 recalls and cools down the item; round 1 is written fresh (still within the
    # cooldown window, so it does NOT re-recall -- its own write leaves the item's cooldown mark
    # at turn 0, i.e. genuinely from an earlier round relative to round 1).
    await _drain(run_turn(
        "novel-rewrite-cooldown-earlier", 1, "指令0", write_turn=_write_turn, **_with_llms(_call_llm),
    ))
    await _drain(run_turn(
        "novel-rewrite-cooldown-earlier", 1, "指令1", write_turn=_write_turn, **_with_llms(_call_llm),
    ))
    from engine.story_sandbox.graph import peek_state
    state = await peek_state("novel-rewrite-cooldown-earlier", 1)
    assert state["turns"][0]["recall_context"] == ITEM
    assert state["turns"][1]["recall_context"] == ""  # still on cooldown (1 - 0 = 1 < 10)

    from engine.story_sandbox.graph import rewrite_last_round
    await _drain(await rewrite_last_round(
        "novel-rewrite-cooldown-earlier", 1, "重写反馈", write_turn=_write_turn, **_with_llms(_call_llm),
    ))
    state = await peek_state("novel-rewrite-cooldown-earlier", 1)
    # Rewriting round 1 (turn_index=1): round 0's cooldown mark (value 0) is from a genuinely
    # earlier round, not this one, so it must still apply -- the item stays suppressed.
    assert state["turns"][1]["recall_context"] == ""


@pytest.mark.asyncio
async def test_snapshot_then_restore_reverts_state(monkeypatch, tmp_path):
    monkeypatch.setattr("utils.paths.story_sandbox_checkpoint_path", lambda: str(tmp_path / "sandbox.sqlite"))
    g._checkpointers.clear()  # force a fresh checkpointer bound to the tmp path

    checkpointer = await g.ensure_checkpointer("novel1")
    noop = g._compile_noop_graph(checkpointer)
    config = {"configurable": {"thread_id": "novel1:1"}}
    seed = seed_state()
    seed["rolling_summary"] = "开场"
    # ainvoke (not aupdate_state) for the setup writes: a real traversal through START legitimately
    # bumps the checkpoint's __start__ channel version, which is what lets a later bare
    # aupdate_state call (restore_state's own, with no explicit as_node) resolve "who wrote last"
    # unambiguously -- exactly what happens in real usage, where restore_state always runs after
    # at least one real graph turn. Two bare aupdate_state calls in a row on this single-node noop
    # graph never populate that disambiguating version (its node reads no channels), which is a
    # langgraph 1.x quirk of this specific bare-noop-graph test setup, not a production code path.
    await noop.ainvoke(seed, config)

    pre = await g.snapshot_state("novel1", 1, branch_id=LEGACY_BRANCH_ID)
    assert pre["rolling_summary"] == "开场"

    await noop.ainvoke({**seed, "rolling_summary": "中途改动"}, config)
    existing = await noop.aget_state(config)
    assert existing.values["rolling_summary"] == "中途改动"

    await g.restore_state("novel1", 1, pre, branch_id=LEGACY_BRANCH_ID)
    restored = await noop.aget_state(config)
    assert restored.values["rolling_summary"] == "开场"


@pytest.mark.asyncio
async def test_snapshot_on_fresh_thread_returns_empty_dict(monkeypatch, tmp_path):
    monkeypatch.setattr("utils.paths.story_sandbox_checkpoint_path", lambda: str(tmp_path / "sandbox.sqlite"))
    g._checkpointers.clear()

    pre = await g.snapshot_state("novel-fresh", 1)
    assert pre == {}


@pytest.mark.asyncio
async def test_restore_with_empty_snapshot_falls_back_to_seed_state(monkeypatch, tmp_path):
    """An opening-turn cancel has no prior checkpoint -- restore_state({}) must fully clear
    back to seed_state(), not leave whatever partial keys the aborted opening turn wrote."""
    monkeypatch.setattr("utils.paths.story_sandbox_checkpoint_path", lambda: str(tmp_path / "sandbox.sqlite"))
    g._checkpointers.clear()

    checkpointer = await g.ensure_checkpointer("novel2")
    noop = g._compile_noop_graph(checkpointer)
    config = {"configurable": {"thread_id": "novel2:1"}}
    # ainvoke, not aupdate_state -- see comment in test_snapshot_then_restore_reverts_state above.
    await noop.ainvoke({**seed_state(), "rolling_summary": "半成品的开场"}, config)

    await g.restore_state("novel2", 1, {}, branch_id=LEGACY_BRANCH_ID)
    restored = await noop.aget_state(config)
    assert restored.values["rolling_summary"] == seed_state()["rolling_summary"]


@pytest.mark.asyncio
async def test_ensure_checkpointer_concurrent_callers_for_same_novel_share_one_build(monkeypatch, tmp_path):
    monkeypatch.setattr("utils.paths.story_sandbox_checkpoint_path", lambda: str(tmp_path / "sandbox.sqlite"))
    g._checkpointers.clear()
    g._checkpointers_building.clear()

    build_calls = []
    real_open = g._open_checkpointer

    async def counting_open(novel_id: str):
        build_calls.append(novel_id)
        return await real_open(novel_id)

    monkeypatch.setattr(g, "_open_checkpointer", counting_open)

    results = await asyncio.gather(g.ensure_checkpointer("novelA"), g.ensure_checkpointer("novelA"))
    assert build_calls == ["novelA"]
    assert results[0] is results[1]


@pytest.mark.asyncio
async def test_ensure_checkpointer_different_novels_build_independently(monkeypatch, tmp_path):
    """Two different novel_ids each get their own connection, built independently -- no
    single-slot singleton to discard/rebuild when the caller's target novel differs from
    whatever the last caller asked for (the old design's failure mode this replaces)."""
    monkeypatch.setattr("utils.paths.story_sandbox_checkpoint_path", lambda: str(tmp_path / "sandbox.sqlite"))
    g._checkpointers.clear()
    g._checkpointers_building.clear()

    build_calls = []
    real_open = g._open_checkpointer

    async def counting_open(novel_id: str):
        build_calls.append(novel_id)
        return await real_open(novel_id)

    monkeypatch.setattr(g, "_open_checkpointer", counting_open)

    cp_a = await g.ensure_checkpointer("novelA")
    cp_b = await g.ensure_checkpointer("novelB")
    assert build_calls == ["novelA", "novelB"]
    assert cp_a is not cp_b
    # Re-fetching either returns its own cached connection, doesn't rebuild.
    assert await g.ensure_checkpointer("novelA") is cp_a
    assert build_calls == ["novelA", "novelB"]


@pytest.mark.asyncio
async def test_close_checkpointer_with_novel_id_closes_only_that_one(monkeypatch, tmp_path):
    monkeypatch.setattr("utils.paths.story_sandbox_checkpoint_path", lambda: str(tmp_path / "sandbox.sqlite"))
    g._checkpointers.clear()

    await g.ensure_checkpointer("novelA")
    await g.ensure_checkpointer("novelB")
    assert set(g._checkpointers) == {"novelA", "novelB"}

    await g.close_checkpointer("novelA")
    assert set(g._checkpointers) == {"novelB"}


@pytest.mark.asyncio
async def test_run_turn_tracks_active_cast_across_turns(monkeypatch):
    """乙 gets mentioned turn 0's instruction -> appears in active_cast; stays absent for the
    next few turns -> gets pruned after ABSENCE_LIMIT turns without a mention."""
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: ["乙"] if "乙" in text else [],
    )

    async def _no_char_derive_llm(system, _user):
        # Empty character-state responses keep this test isolated to scan_characters-driven
        # active_cast tracking -- derive_char's own alias folding into active_cast is covered
        # separately by test_derive_char_folds_recognized_names_into_active_cast.
        if "剧情摘要助手" in system:
            return "折叠后的摘要"
        if "事件摘要助手" in system:
            return '{"event": "甲抬起头", "time": "对峙之后", "location": "书房", "characters": ["甲"], "entities": []}'
        if "走向建议" in system:
            return '["建议一", "建议二"]'
        if "场景当前的状态" in system or "场景推演出开场时的初始状态" in system:
            return '{"description": "书房"}'
        return "{}"

    async def _drain_full(gen):
        async for _ in gen:
            pass
        from engine.story_sandbox.graph import peek_state
        return await peek_state("novel-active-cast", 1)

    state = await _drain_full(run_turn(
        "novel-active-cast", 1, "乙登场了", write_turn=_write_turn, **_with_llms(_no_char_derive_llm),
    ))
    assert state["active_cast"] == {"乙": 0}

    for _ in range(2):
        state = await _drain_full(run_turn(
            "novel-active-cast", 1, "继续", write_turn=_write_turn, **_with_llms(_no_char_derive_llm),
        ))
        assert "乙" in state["active_cast"]

    state = await _drain_full(run_turn(
        "novel-active-cast", 1, "继续", write_turn=_write_turn, **_with_llms(_no_char_derive_llm),
    ))
    assert "乙" not in state["active_cast"]
    assert state["active_cast"] == {}


@pytest.mark.asyncio
async def test_derive_char_folds_recognized_names_into_active_cast(monkeypatch):
    """The identify LLM call reports who's on stage; derive_char folds those names into
    active_cast so the cast panel sees them even if scan_characters missed them."""
    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: [])
    monkeypatch.setattr("engine.memory_recall.entity_index.build_character_vocab", lambda: {"阿离"})

    async def _alias_llm(system, _user):
        if "剧情摘要助手" in system:
            return "折叠后的摘要"
        if "事件摘要助手" in system:
            return '{"event": "甲抬起头", "time": "对峙之后", "location": "书房", "characters": ["甲"], "entities": []}'
        if "走向建议" in system:
            return '["建议一", "建议二"]'
        if "场景当前的状态" in system or "场景推演出开场时的初始状态" in system:
            return "{}"
        if "为每个角色推演出登场时的初始状态" in system:
            return "{}"
        if "根据这段正文内容" in system:
            return '{"角色": ["阿离"], "路人": []}'
        if "根据导演指令" in system:
            return '{"角色": ["阿离"], "路人": []}'
        return '{"阿离": {"psychology": "羞怯"}}'

    from engine.story_sandbox.graph import peek_state

    await _drain(run_turn(
        "novel-alias-cast", 1, "第一段", write_turn=_write_turn, **_with_llms(_alias_llm),
    ))
    state = await peek_state("novel-alias-cast", 1)
    assert "阿离" in state["active_cast"]


@pytest.mark.asyncio
async def test_derive_char_scopes_prior_states_shown_to_llm_to_active_cast(monkeypatch):
    """Characters outside active_cast must not appear in the derive prompt or the output
    character_states -- they were already gone from the scene."""
    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: ["甲"])
    monkeypatch.setattr("engine.memory_recall.entity_index.build_character_vocab", lambda: {"甲", "乙"})

    async def call_identify(_system, _user):
        return '{"角色": ["甲"], "路人": []}'

    async def call_derive(_system, _user):
        return '{"甲": {"psychology": "内向"}}'

    from engine.story_sandbox.graph import _build_derive_char_node

    node = _build_derive_char_node(0, call_derive, call_identify, _identity_guard_text)
    state = {
        "baseline_states": {"甲": {"psychology": "内向"}, "乙": {"psychology": "旧状态"}},
        "final_text": "甲抬起头，看向窗外。",
        "active_cast": {"甲": 5},
        "turns": [],
    }
    result = await node(state)

    assert "乙" not in result["character_states"]
    assert result["character_states"]["甲"] == {"psychology": "内向"}


@pytest.mark.asyncio
async def test_run_turn_guard_text_persists_derived_char_state():
    from engine.story_sandbox.graph import peek_state

    async def _violating_derive_llm(system: str, user: str) -> str:
        if "根据导演指令" in system or "根据这段正文内容" in system:
            return '{"角色": ["甲"], "路人": []}'
        if "剧情摘要助手" in system:
            return "折叠后的摘要"
        if "事件摘要助手" in system:
            return '{"event": "甲抬起头", "time": "对峙之后", "location": "书房", "characters": ["甲"], "entities": []}'
        if "走向建议" in system:
            return '["建议一", "建议二"]'
        if "场景当前的状态" in system or "场景推演出开场时的初始状态" in system:
            return '{"description": "昏暗的书房"}'
        if "为每个角色推演出登场时的初始状态" in system:
            return '{"甲": {"psychology": "开场"}}'
        return f'{{"甲": {{"psychology": "带着{FORBIDDEN}的心理"}}}}'

    await _drain(run_turn(
        "novel-guard-char", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm),
    ))
    steps = [
        step async for step in run_turn(
            "novel-guard-char", 1, "第二轮", write_turn=_write_turn,
            **_with_llms(_violating_derive_llm, _replace_forbidden_guard),
        )
    ]
    state_step = next(s for s in steps if s["type"] == SandboxStepType.STATE)
    guarded_psychology = state_step["states"]["甲"]["psychology"]
    assert FORBIDDEN not in guarded_psychology
    assert REPLACEMENT in guarded_psychology

    persisted = await peek_state("novel-guard-char", 1)
    assert persisted["character_states"]["甲"]["psychology"] == guarded_psychology


@pytest.mark.asyncio
async def test_run_turn_opening_guard_text_persists_initial_states_and_scene():
    from engine.story_sandbox.graph import peek_state

    async def _violating_init_llm(system: str, user: str) -> str:
        if "为每个角色推演出登场时的初始状态" in system:
            return f'{{"甲": {{"psychology": "初始{FORBIDDEN}"}}}}'
        if "场景推演出开场时的初始状态" in system:
            return f'{{"description": "场景{FORBIDDEN}"}}'
        return await _call_llm(system, user)

    steps = [
        step async for step in run_turn(
            "novel-guard-opening", 1, "第一轮", write_turn=_write_turn,
            **_with_llms(_violating_init_llm, _replace_forbidden_guard),
        )
    ]
    init_step = next(s for s in steps if s["type"] == SandboxStepType.INITIAL_STATE)
    assert FORBIDDEN not in init_step["states"]["甲"]["psychology"]
    assert FORBIDDEN not in init_step["scene_state"]["description"]

    persisted = await peek_state("novel-guard-opening", 1)
    assert persisted["turns"][0]["initial_states"]["甲"]["psychology"] == init_step["states"]["甲"]["psychology"]
    assert (
        persisted["turns"][0]["initial_scene_state"]["description"]
        == init_step["scene_state"]["description"]
    )


@pytest.mark.asyncio
async def test_run_turn_guarded_suggestion_marks_submitted_directions():
    from engine.story_sandbox.graph import peek_state

    async def _violating_suggest_llm(system: str, user: str) -> str:
        if "走向建议" in system:
            return f'["建议含{FORBIDDEN}"]'
        return await _call_llm(system, user)

    await _drain(run_turn(
        "novel-guard-submitted", 1, "第一轮", write_turn=_write_turn,
        **_with_llms(_violating_suggest_llm, _replace_forbidden_guard),
    ))
    state = await peek_state("novel-guard-submitted", 1)
    guarded_suggestion = state["turns"][0]["suggestions"][0]
    assert FORBIDDEN not in guarded_suggestion
    assert REPLACEMENT in guarded_suggestion

    await _drain(run_turn(
        "novel-guard-submitted", 1, f"- {guarded_suggestion}", write_turn=_write_turn,
        **_with_llms(_call_llm, _replace_forbidden_guard),
        submitted_directions=[guarded_suggestion],
    ))
    state = await peek_state("novel-guard-submitted", 1)
    assert state["turns"][0]["submitted_directions"] == [guarded_suggestion]


@pytest.mark.asyncio
async def test_run_turn_guard_text_persists_suggestions():
    from engine.story_sandbox.graph import peek_state

    async def _violating_suggest_llm(system: str, user: str) -> str:
        if "走向建议" in system:
            return f'["建议含{FORBIDDEN}"]'
        return await _call_llm(system, user)

    steps = [
        step async for step in run_turn(
            "novel-guard-suggest", 1, "第一轮", write_turn=_write_turn,
            **_with_llms(_violating_suggest_llm, _replace_forbidden_guard),
        )
    ]
    suggest_step = next(s for s in steps if s["type"] == SandboxStepType.SUGGESTIONS)
    assert FORBIDDEN not in suggest_step["options"][0]

    persisted = await peek_state("novel-guard-suggest", 1)
    assert persisted["turns"][0]["suggestions"] == suggest_step["options"]
    assert persisted["suggestions"] == suggest_step["options"]


@pytest.mark.asyncio
async def test_regenerate_suggestions_guard_text_persists_to_state():
    from engine.story_sandbox.graph import peek_state, regenerate_suggestions

    await _drain(run_turn(
        "novel-guard-regen", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm),
    ))

    async def _violating_suggest_llm(system: str, user: str) -> str:
        if "走向建议" in system:
            return f'["新建议{FORBIDDEN}"]'
        return await _call_llm(system, user)

    result = await regenerate_suggestions(
        "novel-guard-regen", 1, _violating_suggest_llm, guard_text=_replace_forbidden_guard,
    )
    assert FORBIDDEN not in result[0]

    persisted = await peek_state("novel-guard-regen", 1)
    assert persisted["turns"][-1]["suggestions"] == result
    assert persisted["suggestions"] == result


@pytest.mark.asyncio
async def test_rewrite_last_round_guard_text_persists_char_state_and_suggestions():
    from engine.story_sandbox.graph import peek_state, rewrite_last_round

    await _drain(run_turn(
        "novel-guard-rewrite", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm),
    ))

    async def _violating_rewrite_llm(system: str, user: str) -> str:
        if "走向建议" in system:
            return f'["重写建议{FORBIDDEN}"]'
        if "场景当前的状态" in system:
            return '{"description": "昏暗的书房"}'
        return f'{{"甲": {{"psychology": "重写{FORBIDDEN}"}}}}'

    steps = [
        step async for step in await rewrite_last_round(
            "novel-guard-rewrite", 1, "反馈", write_turn=_write_turn,
            **_with_llms(_violating_rewrite_llm, _replace_forbidden_guard),
        )
    ]
    state_step = next(s for s in steps if s["type"] == SandboxStepType.STATE)
    suggest_step = next(s for s in steps if s["type"] == SandboxStepType.SUGGESTIONS)
    assert FORBIDDEN not in state_step["states"]["甲"]["psychology"]
    assert FORBIDDEN not in suggest_step["options"][0]

    persisted = await peek_state("novel-guard-rewrite", 1)
    assert persisted["character_states"]["甲"]["psychology"] == state_step["states"]["甲"]["psychology"]
    assert persisted["turns"][-1]["suggestions"] == suggest_step["options"]
    assert persisted["suggestions"] == suggest_step["options"]


@pytest.mark.asyncio
async def test_init_char_filters_identified_roster_to_present_names(monkeypatch):
    """At the opening turn, the identify layer narrows derive_initial_states' cards (and
    therefore its prompt) down to just the identified-and-resolved roster."""
    monkeypatch.setattr("engine.memory_recall.entity_index.scan_characters", lambda text: [])
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.build_character_vocab", lambda: {"甲", "乙"},
    )

    async def _identify_llm(_system, _user):
        return '{"角色": ["甲"], "路人": []}'  # only 甲 is identified as present at the opening

    seen_init_user = {}

    async def _alias_llm(system, user):
        if "剧情摘要助手" in system:
            return "折叠后的摘要"
        if "事件摘要助手" in system:
            return '{"event": "甲抬起头", "time": "对峙之后", "location": "书房", "characters": ["甲"], "entities": []}'
        if "走向建议" in system:
            return '["建议一", "建议二"]'
        if "场景当前的状态" in system or "场景推演出开场时的初始状态" in system:
            return "{}"
        if "为每个角色推演出登场时的初始状态" in system:
            seen_init_user["user"] = user
            return '{"甲": {"psychology": "警惕"}}'
        return "{}"

    llms = _with_llms(_alias_llm)
    llms["call_llm_identify"] = _identify_llm
    await _drain(run_turn(
        "novel-init-filter", 1, "甲登场", write_turn=_write_turn,
        **llms,
    ))
    assert "角色：甲" in seen_init_user["user"]
    assert "角色：乙" not in seen_init_user["user"]


@pytest.mark.asyncio
async def test_run_turn_puts_dynamic_cast_block_in_packet_not_system(monkeypatch):
    monkeypatch.setattr(
        "engine.story_sandbox.cast.render_dynamic_cast_block",
        lambda active_cast, *, chapter, exclude=None: "## 在场角色档案\n角色：乙",
    )

    seen = {}

    async def _capture_write_turn(system: str, packet: str) -> str:
        seen["system"] = system
        seen["packet"] = packet
        return "正文"

    await _drain(run_turn(
        "novel-cast-to-user-prompt", 1, "继续", write_turn=_capture_write_turn,
        **_with_llms(_call_llm),
    ))
    assert "在场角色档案" in seen["packet"]
    assert "在场角色档案" not in seen["system"]


@pytest.mark.asyncio
async def test_run_turn_puts_related_cast_block_in_packet_not_system(monkeypatch):
    monkeypatch.setattr(
        "engine.story_sandbox.cast.render_related_cast_block",
        lambda names, *, chapter, exclude=None: "## 相关角色档案\n角色：角色甲",
    )

    seen = {}

    async def _capture_write_turn(system: str, packet: str) -> str:
        seen["system"] = system
        seen["packet"] = packet
        return "正文"

    await _drain(run_turn(
        "novel-related-cast-to-user-prompt", 1, "继续", write_turn=_capture_write_turn,
        **_with_llms(_call_llm),
    ))
    assert "相关角色档案" in seen["packet"]
    assert "相关角色档案" not in seen["system"]


@pytest.mark.asyncio
async def test_run_turn_related_cast_comes_from_relationship_graph_connected_to_active_cast(
    monkeypatch,
):
    """End-to-end through the real resolve_related_cast/render_related_cast_block: a character
    with no direct/alias text match still surfaces as background-only context when the
    relationship graph connects them to someone actually present -- this is the graph's real
    intended use in story_sandbox (see relationship_graph.py::related_to_present)."""
    monkeypatch.setattr(
        "engine.story_sandbox.cast.render_dynamic_cast_block",
        lambda active_cast, *, chapter, exclude=None: "## 在场角色档案\n角色：甲",
    )
    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {"甲→角色甲": {
            "from": "甲", "to": "角色甲", "nature": "主人/奴隶", "relationship_anchor": "",
            "from_ref_terms": [], "to_ref_terms": ["废物"],
        }}},
    )

    seen = {}

    async def _capture_write_turn(system: str, packet: str) -> str:
        seen["system"] = system
        seen["packet"] = packet
        return "正文"

    await _drain(run_turn(
        "novel-related-cast-from-graph", 1, "继续", write_turn=_capture_write_turn,
        **_with_llms(_call_llm),
    ))
    assert "相关角色档案" in seen["packet"]
    assert "角色甲" in seen["packet"]
    assert "相关角色档案" not in seen["system"]


@pytest.mark.asyncio
async def test_run_turn_system_prompt_character_states_includes_derive_char_names_in_active_cast(
    monkeypatch,
):
    """Once derive_char reports a character, that name enters active_cast and its dynamic state
    is injected into the next turn's writer prompt -- no chapter-outline cap filters it out."""
    async def call_llm_derive_char(_system, _user):
        return '{"角色甲": {"psychology": "冷漠"}}'

    async def call_llm_identify_first(system, _user):
        if "根据这段正文内容" in system or "根据导演指令" in system:
            return '{"角色": ["角色甲"], "路人": []}'
        return await _call_llm(system, _user)

    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph", lambda: {"groups": {}, "edges": {}},
    )
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.build_character_vocab", lambda: {"角色甲"},
    )
    await _drain(run_turn(
        "novel-present-state-filter", 1, "第一段", write_turn=_write_turn,
        **{**_with_llms(_call_llm), "call_llm_derive_char": call_llm_derive_char,
           "call_llm_identify": call_llm_identify_first},
    ))

    seen = {}

    async def _capture_write_turn(system: str, packet: str) -> str:
        seen["system"] = system
        return "正文"

    await _drain(run_turn(
        "novel-present-state-filter", 1, "继续", write_turn=_capture_write_turn,
        **_with_llms(_call_llm),
    ))
    assert "角色甲" in seen["system"]


@pytest.mark.asyncio
async def test_run_turn_suggest_directions_gets_related_cast_from_relationship_graph(
    monkeypatch,
):
    """The 剧情选项生成 (suggest_directions) LLM call gets the same present-vs-related split as
    the prose prompt and dialogue draft -- a character connected to someone present, but not
    themselves present, is grounding-only context for the suggestion model too, not someone it
    should suggest already acting."""
    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {"甲→角色甲": {
            "from": "甲", "to": "角色甲", "nature": "主人/奴隶", "relationship_anchor": "",
            "from_ref_terms": [], "to_ref_terms": ["废物"],
        }}},
    )

    seen = {}

    async def _suggest_aware_llm(system, user):
        if "走向建议" in system:
            seen["system"] = system
            return "[]"
        return await _call_llm(system, user)

    await _drain(run_turn(
        "novel-suggest-related-cast", 1, "继续", write_turn=_write_turn,
        **_with_llms(_suggest_aware_llm),
    ))
    assert "相关角色档案" in seen["system"]
    assert "角色甲" in seen["system"]
    assert "默认不要让他们出现或行动" in seen["system"]


@pytest.mark.asyncio
async def test_run_turn_puts_recall_block_in_packet_not_system(monkeypatch):
    monkeypatch.setattr(
        "engine.memory_recall.recall.recall_relevant_context",
        lambda text, **kwargs: ("## 相关历史/设定回收\n- 【蛊虫】寄生方式驱动力量", {}, []),
    )

    seen = {}

    async def _capture_write_turn(system: str, packet: str) -> str:
        seen["system"] = system
        seen["packet"] = packet
        return "正文"

    await _drain(run_turn(
        "novel-recall-to-user-prompt", 1, "继续", write_turn=_capture_write_turn,
        **_with_llms(_call_llm),
    ))
    assert "相关历史/设定回收" in seen["packet"]
    assert "相关历史/设定回收" not in seen["system"]


@pytest.mark.asyncio
async def test_run_turn_packet_orders_cast_block_before_recall_block_before_instruction(monkeypatch):
    monkeypatch.setattr(
        "engine.story_sandbox.cast.render_dynamic_cast_block",
        lambda active_cast, *, chapter, exclude=None: "## 在场角色档案\n角色：乙",
    )
    monkeypatch.setattr(
        "engine.memory_recall.recall.recall_relevant_context",
        lambda text, **kwargs: ("## 相关历史/设定回收\n- 召回内容", {}, []),
    )

    seen = {}

    async def _capture_write_turn(system: str, packet: str) -> str:
        seen["packet"] = packet
        return "正文"

    await _drain(run_turn(
        "novel-packet-order", 1, "继续指令本身", write_turn=_capture_write_turn,
        **_with_llms(_call_llm),
    ))
    cast_pos = seen["packet"].index("在场角色档案")
    recall_pos = seen["packet"].index("相关历史/设定回收")
    instruction_pos = seen["packet"].index("导演本轮指令")
    assert cast_pos < recall_pos < instruction_pos


@pytest.mark.asyncio
async def test_rewrite_last_round_puts_cast_and_recall_block_in_packet_not_system(monkeypatch):
    await _drain(run_turn(
        "novel-rewrite-to-user-prompt", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm),
    ))

    monkeypatch.setattr(
        "engine.story_sandbox.cast.render_dynamic_cast_block",
        lambda active_cast, *, chapter, exclude=None: "## 在场角色档案\n角色：乙",
    )
    monkeypatch.setattr(
        "engine.memory_recall.recall.recall_relevant_context",
        lambda text, **kwargs: ("## 相关历史/设定回收\n- 召回内容", {}, []),
    )

    from engine.story_sandbox.graph import rewrite_last_round

    seen = {}

    async def _capture_write_turn(system: str, packet: str) -> str:
        seen["system"] = system
        seen["packet"] = packet
        return "重写后的正文"

    await _drain(await rewrite_last_round(
        "novel-rewrite-to-user-prompt", 1, "反馈", write_turn=_capture_write_turn,
        **_with_llms(_call_llm),
    ))
    assert "在场角色档案" in seen["packet"] and "在场角色档案" not in seen["system"]
    assert "相关历史/设定回收" in seen["packet"] and "相关历史/设定回收" not in seen["system"]


@pytest.mark.asyncio
async def test_run_turn_persists_recalled_settings_onto_its_own_round(monkeypatch):
    monkeypatch.setattr(
        "engine.memory_recall.recall.recall_relevant_context",
        lambda text, **kwargs: (
            "## 相关历史/设定回收\n- 【蛊虫】寄生方式驱动力量",
            kwargs.get("cooldown") or {},
            [{"category": "power_system", "name": "蛊虫", "desc": "寄生方式驱动力量"}],
        ),
    )

    from engine.story_sandbox.graph import peek_state

    await _drain(run_turn(
        "novel-recalled-settings", 1, "他体内的蛊虫", write_turn=_write_turn, **_with_llms(_call_llm),
    ))
    state = await peek_state("novel-recalled-settings", 1)
    assert state["turns"][0]["recalled_settings"] == [
        {"category": "power_system", "name": "蛊虫", "desc": "寄生方式驱动力量"},
    ]


@pytest.mark.asyncio
async def test_run_turn_prose_step_carries_recalled_settings(monkeypatch):
    monkeypatch.setattr(
        "engine.memory_recall.recall.recall_relevant_context",
        lambda text, **kwargs: (
            "召回文本",
            kwargs.get("cooldown") or {},
            [{"category": "factions", "name": "青云门", "desc": "云梦国第一宗门"}],
        ),
    )

    steps = [step async for step in run_turn(
        "novel-recalled-settings-2", 1, "继续", write_turn=_write_turn, **_with_llms(_call_llm),
    )]
    prose_step = next(s for s in steps if s["type"] == SandboxStepType.PROSE)
    assert prose_step["recalled_settings"] == [
        {"category": "factions", "name": "青云门", "desc": "云梦国第一宗门"},
    ]


@pytest.mark.asyncio
async def test_rewrite_last_round_recomputes_recalled_settings(monkeypatch):
    from engine.story_sandbox.graph import peek_state, rewrite_last_round

    monkeypatch.setattr(
        "engine.memory_recall.recall.recall_relevant_context",
        lambda text, **kwargs: ("重写前的召回", kwargs.get("cooldown") or {}, []),
    )
    await _drain(run_turn(
        "novel-recalled-settings-3", 1, "第一轮", write_turn=_write_turn, **_with_llms(_call_llm),
    ))

    monkeypatch.setattr(
        "engine.memory_recall.recall.recall_relevant_context",
        lambda text, **kwargs: (
            "重写后的召回",
            kwargs.get("cooldown") or {},
            [{"category": "races", "name": "人族", "desc": "凡躯"}],
        ),
    )
    await _drain(await rewrite_last_round(
        "novel-recalled-settings-3", 1, "反馈", write_turn=_write_turn, **_with_llms(_call_llm),
    ))

    state = await peek_state("novel-recalled-settings-3", 1)
    assert state["turns"][0]["recalled_settings"] == [
        {"category": "races", "name": "人族", "desc": "凡躯"},
    ]


@pytest.mark.asyncio
async def test_chapter_mode_prior_prose_scanned_name_flows_to_related_cast(monkeypatch):
    """After the non-opening cast redesign (2026-08-12), resolve_cast no longer scans
    prior_prose -- a name scan_characters catches in the prior turn's prose that the identify
    layer didn't confirm present becomes background_cast, which resolve_cast folds into
    related_cast_this_turn (not active_cast). The character may re-enter active_cast only if
    the CURRENT turn's derive_char confirms them present."""
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: ["角色甲"] if "角色甲" in text else [],
    )

    async def _write_turn_with_leaked_name(system: str, packet: str) -> str:
        return "角色甲突然出现在门口。"

    await _drain(run_turn(
        "novel-chapter-scope-guard", 1, "继续", write_turn=_write_turn_with_leaked_name,
        **_with_llms(_call_llm),
    ))

    from engine.story_sandbox.graph import peek_state
    state = await peek_state("novel-chapter-scope-guard", 1)
    assert "角色甲" in state.get("background_cast", [])


@pytest.mark.asyncio
async def test_chapter_mode_active_cast_includes_name_from_this_turns_own_instruction(monkeypatch):
    """A name the DIRECTOR themselves types into this turn's instruction is a deliberate choice
    and must still be allowed onto the stage, even if off-outline."""
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: ["角色甲"] if "角色甲" in text else [],
    )

    steps = [step async for step in run_turn(
        "novel-chapter-scope-guard-2", 1, "角色甲登场", write_turn=_write_turn,
        **_with_llms(_call_llm),
    )]
    prose_step = next(s for s in steps if s["type"] == SandboxStepType.PROSE)
    assert "角色甲" in prose_step["active_cast"]


@pytest.mark.asyncio
async def test_free_mode_prior_prose_scanned_name_flows_to_background_cast(monkeypatch):
    """After the non-opening cast redesign (2026-08-12), free mode follows the same rule as
    chapter mode: a scan_characters hit from prior prose that the identify layer didn't
    confirm present becomes background_cast (not active_cast)."""
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: ["丙"] if "丙" in text else [],
    )

    async def _write_turn_mentions_bing(system: str, packet: str) -> str:
        return "丙从阴影中走出。"

    await _drain(run_turn(
        "novel-free-mode-unrestricted", 0, "开场", write_turn=_write_turn_mentions_bing,
        **_with_llms(_call_llm),
    ))

    from engine.story_sandbox.graph import peek_state
    state = await peek_state("novel-free-mode-unrestricted", 0)
    assert "丙" in state.get("background_cast", [])


@pytest.mark.asyncio
async def test_two_branches_of_same_chapter_have_independent_turns(monkeypatch):
    """Writing a turn to branch 'a' must not appear when peeking branch 'b' of the same chapter."""
    async def call_llm(system, user):
        return '{"summary": "", "event": "", "entities": []}'

    async def write_turn(system, packet):
        return "正文"

    kwargs = dict(
        write_turn=write_turn, call_llm_derive_char=call_llm, call_llm_derive_scene=call_llm,
        call_llm_summary_fold=call_llm, call_llm_event_extract=call_llm, call_llm_profile_mutate=call_llm, call_llm_suggest=call_llm,
        guard_text_derive_char=_identity_guard_text, guard_text_derive_scene=_identity_guard_text,
        guard_text_summary_fold=_identity_guard_text, guard_text_event_extract=_identity_guard_text, guard_text_profile_mutate=_identity_guard_text,
        guard_text_suggest=_identity_guard_text,
    )
    async for _ in run_turn("novel-x", 8, "指令", branch_id="a", **kwargs):
        pass

    state_a = await g.peek_state("novel-x", 8, branch_id="a")
    state_b = await g.peek_state("novel-x", 8, branch_id="b")
    assert len(state_a["turns"]) == 1
    assert len(state_b["turns"]) == 0


@pytest.mark.asyncio
async def test_legacy_branch_id_reads_pre_existing_two_segment_thread(monkeypatch):
    """A thread written under the OLD f'{novel_id}:{chapter}' key (simulating pre-feature data)
    must be readable via branch_id=LEGACY_BRANCH_ID without any migration step."""
    checkpointer = await g.ensure_checkpointer("novel-x")
    graph = g._compile_noop_graph(checkpointer)
    config = {"configurable": {"thread_id": "novel-x:8"}}
    # ainvoke (not aupdate_state) for the setup write -- a real traversal through START bumps the
    # checkpoint's __start__ channel version, which is what lets peek_state's own later bare
    # aupdate_state call (via _ensure_round_ids' id-backfill, since this round has no "id") resolve
    # "who wrote last" unambiguously -- same reason test_snapshot_then_restore_reverts_state uses
    # ainvoke for its setup write instead of a bare aupdate_state.
    await graph.ainvoke({**seed_state(), "turns": [{"instruction": "旧对话", "prose": "旧正文", "character_states": {}, "suggestions": [], "initial_states": None, "scene_state": {}, "initial_scene_state": None}]}, config)

    state_explicit = await g.peek_state("novel-x", 8, branch_id=LEGACY_BRANCH_ID)
    state_default = await g.peek_state("novel-x", 8)
    assert len(state_explicit["turns"]) == 1
    assert state_explicit["turns"][0]["instruction"] == "旧对话"
    assert state_default == state_explicit


@pytest.mark.asyncio
async def test_fork_branch_copies_turns_into_dest_thread(monkeypatch):
    async def call_llm(system, user):
        return '{"summary": "甲登场了", "event": "甲登场", "entities": ["甲"]}'

    async def write_turn(system, packet):
        return "正文"

    kwargs = dict(
        write_turn=write_turn, call_llm_derive_char=call_llm, call_llm_derive_scene=call_llm,
        call_llm_summary_fold=call_llm, call_llm_event_extract=call_llm, call_llm_profile_mutate=call_llm, call_llm_suggest=call_llm,
        guard_text_derive_char=_identity_guard_text, guard_text_derive_scene=_identity_guard_text,
        guard_text_summary_fold=_identity_guard_text, guard_text_event_extract=_identity_guard_text, guard_text_profile_mutate=_identity_guard_text,
        guard_text_suggest=_identity_guard_text,
    )
    async for _ in run_turn("novel-x", 8, "指令", branch_id="src", **kwargs):
        pass

    await g.fork_branch("novel-x", 8, "src", "dest")

    src_state = await g.peek_state("novel-x", 8, branch_id="src")
    dest_state = await g.peek_state("novel-x", 8, branch_id="dest")
    assert len(dest_state["turns"]) == len(src_state["turns"]) == 1
    assert dest_state["turns"][0]["instruction"] == src_state["turns"][0]["instruction"]
    assert dest_state["character_states"] == src_state["character_states"]


@pytest.mark.asyncio
async def test_reset_chapter_on_a_freshly_forked_branch_does_not_raise(monkeypatch):
    """Regression test: fork_branch writes the dest thread's checkpoint via a bare aupdate_state
    (restore_state), never a real graph run -- so its versions_seen stays empty. reset_chapter
    (also a bare aupdate_state, used by delete_story_sandbox_branch) used to omit as_node and rely
    on LangGraph inferring it from versions_seen, which raised InvalidUpdateError('Ambiguous
    update, specify as_node') the moment a forked branch was deleted before ever running a turn
    -- reproduced this exact 500 via the live /api/story-sandbox/branches DELETE endpoint."""
    async def call_llm(system, user):
        return '{"summary": "甲登场了", "event": "甲登场", "entities": ["甲"]}'

    async def write_turn(system, packet):
        return "正文"

    kwargs = dict(
        write_turn=write_turn, call_llm_derive_char=call_llm, call_llm_derive_scene=call_llm,
        call_llm_summary_fold=call_llm, call_llm_event_extract=call_llm, call_llm_profile_mutate=call_llm, call_llm_suggest=call_llm,
        guard_text_derive_char=_identity_guard_text, guard_text_derive_scene=_identity_guard_text,
        guard_text_summary_fold=_identity_guard_text, guard_text_event_extract=_identity_guard_text, guard_text_profile_mutate=_identity_guard_text,
        guard_text_suggest=_identity_guard_text,
    )
    async for _ in run_turn("novel-x", 8, "指令", branch_id="src", **kwargs):
        pass

    await g.fork_branch("novel-x", 8, "src", "dest")

    await g.reset_chapter("novel-x", 8, branch_id="dest")

    dest_state = await g.peek_state("novel-x", 8, branch_id="dest")
    assert dest_state["turns"] == []


@pytest.mark.asyncio
async def test_fork_branch_remaps_event_log_entry_ids_so_they_never_collide(monkeypatch):
    async def call_llm(system, user):
        return '{"summary": "甲登场了", "event": "甲登场", "entities": ["甲"]}'

    async def write_turn(system, packet):
        return "正文"

    kwargs = dict(
        write_turn=write_turn, call_llm_derive_char=call_llm, call_llm_derive_scene=call_llm,
        call_llm_summary_fold=call_llm, call_llm_event_extract=call_llm, call_llm_profile_mutate=call_llm, call_llm_suggest=call_llm,
        guard_text_derive_char=_identity_guard_text, guard_text_derive_scene=_identity_guard_text,
        guard_text_summary_fold=_identity_guard_text, guard_text_event_extract=_identity_guard_text, guard_text_profile_mutate=_identity_guard_text,
        guard_text_suggest=_identity_guard_text,
    )
    async for _ in run_turn("novel-x", 8, "指令", branch_id="src", **kwargs):
        pass

    src_state = await g.peek_state("novel-x", 8, branch_id="src")
    old_id = src_state["turns"][0]["event_log_entries"][0]["id"]

    remap = await g.fork_branch("novel-x", 8, "src", "dest")

    assert old_id in remap
    new_id = remap[old_id]
    assert new_id != old_id

    dest_state = await g.peek_state("novel-x", 8, branch_id="dest")
    assert dest_state["turns"][0]["event_log_entries"][0]["id"] == new_id
    src_state_after = await g.peek_state("novel-x", 8, branch_id="src")
    assert src_state_after["turns"][0]["event_log_entries"][0]["id"] == old_id


@pytest.mark.asyncio
async def test_fork_branch_from_empty_source_is_a_no_op(monkeypatch):
    remap = await g.fork_branch("novel-x", 8, "never-used-source", "dest")
    assert remap == {}
    dest_state = await g.peek_state("novel-x", 8, branch_id="dest")
    assert dest_state["turns"] == []
