import pytest
from engine.story_sandbox.cast_identify import (
    identify_present_characters,
    identify_present_characters_in_prose,
    remap_state_keys,
    resolve_present_roster,
    resolve_present_roster_in_prose,
    resolve_roster_names,
)
from engine.story_sandbox.derivation_retry import DerivationValidationError


def test_resolve_roster_names_exact_match():
    result = resolve_roster_names(["高木柔柔"], ["高木柔柔", "林昭然"])
    assert result == {"高木柔柔": "高木柔柔"}


def test_resolve_roster_names_shortened_name_resolves_via_substring():
    result = resolve_roster_names(["柔柔"], ["高木柔柔", "林昭然"])
    assert result == {"柔柔": "高木柔柔"}


def test_resolve_roster_names_honorific_suffix_resolves_via_reverse_containment():
    result = resolve_roster_names(["高木柔柔大人"], ["高木柔柔", "林昭然"])
    assert result == {"高木柔柔大人": "高木柔柔"}


def test_resolve_roster_names_ambiguous_hit_drops_to_none():
    result = resolve_roster_names(["柔柔"], ["高木柔柔", "远山柔柔"])
    assert result == {"柔柔": None}


def test_resolve_roster_names_no_hit_drops_to_none():
    result = resolve_roster_names(["路人甲"], ["高木柔柔", "林昭然"])
    assert result == {"路人甲": None}


def test_resolve_roster_names_deduplicates_repeated_raw_names():
    result = resolve_roster_names(["柔柔", "柔柔", "林昭然"], ["高木柔柔", "林昭然"])
    assert result == {"柔柔": "高木柔柔", "林昭然": "林昭然"}


def test_resolve_roster_names_empty_roster_drops_everything():
    result = resolve_roster_names(["高木柔柔"], [])
    assert result == {"高木柔柔": None}


@pytest.mark.asyncio
async def test_identify_present_characters_parses_structured_dict():
    async def call_llm(_system, _user):
        return '{"角色": ["高木柔柔", "林昭然"], "路人": ["路边大爷"]}'

    result = await identify_present_characters(
        "写柔柔和昭然在路边碰到一个卖菜大爷", ["高木柔柔", "林昭然"], call_llm,
    )
    assert result == {"角色": ["高木柔柔", "林昭然"], "路人": ["路边大爷"]}


@pytest.mark.asyncio
async def test_identify_present_characters_tolerates_missing_passerby_key():
    async def call_llm(_system, _user):
        return '{"角色": ["高木柔柔"]}'

    result = await identify_present_characters("指令", ["高木柔柔"], call_llm)
    assert result == {"角色": ["高木柔柔"], "路人": []}


@pytest.mark.asyncio
async def test_identify_present_characters_includes_roster_and_instruction_in_prompt():
    seen = {}

    async def call_llm(_system, user):
        seen["user"] = user
        return '{"角色": [], "路人": []}'

    await identify_present_characters("指令内容", ["高木柔柔"], call_llm)
    assert "高木柔柔" in seen["user"]
    assert "指令内容" in seen["user"]


@pytest.mark.asyncio
async def test_identify_present_characters_tolerates_empty_array():
    async def call_llm(_system, _user):
        return '{"角色": [], "路人": []}'

    result = await identify_present_characters("指令", ["高木柔柔"], call_llm)
    assert result == {"角色": [], "路人": []}


@pytest.mark.asyncio
async def test_identify_present_characters_raises_after_retry_on_malformed_json():
    async def call_llm(_system, _user):
        return "不是JSON"

    with pytest.raises(DerivationValidationError):
        await identify_present_characters("指令", ["高木柔柔"], call_llm)


@pytest.mark.asyncio
async def test_resolve_present_roster_resolves_shortened_names():
    async def call_llm(_system, _user):
        return '{"角色": ["柔柔"], "路人": []}'

    cast_names, passersby = await resolve_present_roster("指令", ["高木柔柔", "林昭然"], call_llm)
    assert cast_names == ["高木柔柔"]
    assert passersby == []


@pytest.mark.asyncio
async def test_resolve_present_roster_drops_unmatched_names_but_keeps_matched():
    async def call_llm(_system, _user):
        return '{"角色": ["柔柔", "路人甲"], "路人": []}'

    cast_names, passersby = await resolve_present_roster("指令", ["高木柔柔", "林昭然"], call_llm)
    assert cast_names == ["高木柔柔"]
    assert passersby == []


