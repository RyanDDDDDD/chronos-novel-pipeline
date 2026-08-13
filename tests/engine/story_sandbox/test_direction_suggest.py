import pytest
from engine.story_sandbox.direction_suggest import suggest_directions


@pytest.mark.asyncio
async def test_suggest_directions_parses_json_list():
    async def call_llm(_system, _user):
        return '["甲追出去解释", "乙干脆离开现场", "刚好有第三人闯入"]'

    result = await suggest_directions("甲愣住了。", {}, call_llm)
    assert result == ["甲追出去解释", "乙干脆离开现场", "刚好有第三人闯入"]


@pytest.mark.asyncio
async def test_suggest_directions_includes_character_states_in_prompt():
    seen = {}

    async def call_llm(system, _user):
        seen["system"] = system
        return "[]"

    await suggest_directions(
        "甲愣住了。", {"甲": {"psychology": "愤怒", "physiology": "", "clothing": ""}}, call_llm,
    )
    assert "愤怒" in seen["system"]


@pytest.mark.asyncio
async def test_suggest_directions_includes_character_cards_in_prompt():
    seen = {}

    async def call_llm(system, _user):
        seen["system"] = system
        return "[]"

    await suggest_directions(
        "甲愣住了。", {"甲": {"psychology": "愤怒"}}, call_llm,
        cards=[{"name": "甲", "card": "角色：甲（主角）\n人格：外冷内热"}],
    )
    assert "角色人设档案" in seen["system"]
    assert "角色：甲（主角）" in seen["system"]
    assert "人格：外冷内热" in seen["system"]
    assert "愤怒" in seen["system"]


@pytest.mark.asyncio
async def test_suggest_directions_includes_related_cards_under_no_action_header():
    seen = {}

    async def call_llm(system, _user):
        seen["system"] = system
        return "[]"

    await suggest_directions(
        "甲愣住了。", {"甲": {"psychology": "愤怒"}}, call_llm,
        cards=[{"name": "甲", "card": "角色：甲（主角）"}],
        related_cards=[{"name": "司马相如", "card": "角色：司马相如（人设详情）"}],
    )
    assert "角色：司马相如（人设详情）" in seen["system"]
    assert "默认不要让他们出现或行动" in seen["system"]
    cast_pos = seen["system"].index("角色人设档案")
    related_pos = seen["system"].index("相关角色档案")
    assert cast_pos < related_pos


@pytest.mark.asyncio
async def test_suggest_directions_omits_related_cards_section_when_none_given():
    seen = {}

    async def call_llm(system, _user):
        seen["system"] = system
        return "[]"

    await suggest_directions(
        "甲愣住了。", {"甲": {"psychology": "愤怒"}}, call_llm,
        cards=[{"name": "甲", "card": "角色：甲（主角）"}],
    )
    assert "相关角色档案" not in seen["system"]


@pytest.mark.asyncio
async def test_suggest_directions_renders_related_cards_even_without_present_cards():
    seen = {}

    async def call_llm(system, _user):
        seen["system"] = system
        return "[]"

    await suggest_directions(
        "正文", {}, call_llm,
        related_cards=[{"name": "司马相如", "card": "角色：司马相如"}],
    )
    assert "相关角色档案" in seen["system"]
    assert "角色：司马相如" in seen["system"]


@pytest.mark.asyncio
async def test_suggest_directions_omits_cards_section_when_cards_empty():
    seen = {}

    async def call_llm(system, _user):
        seen["system"] = system
        return "[]"

    await suggest_directions("正文", {}, call_llm, cards=[])
    assert "角色人设档案" not in seen["system"]


@pytest.mark.asyncio
async def test_suggest_directions_includes_recall_block_in_prompt():
    seen = {}

    async def call_llm(system, _user):
        seen["system"] = system
        return "[]"

    await suggest_directions(
        "甲愣住了。", {}, call_llm,
        recall_block="## 相关历史/设定回收\n- 【蛊虫】寄生方式驱动力量",
    )
    assert "## 相关历史/设定回收" in seen["system"]
    assert "蛊虫" in seen["system"]


@pytest.mark.asyncio
async def test_suggest_directions_omits_recall_section_when_empty():
    seen = {}

    async def call_llm(system, _user):
        seen["system"] = system
        return "[]"

    await suggest_directions("正文", {}, call_llm)
    assert "设定回收" not in seen["system"]


@pytest.mark.asyncio
async def test_suggest_directions_omits_recall_section_when_blank():
    seen = {}

    async def call_llm(system, _user):
        seen["system"] = system
        return "[]"

    await suggest_directions("正文", {}, call_llm, recall_block="   ")
    assert "设定回收" not in seen["system"]


@pytest.mark.asyncio
async def test_suggest_directions_tolerates_markdown_code_fence():
    async def call_llm(_system, _user):
        return '```json\n["甲追出去解释", "乙干脆离开现场"]\n```'

    result = await suggest_directions("甲愣住了。", {}, call_llm)
    assert result == ["甲追出去解释", "乙干脆离开现场"]


