"""tests/engine/author_loop/dialogue_mode/test_state_derive.py"""
import pytest
from engine.author_loop.dialogue_mode.state_derive import (
    derive_character_states,
    derive_initial_states,
)
from context.state_derive_schema import build_derive_sys, build_init_sys


async def _llm_returning(raw: str):
    async def _call(system: str, user: str, *a, **k):
        return (raw, 0, 0)
    return _call


@pytest.mark.asyncio
async def test_derive_initial_states_empty_cards_skips_llm_call():
    called = {"n": 0}

    async def _call(system, user, *a, **k):
        called["n"] += 1
        return ("{}", 0, 0)
    out = await derive_initial_states([], "开场梗概", _call)
    assert out == {} and called["n"] == 0


@pytest.mark.asyncio
async def test_derive_initial_states_parses_well_formed_result():
    call = await _llm_returning(
        '{"甲": {"psychology": "紧张", "posture": "站立", "clothing": "校服", '
        '"action": "攥紧衣角", "demeanor": "低头"}}'
    )
    out = await derive_initial_states(
        [{"name": "甲", "card": "人设卡文本"}], "开场梗概", call
    )
    assert out == {"甲": {"psychology": "紧张", "posture": "站立", "clothing": "校服",
                         "action": "攥紧衣角", "demeanor": "低头"}}


@pytest.mark.asyncio
async def test_derive_initial_states_includes_cards_and_stage_description_in_prompt():
    seen = {}

    async def _call(system, user, *a, **k):
        seen["system"] = system
        seen["user"] = user
        return ("{}", 0, 0)
    await derive_initial_states([{"name": "甲", "card": "人设卡ABC"}], "开场梗概XYZ", _call)
    assert "人设卡ABC" in seen["user"]
    assert "开场梗概XYZ" in seen["user"]
    for key in ("psychology", "posture", "clothing", "action", "demeanor"):
        assert key in seen["system"]
    assert "personality" not in seen["system"]


@pytest.mark.asyncio
async def test_derive_character_states_tolerates_malformed_json():
    call = await _llm_returning("不是 JSON")
    out = await derive_character_states({}, "正文", call)
    assert out == {}


@pytest.mark.asyncio
async def test_derive_character_states_tolerates_non_dict_top_level():
    call = await _llm_returning("[1, 2, 3]")
    out = await derive_character_states({}, "正文", call)
    assert out == {}


@pytest.mark.asyncio
async def test_derive_character_states_drops_non_dict_entries():
    call = await _llm_returning('{"甲": {"psychology": "x"}, "乙": "不是dict"}')
    out = await derive_character_states({}, "正文", call)
    assert out == {"甲": {"psychology": "x"}}


@pytest.mark.asyncio
async def test_derive_character_states_includes_prior_states_and_text_in_prompt():
    seen = {}

    async def _call(system, user, *a, **k):
        seen["system"] = system
        seen["user"] = user
        return ("{}", 0, 0)
    await derive_character_states({"甲": {"psychology": "旧"}}, "新正文ABC", _call)
    assert "新正文ABC" in seen["user"]
    assert "旧" in seen["user"]


def test_system_prompts_name_five_fields_not_personality():
    for sys_prompt in (build_init_sys(), build_derive_sys()):
        for key in ("psychology", "posture", "clothing", "action", "demeanor"):
            assert key in sys_prompt
        assert "personality" not in sys_prompt
