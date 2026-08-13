import pytest
from engine.story_sandbox.dialogue_draft import draft_dialogue


@pytest.mark.asyncio
async def test_draft_dialogue_returns_empty_string_without_calling_llm_when_no_present_cards():
    calls = []

    async def call_llm(_system, _user):
        calls.append(1)
        return "不该被调用"

    result = await draft_dialogue("继续", [], {}, [], [], call_llm)
    assert result == ""
    assert calls == []


@pytest.mark.asyncio
async def test_draft_dialogue_returns_empty_string_when_only_related_cards_given():
    """related_cards alone never justifies a draft -- with no one confidently present, there is
    no one to write lines/actions for."""
    calls = []

    async def call_llm(_system, _user):
        calls.append(1)
        return "不该被调用"

    result = await draft_dialogue(
        "继续", [], {}, [], [{"name": "司马相如", "card": "角色：司马相如"}], call_llm,
    )
    assert result == ""
    assert calls == []


@pytest.mark.asyncio
async def test_draft_dialogue_returns_stripped_llm_output():
    async def call_llm(_system, _user):
        return "\n甲：你来了。\n乙：（点头）嗯。\n"

    result = await draft_dialogue(
        "继续", [], {"甲": {"psychology": "平静"}},
        [{"name": "甲", "card": "角色：甲"}], [], call_llm,
    )
    assert result == "甲：你来了。\n乙：（点头）嗯。"


@pytest.mark.asyncio
async def test_draft_dialogue_includes_present_cards_in_prompt():
    seen = {}

    async def call_llm(system, _user):
        seen["system"] = system
        return ""

    await draft_dialogue(
        "继续", [], {}, [{"name": "甲", "card": "角色：甲（主角）\n人格：外冷内热"}], [], call_llm,
    )
    assert "角色：甲（主角）" in seen["system"]
    assert "人格：外冷内热" in seen["system"]


@pytest.mark.asyncio
async def test_draft_dialogue_includes_related_cards_under_no_lines_header():
    seen = {}

    async def call_llm(system, _user):
        seen["system"] = system
        return ""

    await draft_dialogue(
        "继续", [], {}, [{"name": "甲", "card": "角色：甲"}],
        [{"name": "司马相如", "card": "角色：司马相如（人设详情）"}], call_llm,
    )
    assert "角色：司马相如（人设详情）" in seen["system"]
    assert "禁止为其安排台词或动作" in seen["system"]
    cast_pos = seen["system"].index("在场角色人设档案")
    related_pos = seen["system"].index("相关角色档案")
    assert cast_pos < related_pos


@pytest.mark.asyncio
async def test_draft_dialogue_omits_related_section_when_no_related_cards():
    seen = {}

    async def call_llm(system, _user):
        seen["system"] = system
        return ""

    await draft_dialogue("继续", [], {}, [{"name": "甲", "card": "角色：甲"}], [], call_llm)
    assert "相关角色档案" not in seen["system"]


@pytest.mark.asyncio
async def test_draft_dialogue_includes_character_states_in_prompt():
    seen = {}

    async def call_llm(system, _user):
        seen["system"] = system
        return ""

    await draft_dialogue(
        "继续", [], {"甲": {"psychology": "愤怒"}},
        [{"name": "甲", "card": "角色：甲"}], [], call_llm,
    )
    assert "愤怒" in seen["system"]


@pytest.mark.asyncio
async def test_draft_dialogue_includes_recent_turns_in_prompt():
    seen = {}

    async def call_llm(system, _user):
        seen["system"] = system
        return ""

    turns = [{"instruction": "写甲的反应", "prose": "甲转身走了。"}]
    await draft_dialogue("继续", turns, {}, [{"name": "甲", "card": "角色：甲"}], [], call_llm)
    assert "写甲的反应" in seen["system"]
    assert "甲转身走了。" in seen["system"]


@pytest.mark.asyncio
async def test_draft_dialogue_puts_instruction_in_user_turn_not_system():
    seen = {}

    async def call_llm(system, user):
        seen["system"] = system
        seen["user"] = user
        return ""

    await draft_dialogue("去质问乙", [], {}, [{"name": "甲", "card": "角色：甲"}], [], call_llm)
    assert "去质问乙" in seen["user"]
    assert "去质问乙" not in seen["system"]


@pytest.mark.asyncio
async def test_draft_dialogue_falls_back_to_placeholder_user_turn_when_instruction_blank():
    seen = {}

    async def call_llm(_system, user):
        seen["user"] = user
        return ""

    await draft_dialogue("   ", [], {}, [{"name": "甲", "card": "角色：甲"}], [], call_llm)
    assert seen["user"] == "本轮无特别指令，请直接续写。"


@pytest.mark.asyncio
async def test_draft_dialogue_renders_turn_count_into_prompt():
    seen = {}

    async def call_llm(system, _user):
        seen["system"] = system
        return ""

    await draft_dialogue(
        "继续", [], {}, [{"name": "甲", "card": "角色：甲"}], [], call_llm, turn_count=5,
    )
    assert "目标写出约 5 行台词" in seen["system"]
    assert "{turn_count}" not in seen["system"]