@pytest.mark.asyncio
async def test_suggest_directions_tolerates_malformed_json():
    async def call_llm(_system, _user):
        return "不是JSON"

    result = await suggest_directions("正文", {}, call_llm)
    assert result == []


@pytest.mark.asyncio
async def test_suggest_directions_tolerates_non_list_json():
    async def call_llm(_system, _user):
        return '{"not": "a list"}'

    result = await suggest_directions("正文", {}, call_llm)
    assert result == []


@pytest.mark.asyncio
async def test_suggest_directions_drops_non_string_entries():
    async def call_llm(_system, _user):
        return '["合法建议", 42, null, ""]'

    result = await suggest_directions("正文", {}, call_llm)
    assert result == ["合法建议"]


@pytest.mark.asyncio
async def test_suggest_directions_appends_hint_when_provided():
    seen = {}

    async def call_llm(_system, user):
        seen["user"] = user
        return "[]"

    await suggest_directions("正文", {}, call_llm, hint="往乙这边的反应上靠一点")
    assert "导演的补充提示" in seen["user"]
    assert "往乙这边的反应上靠一点" in seen["user"]


@pytest.mark.asyncio
async def test_suggest_directions_hint_requires_all_four_to_follow_it():
    seen = {}

    async def call_llm(system, user):
        seen["system"] = system
        seen["user"] = user
        return "[]"

    await suggest_directions("正文", {}, call_llm, hint="往乙这边的反应上靠一点")
    # The hint must bind all 4 suggestions, not just inspire one while the rest
    # revert to the system prompt's generic "4 different directions" framing.
    assert "都" in seen["user"]
    assert "不要只有一条贴合" in seen["system"]


@pytest.mark.asyncio
async def test_suggest_directions_omits_hint_section_when_hint_is_empty():
    seen = {}

    async def call_llm(_system, user):
        seen["user"] = user
        return "[]"

    await suggest_directions("正文", {}, call_llm)
    assert "导演的补充提示" not in seen["user"]


@pytest.mark.asyncio
async def test_suggest_directions_omits_hint_section_when_hint_is_blank():
    seen = {}

    async def call_llm(_system, user):
        seen["user"] = user
        return "[]"

    await suggest_directions("正文", {}, call_llm, hint="   ")
    assert "导演的补充提示" not in seen["user"]


@pytest.mark.asyncio
async def test_suggest_directions_keeps_grounding_out_of_user_turn():
    seen = {}

    async def call_llm(system, user):
        seen["system"] = system
        seen["user"] = user
        return "[]"

    await suggest_directions(
        "甲愣住了。", {"甲": {"psychology": "愤怒"}}, call_llm,
        cards=[{"name": "甲", "card": "角色：甲（主角）"}],
    )
    assert "甲愣住了" not in seen["user"]
    assert "愤怒" not in seen["user"]
    assert "角色：甲" not in seen["user"]
    assert seen["user"] == "无补充提示，请直接给出建议。"
    assert "甲愣住了" in seen["system"]


@pytest.mark.asyncio
async def test_suggest_directions_prompts_for_four():
    seen = {}

    async def call_llm(system, _user):
        seen["system"] = system
        return '["一", "二", "三", "四"]'

    await suggest_directions("正文", {}, call_llm)
    assert "4 个" in seen["system"]


@pytest.mark.asyncio
async def test_suggest_directions_returns_four_without_retry_when_first_call_has_four():
    calls = []

    async def call_llm(_system, _user):
        calls.append(1)
        return '["一", "二", "三", "四"]'

    result = await suggest_directions("正文", {}, call_llm)
    assert result == ["一", "二", "三", "四"]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_suggest_directions_retries_once_when_short_and_merges_results():
    responses = iter(['["一", "二"]', '["三", "四", "五"]'])
    calls = []

    async def call_llm(_system, _user):
        calls.append(1)
        return next(responses)

    result = await suggest_directions("正文", {}, call_llm)
    assert result == ["一", "二", "三", "四"]  # merged, de-duped, capped at 4
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_suggest_directions_dedupes_overlap_between_first_call_and_retry():
    responses = iter(['["一", "二"]', '["二", "三"]'])

    async def call_llm(_system, _user):
        return next(responses)

    result = await suggest_directions("正文", {}, call_llm)
    assert result == ["一", "二", "三"]  # only 3 unique after dedup -- no third call


@pytest.mark.asyncio
async def test_suggest_directions_truncates_more_than_four_without_retrying():
    calls = []

    async def call_llm(_system, _user):
        calls.append(1)
        return '["一", "二", "三", "四", "五"]'

    result = await suggest_directions("正文", {}, call_llm)
    assert result == ["一", "二", "三", "四"]
    assert len(calls) == 1
