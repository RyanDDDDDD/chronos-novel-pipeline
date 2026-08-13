import pytest

from engine.story_sandbox.summary_fold import (
    EventResult,
    FoldResult,
    extract_event,
    extract_events,
    fold_summary,
    fold_turn_into_summary,
)


@pytest.mark.asyncio
async def test_fold_parses_full_json():
    async def call_llm(system, user):
        return (
            '{"summary": "甲已击败乙", "event": "甲在山巅击败了乙",'
            ' "time": "决战之后", "entities": ["甲", "乙"]}'
        )

    result = await fold_turn_into_summary("旧摘要", "新发生的一段", call_llm)
    assert result == FoldResult(
        summary="甲已击败乙", event="甲在山巅击败了乙", time="决战之后",
        entities=["甲", "乙"],
    )


@pytest.mark.asyncio
async def test_fold_degrades_on_invalid_json():
    async def call_llm(system, user):
        return "这不是 JSON，就是一句摘要文本"

    result = await fold_turn_into_summary("旧摘要", "新发生的一段", call_llm)
    assert result == FoldResult(summary="这不是 JSON，就是一句摘要文本")


@pytest.mark.asyncio
async def test_fold_degrades_on_missing_summary_field():
    async def call_llm(system, user):
        return '{"event": "有事件但没摘要字段"}'

    result = await fold_turn_into_summary("旧摘要", "新发生的一段", call_llm)
    assert result.summary == '{"event": "有事件但没摘要字段"}'
    assert result.event is None


@pytest.mark.asyncio
async def test_fold_empty_entities_defaults_to_empty_list():
    async def call_llm(system, user):
        return '{"summary": "普通一段", "event": "没什么大事", "entities": []}'

    result = await fold_turn_into_summary("", "x", call_llm)
    assert result.entities == []


@pytest.mark.asyncio
async def test_fold_parses_location_and_characters():
    async def call_llm(system, user):
        return (
            '{"summary": "甲已击败乙", "event": "甲在山巅击败了乙",'
            ' "time": "决战之后", "location": "山巅", "characters": ["甲", "乙"],'
            ' "entities": ["甲", "乙"]}'
        )

    result = await fold_turn_into_summary("旧摘要", "新发生的一段", call_llm)
    assert result.location == "山巅"
    assert result.characters == ["甲", "乙"]


@pytest.mark.asyncio
async def test_fold_empty_location_defaults_to_none():
    async def call_llm(system, user):
        return '{"summary": "普通一段", "event": "没什么大事", "location": "", "entities": []}'

    result = await fold_turn_into_summary("", "x", call_llm)
    assert result.location is None


@pytest.mark.asyncio
async def test_fold_missing_characters_defaults_to_empty_list():
    async def call_llm(system, user):
        return '{"summary": "普通一段", "event": "没什么大事", "entities": []}'

    result = await fold_turn_into_summary("", "x", call_llm)
    assert result.characters == []


def test_fold_sys_prompt_mentions_location_and_characters():
    from engine.story_sandbox.summary_fold import _FOLD_SYS
    assert "location" in _FOLD_SYS
    assert "characters" in _FOLD_SYS


@pytest.mark.asyncio
async def test_fold_includes_present_roster_hint_in_prompt():
    seen = {}

    async def call_llm(system, user):
        seen["user"] = user
        return '{"summary": "s", "event": "e", "entities": []}'

    await fold_turn_into_summary("旧摘要", "新的一段", call_llm, present=["高木柔柔", "林昭然"])
    assert "高木柔柔" in seen["user"] and "林昭然" in seen["user"]


@pytest.mark.asyncio
async def test_fold_omits_roster_hint_when_present_not_given():
    seen = {}

    async def call_llm(system, user):
        seen["user"] = user
        return '{"summary": "s", "event": "e", "entities": []}'

    await fold_turn_into_summary("旧摘要", "新的一段", call_llm)
    assert "在场角色" not in seen["user"]


@pytest.mark.asyncio
async def test_fold_omits_roster_hint_when_present_is_empty_list():
    """present=[] is a real 'nobody identified this turn' result, not 'no hint available' -- but
    there's nothing useful to list either way, so the hint line is the same as the None case."""
    seen = {}

    async def call_llm(system, user):
        seen["user"] = user
        return '{"summary": "s", "event": "e", "entities": []}'

    await fold_turn_into_summary("旧摘要", "新的一段", call_llm, present=[])
    assert "在场角色" not in seen["user"]


@pytest.mark.asyncio
async def test_fold_summary_returns_plain_text():
    async def call_llm(system, user):
        return "  合并后的摘要  "

    result = await fold_summary("旧摘要", "新发生的一段", call_llm)
    assert result == "合并后的摘要"


@pytest.mark.asyncio
async def test_fold_summary_degrades_to_raw_on_empty_response():
    async def call_llm(system, user):
        return ""

    result = await fold_summary("旧摘要", "新发生的一段", call_llm)
    assert result == ""


@pytest.mark.asyncio
async def test_extract_event_parses_full_json():
    async def call_llm(system, user):
        return (
            '{"event": "甲在山巅击败了乙", "time": "决战之后", "location": "山巅", '
            '"characters": ["甲", "乙"], "entities": ["甲", "乙"]}'
        )

    result = await extract_event("新发生的一段", call_llm)
    assert result == EventResult(
        event="甲在山巅击败了乙", time="决战之后", location="山巅",
        characters=["甲", "乙"], entities=["甲", "乙"],
    )


@pytest.mark.asyncio
async def test_extract_events_parses_events_array():
    async def call_llm(system, user):
        return (
            '{"events": ['
            '{"event": "甲回忆起童年", "time": "闪回", "location": "", "characters": ["甲"], "entities": ["甲"]},'
            '{"event": "乙回忆起师父", "time": "闪回", "location": "", "characters": ["乙"], "entities": ["乙"]}'
            ']}'
        )

    results = await extract_events("新发生的一段", call_llm)
    assert len(results) == 2
    assert results[0].event == "甲回忆起童年"
    assert results[1].event == "乙回忆起师父"


@pytest.mark.asyncio
async def test_extract_events_legacy_single_object_still_works():
    async def call_llm(system, user):
        return '{"event": "甲在山巅击败了乙", "time": "决战之后", "entities": ["甲", "乙"]}'

    results = await extract_events("新发生的一段", call_llm)
    assert len(results) == 1
    assert results[0].event == "甲在山巅击败了乙"
    async def call_llm(system, user):
        return "纯文本，不是 JSON"

    result = await extract_event("新发生的一段", call_llm)
    assert result == EventResult()