@pytest.mark.asyncio
async def test_resolve_present_roster_empty_identification_is_a_real_empty_result():
    async def call_llm(_system, _user):
        return '{"角色": [], "路人": []}'

    result = await resolve_present_roster("指令", ["高木柔柔"], call_llm)
    assert result == ([], [])


@pytest.mark.asyncio
async def test_resolve_present_roster_returns_none_when_roster_empty():
    called = []

    async def call_llm(_system, _user):
        called.append(True)
        return '{"角色": [], "路人": []}'

    result = await resolve_present_roster("指令", [], call_llm)
    assert result is None
    assert called == []


@pytest.mark.asyncio
async def test_resolve_present_roster_returns_none_when_identify_call_fails():
    async def call_llm(_system, _user):
        return "不是JSON"

    result = await resolve_present_roster("指令", ["高木柔柔"], call_llm)
    assert result is None


@pytest.mark.asyncio
async def test_resolve_present_roster_returns_unfiltered_passersby(monkeypatch):
    async def call_llm(_system, _user):
        return '{"角色": ["柔柔"], "路人": ["路边大爷", "  ", "路边大爷"]}'

    cast_names, passersby = await resolve_present_roster("指令", ["高木柔柔"], call_llm)
    assert cast_names == ["高木柔柔"]
    assert passersby == ["路边大爷"]


def test_remap_state_keys_renames_shortened_key_to_canonical():
    states = {"柔柔": {"psychology": "警惕"}}
    result = remap_state_keys(states, ["高木柔柔", "林昭然"])
    assert result == {"高木柔柔": {"psychology": "警惕"}}


def test_remap_state_keys_drops_unmatched_key():
    states = {"路人甲": {"psychology": "平静"}, "柔柔": {"psychology": "警惕"}}
    result = remap_state_keys(states, ["高木柔柔"])
    assert result == {"高木柔柔": {"psychology": "警惕"}}


def test_remap_state_keys_leaves_canonical_keys_unchanged():
    states = {"高木柔柔": {"psychology": "警惕"}}
    result = remap_state_keys(states, ["高木柔柔"])
    assert result == {"高木柔柔": {"psychology": "警惕"}}


def test_remap_state_keys_noop_when_roster_empty():
    states = {"柔柔": {"psychology": "警惕"}}
    result = remap_state_keys(states, [])
    assert result == states


@pytest.mark.asyncio
async def test_identify_present_characters_in_prose_parses_structured_dict():
    async def call_llm(_system, _user):
        return '{"角色": ["高木柔柔", "林昭然"], "路人": ["路边大爷"]}'

    result = await identify_present_characters_in_prose(
        "柔柔和昭然在路边碰到一个卖菜大爷", ["高木柔柔", "林昭然"], call_llm,
    )
    assert result == {"角色": ["高木柔柔", "林昭然"], "路人": ["路边大爷"]}


@pytest.mark.asyncio
async def test_identify_present_characters_in_prose_includes_roster_and_prose_in_prompt():
    seen = {}

    async def call_llm(_system, user):
        seen["user"] = user
        return '{"角色": [], "路人": []}'

    await identify_present_characters_in_prose("这段正文内容", ["高木柔柔"], call_llm)
    assert "高木柔柔" in seen["user"]
    assert "这段正文内容" in seen["user"]


@pytest.mark.asyncio
async def test_resolve_present_roster_in_prose_resolves_shortened_names():
    async def call_llm(_system, _user):
        return '{"角色": ["柔柔"], "路人": []}'

    cast_names, passersby = await resolve_present_roster_in_prose(
        "正文", ["高木柔柔", "林昭然"], call_llm,
    )
    assert cast_names == ["高木柔柔"]
    assert passersby == []


@pytest.mark.asyncio
async def test_resolve_present_roster_in_prose_returns_none_when_roster_empty():
    called = []

    async def call_llm(_system, _user):
        called.append(True)
        return '{"角色": [], "路人": []}'

    result = await resolve_present_roster_in_prose("正文", [], call_llm)
    assert result is None
    assert called == []


@pytest.mark.asyncio
async def test_resolve_present_roster_in_prose_returns_none_when_identify_call_fails():
    async def call_llm(_system, _user):
        return "不是JSON"

    result = await resolve_present_roster_in_prose("正文", ["高木柔柔"], call_llm)
    assert result is None
