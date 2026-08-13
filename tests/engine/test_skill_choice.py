import pytest
from engine.execution.skill_choice import ask_choice, parse_choice_reply


def test_parse_choice_reply_multi():
    assert parse_choice_reply({"choices": [1, 3]}, n=4, multi=True) == [0, 2]


def test_parse_choice_reply_single_skip():
    assert parse_choice_reply({"choice": 0}, n=4, multi=False) == []


def test_parse_choice_reply_single_default_first_when_missing():
    assert parse_choice_reply({}, n=4, multi=False) == [0]


@pytest.mark.asyncio
async def test_ask_choice_auto_when_no_prompt_user():
    async def auto():
        return [1]

    out = await ask_choice(None, skill="plugin", seg={"text": "x"},
                           options=[{"label": "a"}, {"label": "b"}], multi=False, auto_pick=auto)
    assert out == [1]


@pytest.mark.asyncio
async def test_ask_choice_uses_new_channel_signature():
    seen = {}

    async def pu(kind, payload):
        seen["kind"] = kind
        seen["payload"] = payload
        return {"choice": 2}

    out = await ask_choice(pu, skill="plugin", seg={"index": 0, "text": "x", "_beat": 1, "_beats": 3},
                           options=[{"label": "a"}, {"label": "b"}], multi=False, auto_pick=None)
    assert seen["kind"] == "choice"
    assert seen["payload"]["skill"] == "plugin" and seen["payload"]["beat"] == 1
    assert out == [1]
