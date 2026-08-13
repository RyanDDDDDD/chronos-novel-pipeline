import pytest
from engine.story_sandbox.derivation_retry import DerivationValidationError
from engine.story_sandbox.state_derive import (
    derive_character_states,
    derive_initial_states,
    derive_initial_states_from_prose,
)


@pytest.mark.asyncio
async def test_derive_character_states_passes_through_arbitrary_fields():
    async def call_llm(_system, _user):
        return '{"甲": {"personality": "逐渐大胆", "physique": {"面部": "泛红"}, "新字段": "新增内容"}}'

    result = await derive_character_states(
        {"甲": {"personality": "内向"}}, "甲鼓起勇气开口了。", call_llm,
    )
    assert result == {"甲": {"personality": "逐渐大胆", "physique": {"面部": "泛红"}, "新字段": "新增内容"}}


@pytest.mark.asyncio
async def test_derive_character_states_only_reports_mentioned_names():
    async def call_llm(_system, _user):
        return '{"甲": {"personality": "释然"}}'

    result = await derive_character_states(
        {"甲": {}, "乙": {"personality": "平静"}}, "甲松了口气。", call_llm,
    )
    assert "乙" not in result


@pytest.mark.asyncio
async def test_derive_character_states_tolerates_markdown_code_fence():
    async def call_llm(_system, _user):
        return '```json\n{"甲": {"personality": "逐渐大胆"}}\n```'

    result = await derive_character_states({}, "正文", call_llm)
    assert result == {"甲": {"personality": "逐渐大胆"}}


@pytest.mark.asyncio
async def test_derive_character_states_raises_after_retry_on_malformed_json():
    calls = []

    async def call_llm(_system, _user):
        calls.append(1)
        return "不是JSON"

    with pytest.raises(DerivationValidationError):
        await derive_character_states({}, "正文", call_llm)
    assert len(calls) == 3  # _MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_derive_character_states_raises_after_retry_on_non_dict_json():
    async def call_llm(_system, _user):
        return "[1, 2, 3]"

    with pytest.raises(DerivationValidationError):
        await derive_character_states({}, "正文", call_llm)


@pytest.mark.asyncio
async def test_derive_character_states_skips_non_dict_per_character_entries():
    async def call_llm(_system, _user):
        return '{"甲": "不是字典", "乙": {"personality": "合法"}}'

    result = await derive_character_states({}, "正文", call_llm)
    assert result == {"乙": {"personality": "合法"}}


@pytest.mark.asyncio
async def test_derive_initial_states_returns_empty_without_calling_llm_when_no_cards():
    called = []

    async def call_llm(_system, _user):
        called.append(True)
        return "{}"

    result = await derive_initial_states([], "随便写点什么", call_llm)
    assert result == {}
    assert called == []


@pytest.mark.asyncio
async def test_derive_initial_states_includes_cards_and_instruction_in_prompt():
    seen = {}

    async def call_llm(_system, user):
        seen["user"] = user
        return "{}"

    await derive_initial_states(
        [{"name": "甲", "card": "角色：甲（主角）\n人格：外冷内热"}],
        "乙突然破门而入", call_llm,
    )
    assert "外冷内热" in seen["user"]
    assert "乙突然破门而入" in seen["user"]


@pytest.mark.asyncio
async def test_derive_character_states_raises_after_retry_on_invalid_scored_desc(monkeypatch):
    from context.content_packs import StateFieldSpec

    monkeypatch.setattr(
        "context.state_derive_schema.state_derive_fields",
        lambda: [
            StateFieldSpec("psychology", "心理", "text", "情绪·心理 psychology"),
            StateFieldSpec("extra_score", "额外", "scored_desc", "extra scored_desc"),
        ],
    )

    async def call_llm(_system, _user):
        return '{"甲": {"extra_score": {"score": "bad", "desc": ""}}}'

    with pytest.raises(DerivationValidationError):
        await derive_character_states({}, "正文", call_llm)


def test_fields_schema_has_five_fields_not_personality():
    from context.state_derive_schema import build_derive_sys, build_derive_sys_closed, build_init_sys

    for sys_prompt in (build_init_sys(), build_derive_sys(), build_derive_sys_closed()):
        for key in ("psychology", "posture", "clothing", "action", "demeanor"):
            assert key in sys_prompt
        assert "personality" not in sys_prompt
        assert "性格" not in sys_prompt


@pytest.mark.asyncio
async def test_derive_initial_states_parses_result():
    async def call_llm(_system, _user):
        return '{"甲": {"personality": "外冷内热", "psychology": "警惕"}}'

    result = await derive_initial_states([{"name": "甲", "card": "角色：甲"}], "随便写点什么", call_llm)
    assert result == {"甲": {"personality": "外冷内热", "psychology": "警惕"}}


@pytest.mark.asyncio
async def test_derive_initial_states_tolerates_markdown_code_fence():
    async def call_llm(_system, _user):
        return '```json\n{"甲": {"personality": "外冷内热"}}\n```'

    result = await derive_initial_states([{"name": "甲", "card": "角色：甲"}], "随便写点什么", call_llm)
    assert result == {"甲": {"personality": "外冷内热"}}


@pytest.mark.asyncio
async def test_derive_initial_states_raises_after_retry_on_malformed_json():
    async def call_llm(_system, _user):
        return "不是JSON"

    with pytest.raises(DerivationValidationError):
        await derive_initial_states([{"name": "甲", "card": "角色：甲"}], "随便写点什么", call_llm)


@pytest.mark.asyncio
async def test_derive_character_states_closed_set_prompt_includes_present_list():
    seen = {}

    async def call_llm(system, user):
        seen["system"] = system
        seen["user"] = user
        return '{"高木柔柔": {"psychology": "警惕"}}'

    result = await derive_character_states(
        {}, "正文", call_llm, present=["高木柔柔", "林昭然"],
    )
    assert result == {"高木柔柔": {"psychology": "警惕"}}
    assert "高木柔柔" in seen["user"]
    assert "林昭然" in seen["user"]
    assert "在场角色" in seen["system"] or "在场角色" in seen["user"]


@pytest.mark.asyncio
async def test_derive_character_states_present_none_keeps_free_form_prompt():
    seen = {}

    async def call_llm(system, _user):
        seen["system"] = system
        return '{"甲": {"psychology": "警惕"}}'

    from context.state_derive_schema import build_derive_sys

    await derive_character_states({}, "正文", call_llm)
    assert seen["system"] == build_derive_sys()


def test_init_sys_forbids_renaming_and_new_characters():
    from context.state_derive_schema import build_init_sys

    init_sys = build_init_sys()
    assert "不要新增" in init_sys
    assert "照抄" in init_sys


@pytest.mark.asyncio
async def test_derive_initial_states_from_prose_returns_empty_without_cards():
    async def call_llm(_system, _user):
        raise AssertionError("should not be called with no cards")

    result = await derive_initial_states_from_prose([], "正文", call_llm)
    assert result == {}


@pytest.mark.asyncio
async def test_derive_initial_states_from_prose_grounds_on_final_text():
    seen = {}

    async def call_llm(system, user):
        seen["system"] = system
        seen["user"] = user
        return '{"新角色": {"psychology": "警惕"}}'

    cards = [{"name": "新角色", "card": "【新角色】人设档案"}]
    result = await derive_initial_states_from_prose(cards, "这段新写的正文内容", call_llm)
    assert result == {"新角色": {"psychology": "警惕"}}
    assert "人设档案" in seen["user"]
    assert "这段新写的正文内容" in seen["user"]
