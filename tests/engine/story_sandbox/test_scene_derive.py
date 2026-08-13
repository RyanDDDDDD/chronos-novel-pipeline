import pytest
from engine.story_sandbox.derivation_retry import DerivationValidationError
from engine.story_sandbox.scene_derive import derive_initial_scene_state, derive_scene_state


@pytest.mark.asyncio
async def test_derive_initial_scene_state_returns_empty_without_calling_llm_when_instruction_empty():
    called = []

    async def call_llm(_system, _user):
        called.append(True)
        return "{}"

    result = await derive_initial_scene_state("", "世界观", [], call_llm)
    assert result == {}
    assert called == []


@pytest.mark.asyncio
async def test_derive_initial_scene_state_includes_instruction_and_world_summary_in_prompt():
    seen = {}

    async def call_llm(_system, user):
        seen["user"] = user
        return "{}"

    await derive_initial_scene_state("甲把乙推进储物间", "赛博朋克世界观", [], call_llm)
    assert "甲把乙推进储物间" in seen["user"]
    assert "赛博朋克世界观" in seen["user"]


@pytest.mark.asyncio
async def test_derive_initial_scene_state_parses_result():
    async def call_llm(_system, _user):
        return '{"description": "昏暗的储物间", "objects": "纸箱堆到天花板", "atmosphere": "闷热", "disruption": ""}'

    result = await derive_initial_scene_state("随便写点什么", "", [], call_llm)
    assert result == {
        "description": "昏暗的储物间", "objects": "纸箱堆到天花板",
        "atmosphere": "闷热", "disruption": "",
    }


@pytest.mark.asyncio
async def test_derive_initial_scene_state_tolerates_markdown_code_fence():
    async def call_llm(_system, _user):
        return '```json\n{"description": "昏暗的储物间"}\n```'

    result = await derive_initial_scene_state("随便写点什么", "", [], call_llm)
    assert result == {"description": "昏暗的储物间"}


@pytest.mark.asyncio
async def test_derive_initial_scene_state_includes_known_locations_in_prompt_when_present():
    seen = {}

    async def call_llm(_system, user):
        seen["user"] = user
        return "{}"

    await derive_initial_scene_state(
        "随便写点什么", "", ["废弃车站", "青云观"], call_llm,
    )
    assert "已知地点" in seen["user"]
    assert "废弃车站" in seen["user"] and "青云观" in seen["user"]


@pytest.mark.asyncio
async def test_derive_initial_scene_state_omits_known_locations_block_when_empty():
    seen = {}

    async def call_llm(_system, user):
        seen["user"] = user
        return "{}"

    await derive_initial_scene_state("随便写点什么", "", [], call_llm)
    assert "已知地点" not in seen["user"]


@pytest.mark.asyncio
async def test_derive_initial_scene_state_raises_after_retry_on_malformed_json():
    calls = []

    async def call_llm(_system, _user):
        calls.append(1)
        return "不是JSON"

    with pytest.raises(DerivationValidationError):
        await derive_initial_scene_state("随便写点什么", "", [], call_llm)
    assert len(calls) == 3  # _MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_derive_scene_state_raises_after_retry_on_malformed_json():
    async def call_llm(_system, _user):
        return "不是JSON"

    with pytest.raises(DerivationValidationError):
        await derive_scene_state({}, "正文", call_llm)


@pytest.mark.asyncio
async def test_derive_scene_state_raises_after_retry_on_non_dict_json():
    async def call_llm(_system, _user):
        return "[1, 2, 3]"

    with pytest.raises(DerivationValidationError):
        await derive_scene_state({}, "正文", call_llm)


@pytest.mark.asyncio
async def test_derive_scene_state_includes_prior_state_and_text_in_prompt():
    seen = {}

    async def call_llm(_system, user):
        seen["user"] = user
        return "{}"

    await derive_scene_state({"description": "昏暗的储物间"}, "木架被撞倒，纸箱散落一地。", call_llm)
    assert "昏暗的储物间" in seen["user"]
    assert "木架被撞倒，纸箱散落一地。" in seen["user"]


@pytest.mark.asyncio
async def test_derive_scene_state_parses_result():
    async def call_llm(_system, _user):
        return '{"description": "昏暗的储物间", "objects": "木架被撞倒，纸箱散落一地", "atmosphere": "闷热", "disruption": "门被反锁"}'

    result = await derive_scene_state({"description": "昏暗的储物间"}, "正文", call_llm)
    assert result["objects"] == "木架被撞倒，纸箱散落一地"
    assert result["disruption"] == "门被反锁"



def test_scene_fields_schema_has_four_fields():
    from engine.story_sandbox.scene_derive import _DERIVE_SYS, _INIT_SYS

    for sys_prompt in (_INIT_SYS, _DERIVE_SYS):
        for key in ("description", "objects", "atmosphere", "disruption"):
            assert key in sys_prompt
