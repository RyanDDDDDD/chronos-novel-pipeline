import pytest
from pydantic import ValidationError

from engine.setup_chat import auto_construct as ac


@pytest.fixture(autouse=True)
def _rebuild_character_tool_schemas(monkeypatch):
    """Overrides the conftest fixture of the same name: this file's fixtures use
    武器/流派/身份 instead of a real content pack's mature-content fields, so custom_fields()
    must be patched before add_character/edit_character's args_schema is rebuilt from it."""
    import context.content_packs as cp
    from engine.setup_chat.tool_args import build_add_character_args, build_edit_character_args
    from engine.setup_chat.tools import add_character, edit_character

    monkeypatch.setattr(
        cp,
        "custom_fields",
        lambda: [
            cp.CustomFieldSpec(name="武器", required=True, timeline_delta=True),
            cp.CustomFieldSpec(name="流派", required=True, timeline_delta=True),
            cp.CustomFieldSpec(name="身份", required=True, timeline_delta=True),
        ],
    )
    add_character.args_schema = build_add_character_args()
    edit_character.args_schema = build_edit_character_args()


def _valid_character_json(name: str) -> str:
    import json

    from engine.setup.cast.stance_schema import physique_slots

    data = {
        "given_name": name,
        "role": "配角",
        "gender": "female",
        "causal_anchors": {"渴望": "一句"},
        "physique": {k: "x" for k in physique_slots("female")},
        "clothing_color_palette": ["黑"],
        "clothing_materials": ["棉"],
        "clothing_signature_outfit": "黑色棉质日常常服",
        "clothing_accessories": [],
        "sliders": {
            "投入": {
                "level": 1,
                "text": "登场态",
                "levels": {"0": "a", "1": "b", "2": "c"},
            }
        },
        "race": "",
        "identity_background": "背景",
        "hobbies": [],
        "verbal_tic": "",
        "personality": "人格",
        "武器": "尚待观察",
        "流派": "尚待观察",
        "身份": "尚待观察",
    }
    return json.dumps(data, ensure_ascii=False)


def test_character_outline_args_rejects_duplicate_given_names():
    with pytest.raises(ValidationError):
        ac.CharacterOutlineArgs.model_validate({
            "characters": [
                {"given_name": "甲", "role": "r", "persona": "p"},
                {"given_name": "甲", "role": "r2", "persona": "p2"},
            ],
            "relationships": [],
        })


def test_character_outline_args_rejects_relationship_referencing_unknown_name():
    with pytest.raises(ValidationError):
        ac.CharacterOutlineArgs.model_validate({
            "characters": [{"given_name": "甲", "role": "r", "persona": "p"}],
            "relationships": [{"a": "甲", "b": "乙", "relation": "x"}],
        })


def test_character_outline_args_accepts_valid_relationships():
    args = ac.CharacterOutlineArgs.model_validate({
        "characters": [
            {"given_name": "甲", "role": "r1", "persona": "p1"},
            {"given_name": "乙", "role": "r2", "persona": "p2"},
        ],
        "relationships": [{"a": "甲", "b": "乙", "relation": "x"}],
    })
    assert len(args.characters) == 2
    assert args.relationships[0].a == "甲"


@pytest.mark.asyncio
async def test_plan_character_outline_parses_valid_json_first_try():
    async def call_llm(_system: str, _user: str) -> str:
        return (
            '{"characters": ['
            '{"given_name": "甲", "role": "女主角", "persona": "外冷内热"},'
            '{"given_name": "乙", "role": "男主角", "persona": "嘴硬心软"}],'
            '"relationships": [{"a": "甲", "b": "乙", "relation": "青梅竹马"}]}'
        )

    outline, errors = await ac.plan_character_outline(
        "brief", 2, {"tone": "x", "background": "y", "core_themes": []}, call_llm,
    )
    assert errors == []
    assert outline is not None
    assert [c["given_name"] for c in outline["characters"]] == ["甲", "乙"]
    assert outline["relationships"] == [{"a": "甲", "b": "乙", "relation": "青梅竹马"}]


@pytest.mark.asyncio
async def test_plan_character_outline_uses_standalone_system_prompt():
    seen = {}

    async def call_llm(system: str, user: str) -> str:
        seen["system"] = system
        seen["user"] = user
        return '{"characters": [{"given_name": "甲", "role": "r", "persona": "p"}], "relationships": []}'

    await ac.plan_character_outline("brief 内容", 1, {}, call_llm)
    assert "不得提问" in seen["system"]
    assert "brief 内容" in seen["user"]


@pytest.mark.asyncio
async def test_plan_character_outline_includes_core_theme_desc_in_world_summary():
    seen = {}

    async def call_llm(system: str, user: str) -> str:
        seen["user"] = user
        return '{"characters": [{"given_name": "甲", "role": "r", "persona": "p"}], "relationships": []}'

    world_bible = {
        "tone": "x", "background": "y",
        "core_themes": [{"name": "反抗", "desc": "个体对抗体制"}, {"name": "救赎", "desc": ""}],
    }
    await ac.plan_character_outline("brief", 1, world_bible, call_llm)
    assert "反抗（个体对抗体制）" in seen["user"]
    assert "救赎" in seen["user"]
    assert "救赎（" not in seen["user"]


@pytest.mark.asyncio
async def test_plan_character_outline_retries_on_dangling_relationship_reference():
    calls: list[str] = []

    async def call_llm(_system: str, user: str) -> str:
        calls.append(user)
        if len(calls) == 1:
            return (
                '{"characters": [{"given_name": "甲", "role": "r", "persona": "p"}],'
                '"relationships": [{"a": "甲", "b": "不存在的角色", "relation": "x"}]}'
            )
        return '{"characters": [{"given_name": "甲", "role": "r", "persona": "p"}], "relationships": []}'

    outline, errors = await ac.plan_character_outline("brief", 1, {}, call_llm, max_redo=1)
    assert errors == []
    assert outline is not None
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_plan_character_outline_retries_when_character_count_mismatches():
    calls: list[str] = []

    async def call_llm(_system: str, user: str) -> str:
        calls.append(user)
        if len(calls) == 1:
            return '{"characters": [{"given_name": "甲", "role": "r", "persona": "p"}], "relationships": []}'
        return (
            '{"characters": [{"given_name": "甲", "role": "r", "persona": "p"},'
            '{"given_name": "乙", "role": "r", "persona": "p"}], "relationships": []}'
        )

    outline, errors = await ac.plan_character_outline("brief", 2, {}, call_llm, max_redo=1)
    assert errors == []
    assert outline is not None
    assert len(outline["characters"]) == 2
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_plan_character_outline_exhausts_retries_returns_errors():
    async def call_llm(_system: str, _user: str) -> str:
        return "不是JSON"

    outline, errors = await ac.plan_character_outline("brief", 2, {}, call_llm, max_redo=1)
    assert outline is None
    assert errors != []


@pytest.mark.asyncio
async def test_plan_character_outline_emits_progress():
    from engine.setup_chat.tool_progress import emit_scope

    async def call_llm(_system: str, _user: str) -> str:
        return '{"characters": [{"given_name": "甲", "role": "r", "persona": "p"}], "relationships": []}'

    received: list[dict] = []

    async def fake_emit(ev: dict) -> None:
        received.append(ev)

    async with emit_scope(fake_emit):
        await ac.plan_character_outline("brief", 1, {}, call_llm)

    labels = [e["label"] for e in received]
    assert labels == ["正在规划角色阵容…", "角色阵容已规划"]


def test_character_role_entry_rejects_blank_role():
    with pytest.raises(ValidationError):
        ac.CharacterRoleEntry.model_validate({"given_name": "甲", "role": ""})


def test_character_roles_args_rejects_name_set_mismatch_with_roster():
    with pytest.raises(ValidationError):
        ac.CharacterRolesArgs.model_validate(
            {"characters": [{"given_name": "甲", "role": "r"}], "relationships": []},
            context={"roster_names": {"甲", "乙"}},
        )


@pytest.mark.asyncio
async def test_plan_character_roles_and_relationships_parses_valid_json_first_try():
    async def call_llm(_system: str, _user: str) -> str:
        return (
            '{"characters": [{"given_name": "甲", "role": "女主角"}, '
            '{"given_name": "乙", "role": "男主角"}], '
            '"relationships": [{"a": "甲", "b": "乙", "relation": "青梅竹马"}]}'
        )

    roster = [
        {"given_name": "甲", "personality": "外冷内热", "verbal_tic": ""},
        {"given_name": "乙", "personality": "嘴硬心软", "verbal_tic": ""},
    ]
    result, errors = await ac.plan_character_roles_and_relationships(
        "brief", roster, {"tone": "x", "background": "y", "core_themes": []}, call_llm,
    )
    assert errors == []
    assert result is not None
    assert result["characters"] == [{"given_name": "甲", "role": "女主角"}, {"given_name": "乙", "role": "男主角"}]
    assert result["relationships"] == [{"a": "甲", "b": "乙", "relation": "青梅竹马"}]


@pytest.mark.asyncio
async def test_plan_character_roles_and_relationships_includes_roster_in_prompt():
    seen = {}

    async def call_llm(system: str, user: str) -> str:
        seen["system"] = system
        seen["user"] = user
        return '{"characters": [{"given_name": "甲", "role": "r"}], "relationships": []}'

    roster = [{"given_name": "甲", "personality": "外冷内热", "verbal_tic": "口头禅X"}]
    await ac.plan_character_roles_and_relationships("brief 内容", roster, {}, call_llm)
    assert "不得提问" in seen["system"]
    assert "甲" in seen["user"] and "外冷内热" in seen["user"] and "口头禅X" in seen["user"]
    assert "brief 内容" in seen["user"]


@pytest.mark.asyncio
async def test_plan_character_roles_and_relationships_retries_on_name_set_mismatch():
    calls: list[str] = []
    roster = [{"given_name": "甲", "personality": "p", "verbal_tic": ""}]

    async def call_llm(_system: str, user: str) -> str:
        calls.append(user)
        if len(calls) == 1:
            return '{"characters": [{"given_name": "乙", "role": "r"}], "relationships": []}'
        return '{"characters": [{"given_name": "甲", "role": "r"}], "relationships": []}'

    result, errors = await ac.plan_character_roles_and_relationships(
        "brief", roster, {}, call_llm, max_redo=1,
    )
    assert errors == []
    assert result is not None
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_plan_character_roles_and_relationships_exhausts_retries_returns_errors():
    roster = [{"given_name": "甲", "personality": "p", "verbal_tic": ""}]

    async def call_llm(_system: str, _user: str) -> str:
        return "不是JSON"

    result, errors = await ac.plan_character_roles_and_relationships(
        "brief", roster, {}, call_llm, max_redo=1,
    )
    assert result is None
    assert errors != []


@pytest.mark.asyncio
async def test_plan_character_outline_still_includes_core_theme_desc_after_refactor():
    """Guards the _render_world_summary extraction -- plan_character_outline's existing
    behavior must not change."""
    seen = {}

    async def call_llm(system: str, user: str) -> str:
        seen["user"] = user
        return '{"characters": [{"given_name": "甲", "role": "r", "persona": "p"}], "relationships": []}'

    world_bible = {
        "tone": "x", "background": "y",
        "core_themes": [{"name": "反抗", "desc": "个体对抗体制"}, {"name": "救赎", "desc": ""}],
    }
    await ac.plan_character_outline("brief", 1, world_bible, call_llm)
    assert "反抗（个体对抗体制）" in seen["user"]
    assert "救赎" in seen["user"]


@pytest.fixture(autouse=True)
def _no_world_races(monkeypatch):
    from engine.setup.cast import cast_validator as cv
    monkeypatch.setattr(cv, "_load_world_race_names", lambda: [], raising=False)


def test_parse_extracted_character_text_splits_personality_and_verbal_tic():
    personality, verbal_tic = ac._parse_extracted_character_text("性格：冷静克制\n口癖：随口一句")
    assert personality == "冷静克制"
    assert verbal_tic == "随口一句"


def test_parse_extracted_character_text_normalizes_placeholder_to_empty():
    personality, verbal_tic = ac._parse_extracted_character_text("性格：（无）\n口癖：（无）")
    assert personality == ""
    assert verbal_tic == ""


def test_load_imported_characters_ranks_by_mention_count_and_caps(monkeypatch):
    from repositories import get_research_repo
    from repositories.entities import ResearchChunk

    chunks = [
        ResearchChunk(text="性格：路人甲\n口癖：（无）", topic="路人甲", category="character", mention_count=1),
        ResearchChunk(text="性格：主角气质\n口癖：口头禅A", topic="主角", category="character", mention_count=9),
        ResearchChunk(text="性格：配角\n口癖：（无）", topic="配角", category="character", mention_count=4),
    ]
    monkeypatch.setattr(get_research_repo(), "get_chunks", lambda category, topic=None: chunks)
    roster = ac._load_imported_characters(cap=2)
    assert [r["given_name"] for r in roster] == ["主角", "配角"]
    assert roster[0]["personality"] == "主角气质"
    assert roster[0]["verbal_tic"] == "口头禅A"


def test_load_imported_characters_returns_empty_when_no_extraction(monkeypatch):
    from repositories import get_research_repo

    monkeypatch.setattr(get_research_repo(), "get_chunks", lambda category, topic=None: [])
    assert ac._load_imported_characters(cap=5) == []


def _valid_world_json() -> str:
    return (
        '{"tone": "暗黑奇幻", "background": "一句话立意。乱世将至。", '
        '"factions": [{"name": "赤旗军", "desc": "反抗军"}], '
        '"geography": [{"name": "灰烬荒原", "desc": "废土"}], '
        '"races": [{"name": "人族", "desc": "凡躯"}], '
        '"power_system": [{"name": "血契", "desc": "以血为誓的力量体系"}], '
        '"core_themes": [{"name": "反抗", "desc": "个体对抗体制"}]}'
    )


@pytest.fixture(autouse=True)
def _auto_review_gates_pass(monkeypatch):
    """AUTO construct tests assume schema validation unless a test overrides gate_*.explicitly."""

    async def _accept_world(_bible, *, novel_brief=None):
        return True, ""

    async def _accept_character(_char, *, novel_brief=None):
        return True, ""

    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.gate_world_bible", _accept_world,
    )
    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.gate_character", _accept_character,
    )


@pytest.mark.asyncio
async def test_build_world_accepts_on_first_schema_pass_without_inline_gate(monkeypatch):
    llm_calls: list[str] = []

    async def call_llm(_system: str, user: str) -> str:
        llm_calls.append(user)
        return _valid_world_json()

    bible, errors = await ac.build_world("brief", call_llm)
    assert errors == []
    assert bible is not None
    assert len(llm_calls) == 1


@pytest.mark.asyncio
async def test_build_world_schema_pass_does_not_run_inline_gate(monkeypatch):
    async def call_llm(_system: str, _user: str) -> str:
        return _valid_world_json()

    async def always_advise(_bible, *, novel_brief=None):
        raise AssertionError("build_world should not call gate_world_bible inline")

    monkeypatch.setattr("engine.setup_chat.setup_quality_review.gate_world_bible", always_advise)

    bible, errors = await ac.build_world("brief", call_llm)
    assert bible is not None
    assert errors == []


@pytest.mark.asyncio
async def test_draft_one_character_review_regen_fails_once_then_accepts(monkeypatch):
    gate_calls = {"n": 0}
    llm_calls: list[str] = []

    async def call_llm(_system: str, user: str) -> str:
        llm_calls.append(user)
        return _valid_character_json("甲")

    async def fake_gate(_char, *, novel_brief=None):
        gate_calls["n"] += 1
        if gate_calls["n"] == 1:
            return False, "设定质量评审未通过，未写入。\n\n【因果锚点】\n锚点不够具体"
        return True, ""

    monkeypatch.setattr("engine.setup_chat.setup_quality_review.gate_character", fake_gate)

    fields, error = await ac._draft_one_character(
        "brief", {"given_name": "甲", "role": "配角", "persona": "人设"}, "", call_llm, max_redo=0,
    )
    assert error is None
    assert fields is not None
    assert gate_calls["n"] == 2
    assert len(llm_calls) == 2
    assert "锚点不够具体" in llm_calls[1]


@pytest.mark.asyncio
async def test_build_characters_review_regen_single_final_write(monkeypatch):
    """Gate fail once in draft regen, then accept — only one disk write."""
    gate_calls = {"n": 0}
    write_calls = {"n": 0}

    async def call_llm(_system: str, user: str) -> str:
        name = user.split("姓名=", 1)[1].split("，")[0]
        return _valid_character_json(name)

    async def fake_gate(_char, *, novel_brief=None):
        gate_calls["n"] += 1
        if gate_calls["n"] == 1:
            return False, "设定质量评审未通过，未写入。\n\n【测试维度】\n请补全"
        return True, ""

    monkeypatch.setattr("engine.setup_chat.setup_quality_review.gate_character", fake_gate)

    async def fake_add_character(**kwargs):
        write_calls["n"] += 1
        return True, "ok", {**kwargs}

    monkeypatch.setattr(ac, "_add_character_core", fake_add_character)

    outline = {
        "characters": [{"given_name": "甲", "role": "r", "persona": "p"}],
        "relationships": [],
    }
    chars, errors = await ac.build_characters("brief", outline, call_llm, max_redo=0)
    assert errors == []
    assert len(chars) == 1
    assert gate_calls["n"] == 2  # draft fail, draft pass (write bypasses gate via mock)
    assert write_calls["n"] == 1


@pytest.mark.asyncio
async def test_build_world_parses_valid_json_first_try():
    async def call_llm(_system: str, _user: str) -> str:
        return _valid_world_json()

    bible, errors = await ac.build_world("暗黑奇幻，反抗军对抗帝国", call_llm)
    assert errors == []
    assert bible is not None
    assert bible["tone"] == "暗黑奇幻"
    assert bible["factions"] == [{"name": "赤旗军", "desc": "反抗军", "keywords": []}]


@pytest.mark.asyncio
async def test_build_world_uses_standalone_one_shot_system_prompt():
    """Not the interactive world-interview skill -- that skill instructs the model to ask one
    dimension at a time and wait for the user, which conflicts with this single completion
    call needing the complete JSON immediately (see _WORLD_SYSTEM's own wording)."""
    seen = {}

    async def call_llm(system: str, user: str) -> str:
        seen["system"] = system
        seen["user"] = user
        return "{}"

    await ac.build_world("brief 内容", call_llm)
    assert seen["system"] == ac._WORLD_SYSTEM
    assert "不得提问" in seen["system"] and "不得等待用户确认" in seen["system"]
    assert "brief 内容" in seen["user"]


@pytest.mark.asyncio
async def test_build_world_retries_on_validation_failure_then_succeeds():
    calls: list[str] = []

    async def call_llm(_system: str, user: str) -> str:
        calls.append(user)
        if len(calls) == 1:
            return '{"tone": "暗黑"}'  # missing required fields -> Pydantic validation fails
        return (
            '{"tone": "暗黑奇幻", "background": "立意。背景。", '
            '"factions": [{"name": "赤旗军", "desc": "反抗军"}], '
            '"geography": [{"name": "灰烬荒原", "desc": "废土"}], '
            '"races": [{"name": "人族", "desc": "凡躯"}], '
            '"power_system": [{"name": "血契", "desc": "以血为誓"}], '
            '"core_themes": [{"name": "反抗", "desc": "个体对抗体制"}]}'
        )

    bible, errors = await ac.build_world("brief", call_llm, max_redo=2)
    assert errors == []
    assert bible is not None
    assert len(calls) == 2
    # Second attempt's prompt must carry the first attempt's validation feedback.
    assert "未通过" in calls[1] or "校验" in calls[1] or "字段" in calls[1].lower() or "field" in calls[1].lower()


@pytest.mark.asyncio
async def test_build_world_exhausts_retries_returns_errors():
    async def call_llm(_system: str, _user: str) -> str:
        return "不是JSON"

    bible, errors = await ac.build_world("brief", call_llm, max_redo=1)
    assert bible is None
    assert errors != []


def test_load_imported_world_reference_renders_bullet_list(monkeypatch):
    from repositories import get_research_repo
    from repositories.entities import ResearchChunk

    chunks = [ResearchChunk(text="九品炼气修炼体系", category="world"),
              ResearchChunk(text="天启历三千年", category="world")]
    monkeypatch.setattr(get_research_repo(), "get_chunks", lambda category, topic=None: chunks)
    ref = ac._load_imported_world_reference()
    assert "九品炼气修炼体系" in ref and "天启历三千年" in ref


def test_load_imported_world_reference_empty_when_no_extraction(monkeypatch):
    from repositories import get_research_repo

    monkeypatch.setattr(get_research_repo(), "get_chunks", lambda category, topic=None: [])
    assert ac._load_imported_world_reference() == ""


@pytest.mark.asyncio
async def test_build_world_includes_reference_text_when_provided():
    seen = {}

    async def call_llm(_system: str, user: str) -> str:
        seen["user"] = user
        return "{}"

    await ac.build_world("brief", call_llm, reference_text="九品炼气修炼体系")
    assert "九品炼气修炼体系" in seen["user"]


@pytest.mark.asyncio
async def test_build_world_user_message_unchanged_when_reference_text_empty():
    seen = {}

    async def call_llm(_system: str, user: str) -> str:
        if "user" not in seen:
            seen["user"] = user
        return "{}"

    await ac.build_world("brief 内容", call_llm, max_redo=0)
    assert seen["user"] == "brief 内容"


@pytest.mark.asyncio
async def test_build_characters_drafts_within_batch_concurrently_writes_sequentially(monkeypatch):
    """Core correctness test: within one batch, all LLM drafting calls may run concurrently,
    but add_character (the actual disk write) must never have two in-flight at once -- JsonStore
    has no atomic append, concurrent writes would silently lose characters."""
    draft_order: list[str] = []
    write_order: list[str] = []
    in_flight_writes = 0
    max_concurrent_writes = 0

    async def call_llm(_system: str, user: str) -> str:
        name = user.split("姓名=", 1)[1].split("，")[0]
        draft_order.append(name)
        return _valid_character_json(name)

    async def fake_add_character(**kwargs):
        nonlocal in_flight_writes, max_concurrent_writes
        in_flight_writes += 1
        max_concurrent_writes = max(max_concurrent_writes, in_flight_writes)
        write_order.append(kwargs["given_name"])
        in_flight_writes -= 1
        return True, "ok", {**kwargs}

    monkeypatch.setattr(ac, "_add_character_core", fake_add_character)

    outline = {
        "characters": [
            {"given_name": f"角色{i}", "role": "配角", "persona": "人设"} for i in range(5)
        ],
        "relationships": [],
    }
    chars, errors = await ac.build_characters("brief", outline, call_llm, batch_size=3)
    assert errors == []
    assert len(chars) == 5
    assert max_concurrent_writes == 1  # never more than one write in flight at a time
    assert write_order == ["角色0", "角色1", "角色2", "角色3", "角色4"]


@pytest.mark.asyncio
async def test_build_characters_includes_relationship_text_in_prompt(monkeypatch):
    seen_users: list[str] = []

    async def call_llm(_system: str, user: str) -> str:
        seen_users.append(user)
        name = user.split("姓名=", 1)[1].split("，")[0]
        return _valid_character_json(name)

    async def fake_add_character(**kwargs):
        return True, "ok", {**kwargs}

    monkeypatch.setattr(ac, "_add_character_core", fake_add_character)

    outline = {
        "characters": [
            {"given_name": "甲", "role": "女主角", "persona": "外冷内热"},
            {"given_name": "乙", "role": "男主角", "persona": "嘴硬心软"},
        ],
        "relationships": [{"a": "甲", "b": "乙", "relation": "青梅竹马，互相隐瞒身世"}],
    }
    await ac.build_characters("brief", outline, call_llm, batch_size=2)
    jia_user = next(u for u in seen_users if "姓名=甲" in u)
    assert "青梅竹马" in jia_user


@pytest.mark.asyncio
async def test_build_characters_skips_failed_character_keeps_rest(monkeypatch):
    async def call_llm(_system: str, user: str) -> str:
        return "不是JSON"  # every draft fails validation

    monkeypatch.setattr(ac, "_add_character_core", None)  # must never be called for a failed draft

    outline = {
        "characters": [
            {"given_name": "甲", "role": "r", "persona": "p"},
            {"given_name": "乙", "role": "r", "persona": "p"},
        ],
        "relationships": [],
    }
    chars, errors = await ac.build_characters("brief", outline, call_llm, batch_size=2, max_redo=0)
    assert chars == []
    assert len(errors) == 2


@pytest.mark.asyncio
async def test_build_chapters_runs_strictly_sequentially_with_rolling_summary(monkeypatch):
    seen_users: list[str] = []
    written_order: list[int] = []

    async def call_llm(_system: str, user: str) -> str:
        seen_users.append(user)
        idx = len(seen_users)
        return (
            f'{{"title": "第{idx}章", "core_xp": ["基调"], '
            f'"stages": [{{"title": "场景", "location": "地点", "description": "事件"}}]}}'
        )

    async def fake_generate_one_chapter(**kwargs):
        written_order.append(kwargs["chapter_index"])
        return True, "已追加第X章"

    monkeypatch.setattr(ac, "_generate_one_chapter_core", fake_generate_one_chapter)

    written, errors = await ac.build_chapters("brief", ["甲", "乙"], 3, call_llm)
    assert errors == []
    assert written == 3
    assert written_order == [1, 2, 3]
    # Chapter 2's prompt must carry chapter 1's rolling summary forward.
    assert "第1章" in seen_users[1] or "甲" in seen_users[1]


@pytest.mark.asyncio
async def test_build_chapters_skips_failed_chapter_continues(monkeypatch):
    calls = {"n": 0}

    async def call_llm(_system: str, _user: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "不是JSON"  # chapter 1 fails every retry
        return '{"title": "章", "core_xp": ["基调"], "stages": [{"title": "s", "location": "l", "description": "d"}]}'

    written_chapters: list[int] = []

    async def fake_generate_one_chapter(**kwargs):
        written_chapters.append(kwargs["chapter_index"])
        return True, "ok"

    monkeypatch.setattr(ac, "_generate_one_chapter_core", fake_generate_one_chapter)

    written, errors = await ac.build_chapters("brief", ["甲"], 2, call_llm, max_redo=0)
    assert written == 1
    assert len(errors) == 1
    assert written_chapters == [2]  # chapter 1 skipped, chapter 2 still attempted and written


@pytest.mark.asyncio
async def test_run_auto_build_summarizes_world_character_chapter_results(monkeypatch):
    monkeypatch.setattr(ac, "_load_imported_world_reference", lambda: "")
    monkeypatch.setattr(ac, "_load_imported_plot_reference", lambda: "")
    monkeypatch.setattr(ac, "_load_imported_characters", lambda cap: [])
    monkeypatch.setattr(ac, "build_world", lambda brief, call_llm, **kw: (
        _async_return(({"tone": "x", "background": "y", "factions": [], "geography": [],
                        "races": [], "power_system": [], "core_themes": []}, []))
    ))
    monkeypatch.setattr(ac, "_construct_world_core", lambda **kw: _async_return(None))
    monkeypatch.setattr(ac, "plan_character_outline", lambda *a, **kw: _async_return(
        ({"characters": [], "relationships": []}, [])
    ))
    monkeypatch.setattr(ac, "build_characters", lambda *a, **kw: _async_return(
        ([{"given_name": "甲"}, {"given_name": "乙"}], ["角色丙失败：xxx"])
    ))
    monkeypatch.setattr(ac, "build_chapters", lambda *a, **kw: _async_return((5, [])))

    summary = await ac.run_auto_build("brief", 3, 5, _fake_call_llm)
    assert "世界观已建" in summary
    assert "2" in summary and "3" in summary  # 2 succeeded out of 3 requested
    assert "5" in summary  # 5 chapters


async def _fake_call_llm(_system: str, _user: str) -> str:
    return "{}"


async def _async_return(value):
    return value


@pytest.mark.asyncio
async def test_build_world_emits_progress_inside_scope(monkeypatch):
    from engine.setup_chat.tool_progress import emit_scope

    async def call_llm(_system: str, _user: str) -> str:
        return (
            '{"tone": "暗黑奇幻", "background": "一句话立意。乱世将至。", '
            '"factions": [{"name": "赤旗军", "desc": "反抗军"}], '
            '"geography": [{"name": "灰烬荒原", "desc": "废土"}], '
            '"races": [{"name": "人族", "desc": "凡躯"}], '
            '"power_system": [{"name": "血契", "desc": "以血为誓的力量体系"}], '
            '"core_themes": [{"name": "反抗", "desc": "个体对抗体制"}]}'
        )

    received: list[dict] = []

    async def fake_emit(ev: dict) -> None:
        received.append(ev)

    async with emit_scope(fake_emit):
        await ac.build_world("brief", call_llm)

    labels = [e["label"] for e in received]
    assert labels == ["正在构建世界观…", "世界观已构建"]


@pytest.mark.asyncio
async def test_build_characters_emits_progress_per_character(monkeypatch):
    from engine.setup_chat.tool_progress import emit_scope

    async def call_llm(_system: str, user: str) -> str:
        name = user.split("姓名=", 1)[1].split("，")[0]
        return _valid_character_json(name)

    async def fake_add_character(**kwargs):
        return True, "ok", {**kwargs}

    monkeypatch.setattr(ac, "_add_character_core", fake_add_character)

    received: list[dict] = []

    async def fake_emit(ev: dict) -> None:
        received.append(ev)

    outline = {
        "characters": [
            {"given_name": "甲", "role": "r", "persona": "p"},
            {"given_name": "乙", "role": "r", "persona": "p"},
        ],
        "relationships": [],
    }
    async with emit_scope(fake_emit):
        await ac.build_characters("brief", outline, call_llm, batch_size=2)

    labels = [e["label"] for e in received]
    assert len(labels) == 2
    assert labels[0].startswith("角色 1/2")
    assert labels[1].startswith("角色 2/2")


@pytest.mark.asyncio
async def test_build_characters_emits_progress_for_failed_draft(monkeypatch):
    from engine.setup_chat.tool_progress import emit_scope

    async def call_llm(_system: str, _user: str) -> str:
        return "不是JSON"

    received: list[dict] = []

    async def fake_emit(ev: dict) -> None:
        received.append(ev)

    outline = {"characters": [{"given_name": "甲", "role": "r", "persona": "p"}], "relationships": []}
    async with emit_scope(fake_emit):
        await ac.build_characters("brief", outline, call_llm, batch_size=1, max_redo=0)

    assert len(received) == 1
    assert "失败已跳过" in received[0]["label"]
    assert received[0]["label"].startswith("角色 1/1")


@pytest.mark.asyncio
async def test_build_chapters_emits_progress_per_chapter(monkeypatch):
    from engine.setup_chat.tool_progress import emit_scope

    async def call_llm(_system: str, _user: str) -> str:
        return '{"title": "章", "core_xp": ["基调"], "stages": [{"title": "s", "location": "l", "description": "d"}]}'

    async def fake_generate_one_chapter(**kwargs):
        return True, "ok"

    monkeypatch.setattr(ac, "_generate_one_chapter_core", fake_generate_one_chapter)

    received: list[dict] = []

    async def fake_emit(ev: dict) -> None:
        received.append(ev)

    async with emit_scope(fake_emit):
        await ac.build_chapters("brief", ["甲"], 2, call_llm)

    labels = [e["label"] for e in received]
    assert len(labels) == 2
    assert labels[0].startswith("章节 1/2")
    assert labels[1].startswith("章节 2/2")


@pytest.mark.asyncio
async def test_build_chapters_emits_progress_for_failed_chapter(monkeypatch):
    from engine.setup_chat.tool_progress import emit_scope

    async def call_llm(_system: str, _user: str) -> str:
        return "不是JSON"

    received: list[dict] = []

    async def fake_emit(ev: dict) -> None:
        received.append(ev)

    async with emit_scope(fake_emit):
        await ac.build_chapters("brief", ["甲"], 1, call_llm, max_redo=0)

    assert len(received) == 1
    assert "失败已跳过" in received[0]["label"]
    assert received[0]["label"].startswith("章节 1/1")


@pytest.mark.asyncio
async def test_build_chapters_short_circuits_when_character_names_empty():
    """If build_characters produced zero characters, generate_one_chapter would fail every
    single chapter identically (load_plot_grounding hard-requires a non-empty cast) -- must
    not burn chapter_count LLM calls discovering that N times over."""
    calls = 0

    async def call_llm(_system: str, _user: str) -> str:
        nonlocal calls
        calls += 1
        return "{}"

    written, errors = await ac.build_chapters("brief", [], 6, call_llm)
    assert written == 0
    assert calls == 0
    assert len(errors) == 1
    assert "角色" in errors[0]


@pytest.mark.asyncio
async def test_build_chapters_survives_generate_one_chapter_raising(monkeypatch):
    """A chapter that fails during the actual write (e.g. load_plot_grounding raising
    ValueError on an empty on-disk cast, or any other unexpected error) must be skipped like
    any other chapter failure -- never crash the whole auto_build_setup call."""
    async def call_llm(_system: str, _user: str) -> str:
        return (
            '{"title": "章", "core_xp": ["基调"], '
            '"stages": [{"title": "s", "location": "l", "description": "d"}]}'
        )

    async def raising_generate_one_chapter(**kwargs):
        raise ValueError("当前小说没有角色（character_lore_library 为空），请先「构建人物设定」")

    monkeypatch.setattr(ac, "_generate_one_chapter_core", raising_generate_one_chapter)

    written, errors = await ac.build_chapters("brief", ["甲"], 2, call_llm)
    assert written == 0
    assert len(errors) == 2
    assert all("写入失败" in e for e in errors)


@pytest.mark.asyncio
async def test_draft_one_character_tells_the_llm_the_worlds_races(monkeypatch):
    """collect_character_field_errors hard-requires race to match one of the world's declared
    races -- the draft prompt must say what they are up front rather than making the LLM
    discover them only from a validation-failure round-trip."""
    seen = {}

    async def call_llm(system: str, user: str) -> str:
        seen["system"] = system
        seen["user"] = user
        return _valid_character_json("甲")

    await ac._draft_one_character(
        "brief", {"given_name": "甲", "role": "配角", "persona": "人设"}, "", call_llm,
        max_redo=0, race_names=["人族", "精灵"],
    )
    assert "人族、精灵" in seen["user"]
    assert "人族、精灵" in seen["system"]


@pytest.mark.asyncio
async def test_draft_one_character_omits_race_guidance_when_world_has_no_races(monkeypatch):
    seen = {}

    async def call_llm(system: str, user: str) -> str:
        seen["system"] = system
        seen["user"] = user
        return _valid_character_json("甲")

    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": lambda self: {}})(),
    )

    await ac._draft_one_character(
        "brief", {"given_name": "甲", "role": "配角", "persona": "人设"}, "", call_llm,
        max_redo=0, race_names=None,
    )
    assert "世界设定已定义种族" not in seen["user"]
    assert "世界设定未声明种族时留空" in seen["system"]


@pytest.mark.asyncio
async def test_draft_one_character_uses_standalone_one_shot_system_prompt():
    """Not the interactive character-interview skill -- see the module's existing reasoning.
    Also verifies given_name/role/personality are no longer asked for in the field list."""
    seen = {}

    async def call_llm(system: str, _user: str) -> str:
        seen["system"] = system
        return _valid_character_json("甲")

    await ac._draft_one_character(
        "brief", {"given_name": "甲", "role": "配角", "persona": "人设"}, "", call_llm, max_redo=0,
    )
    system = seen["system"]
    assert "不得提问" in system and "不得等待用户确认" in system
    assert "不得要求提供角色 schema" in system
    assert "level" in system and "levels" in system
    assert "顿号连接的单个字符串" in system
    assert "given_name/role" not in system  # locked fields no longer part of the ask


@pytest.mark.asyncio
async def test_draft_one_character_locks_given_name_role_personality_regardless_of_llm_output():
    """Even if the LLM's JSON puts garbage (or nothing) in given_name/role/personality, the
    final validated dict must carry exactly the locked outline values -- Python overwrites
    unconditionally before validation."""
    async def call_llm(_system: str, _user: str) -> str:
        import json
        data = json.loads(_valid_character_json("垃圾名字"))
        data["role"] = "垃圾定位"
        data["personality"] = "垃圾人格"
        return json.dumps(data, ensure_ascii=False)

    fields, error = await ac._draft_one_character(
        "brief", {"given_name": "锁定名", "role": "锁定定位", "persona": "锁定人设"}, "", call_llm,
        max_redo=0,
    )
    assert error is None
    assert fields is not None
    assert fields["given_name"] == "锁定名"
    assert fields["role"] == "锁定定位"
    assert fields["personality"] == "锁定人设"


@pytest.mark.asyncio
async def test_draft_one_character_locks_verbal_tic_when_outline_entry_provides_it():
    async def call_llm(_system: str, _user: str) -> str:
        import json
        data = json.loads(_valid_character_json("甲"))
        data["verbal_tic"] = "LLM瞎编的口癖"
        return json.dumps(data, ensure_ascii=False)

    fields, error = await ac._draft_one_character(
        "brief", {"given_name": "甲", "role": "配角", "persona": "人设", "verbal_tic": "原著口癖"},
        "", call_llm, max_redo=0,
    )
    assert error is None
    assert fields is not None
    assert fields["verbal_tic"] == "原著口癖"


@pytest.mark.asyncio
async def test_draft_one_character_leaves_verbal_tic_to_llm_when_not_locked():
    """From-scratch branch outline entries never carry a 'verbal_tic' key -- must not touch it,
    the LLM's own value passes through unchanged."""
    async def call_llm(_system: str, _user: str) -> str:
        import json
        data = json.loads(_valid_character_json("甲"))
        data["verbal_tic"] = "LLM自己写的口癖"
        return json.dumps(data, ensure_ascii=False)

    fields, error = await ac._draft_one_character(
        "brief", {"given_name": "甲", "role": "配角", "persona": "人设"}, "", call_llm, max_redo=0,
    )
    assert error is None
    assert fields is not None
    assert fields["verbal_tic"] == "LLM自己写的口癖"


@pytest.mark.asyncio
async def test_draft_one_character_includes_relationship_text_in_prompt():
    seen = {}

    async def call_llm(_system: str, user: str) -> str:
        seen["user"] = user
        return _valid_character_json("甲")

    await ac._draft_one_character(
        "brief", {"given_name": "甲", "role": "配角", "persona": "人设"},
        "与乙：青梅竹马，互相隐瞒身世", call_llm, max_redo=0,
    )
    assert "青梅竹马" in seen["user"]


@pytest.mark.asyncio
async def test_build_chapters_uses_standalone_one_shot_system_prompt():
    """Not the interactive plot-interview skill -- same reasoning as world/character. Only the
    first call_llm invocation is the chapter draft itself; a successful draft triggers a
    second call from _summarize_chapter (a different, unrelated system prompt), so this
    checks the first call specifically rather than whatever was captured last."""
    seen_systems: list[str] = []

    async def call_llm(system: str, _user: str) -> str:
        seen_systems.append(system)
        return (
            '{"title": "章", "core_xp": ["基调"], '
            '"stages": [{"title": "s", "location": "l", "description": "d"}]}'
        )

    await ac.build_chapters("brief", ["甲"], 1, call_llm)
    system = seen_systems[0]
    assert "不得提问" in system and "不得等待" in system
    assert "stage 数量不得少于" in system


def test_load_imported_plot_reference_renders_bullet_list(monkeypatch):
    from repositories import get_research_repo
    from repositories.entities import ResearchChunk

    chunks = [ResearchChunk(text="主角初入宗门", category="plot"),
              ResearchChunk(text="发现血契秘密", category="plot")]
    monkeypatch.setattr(get_research_repo(), "get_chunks", lambda category, topic=None: chunks)
    ref = ac._load_imported_plot_reference()
    assert "主角初入宗门" in ref and "发现血契秘密" in ref


@pytest.mark.asyncio
async def test_build_chapters_includes_reference_text_in_every_chapter_prompt(monkeypatch):
    seen_users: list[str] = []

    async def call_llm(_system: str, user: str) -> str:
        seen_users.append(user)
        idx = len(seen_users)
        return (
            f'{{"title": "第{idx}章", "core_xp": ["基调"], '
            f'"stages": [{{"title": "s", "location": "l", "description": "d"}}]}}'
        )

    async def fake_generate_one_chapter(**kwargs):
        return True, "ok"

    async def fake_summarize(prior, chapter, call_llm):
        return prior

    monkeypatch.setattr(ac, "_generate_one_chapter_core", fake_generate_one_chapter)
    monkeypatch.setattr(ac, "_summarize_chapter", fake_summarize)
    await ac.build_chapters("brief", ["甲"], 2, call_llm, reference_text="主角初入宗门")
    assert all("主角初入宗门" in u for u in seen_users)


@pytest.mark.asyncio
async def test_build_chapters_retries_after_understaffed_write_rejection(monkeypatch):
    """A chapter whose first draft has too few stages for the current word-count target must
    be retried via the same feedback loop as a JSON/pydantic failure, not silently skipped."""
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"target_words": 3000},  # suggested_min_stage_count(3000) == 2
    )
    calls = {"n": 0}

    async def call_llm(_system: str, _user: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return (
                '{"title": "章", "core_xp": ["基调"], '
                '"stages": [{"title": "s", "location": "l", "description": "d"}]}'
            )
        return (
            '{"title": "章", "core_xp": ["基调"], "stages": ['
            '{"title": "s1", "location": "l", "description": "d1"}, '
            '{"title": "s2", "location": "l", "description": "d2"}]}'
        )

    write_calls: list[int] = []

    async def fake_generate_one_chapter(**kwargs):
        write_calls.append(len(kwargs["stages"]))
        if len(kwargs["stages"]) < 2:
            return False, "校验未通过，未写入：\n- ch1 仅 1 段，按当前字数目标（3000 字/章）至少需要 2 段"
        return True, "已追加第1章"

    monkeypatch.setattr(ac, "_generate_one_chapter_core", fake_generate_one_chapter)

    written, errors = await ac.build_chapters("brief", ["甲"], 1, call_llm)
    assert written == 1
    assert errors == []
    assert write_calls == [1, 2]  # first attempt understaffed and rejected, second attempt succeeds


@pytest.mark.asyncio
async def test_build_chapters_gives_up_after_max_redo_understaffed_attempts(monkeypatch):
    """max_redo exhausted while every attempt stays understaffed -> chapter is skipped and
    recorded as an error, exactly like any other exhausted-retry failure; the rest of the
    batch must still proceed (not exercised further here, single-chapter is enough to show
    the skip itself doesn't crash)."""
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"target_words": 3000},
    )

    async def call_llm(_system: str, _user: str) -> str:
        return (
            '{"title": "章", "core_xp": ["基调"], '
            '"stages": [{"title": "s", "location": "l", "description": "d"}]}'
        )

    async def fake_generate_one_chapter(**kwargs):
        return False, "校验未通过，未写入：\n- ch1 仅 1 段，按当前字数目标（3000 字/章）至少需要 2 段"

    monkeypatch.setattr(ac, "_generate_one_chapter_core", fake_generate_one_chapter)

    written, errors = await ac.build_chapters("brief", ["甲"], 1, call_llm, max_redo=1)
    assert written == 0
    assert len(errors) == 1
    assert "写入失败" in errors[0]


@pytest.mark.asyncio
async def test_run_auto_build_passes_worlds_race_names_to_build_characters(monkeypatch):
    monkeypatch.setattr(ac, "_load_imported_world_reference", lambda: "")
    monkeypatch.setattr(ac, "_load_imported_plot_reference", lambda: "")
    monkeypatch.setattr(ac, "_load_imported_characters", lambda cap: [])
    monkeypatch.setattr(ac, "build_world", lambda brief, call_llm, **kw: (
        _async_return(({"tone": "x", "background": "y", "factions": [], "geography": [],
                        "races": [{"name": "人族", "desc": "凡躯"}, {"name": "精灵", "desc": "长寿"}],
                        "power_system": [], "core_themes": []}, []))
    ))
    monkeypatch.setattr(ac, "_construct_world_core", lambda **kw: _async_return(None))
    monkeypatch.setattr(ac, "plan_character_outline", lambda *a, **kw: _async_return(
        ({"characters": [], "relationships": []}, [])
    ))
    seen_kwargs = {}

    async def fake_build_characters(*a, **kw):
        seen_kwargs.update(kw)
        return [], []

    monkeypatch.setattr(ac, "build_characters", fake_build_characters)
    monkeypatch.setattr(ac, "build_chapters", lambda *a, **kw: _async_return((0, [])))

    await ac.run_auto_build("brief", 3, 5, _fake_call_llm)
    assert seen_kwargs.get("race_names") == ["人族", "精灵"]


@pytest.mark.asyncio
async def test_run_auto_build_skips_characters_when_outline_planning_fails(monkeypatch):
    monkeypatch.setattr(ac, "_load_imported_world_reference", lambda: "")
    monkeypatch.setattr(ac, "_load_imported_plot_reference", lambda: "")
    monkeypatch.setattr(ac, "_load_imported_characters", lambda cap: [])
    monkeypatch.setattr(ac, "build_world", lambda brief, call_llm, **kw: (
        _async_return(({"tone": "x", "background": "y", "factions": [], "geography": [],
                        "races": [], "power_system": [], "core_themes": []}, []))
    ))
    monkeypatch.setattr(ac, "_construct_world_core", lambda **kw: _async_return(None))
    monkeypatch.setattr(ac, "plan_character_outline", lambda *a, **kw: _async_return(
        (None, ["角色阵容 JSON 解析失败"])
    ))
    called = {"build_characters": False}

    async def fake_build_characters(*a, **kw):
        called["build_characters"] = True
        return [], []

    monkeypatch.setattr(ac, "build_characters", fake_build_characters)
    monkeypatch.setattr(ac, "build_chapters", lambda *a, **kw: _async_return((0, [])))

    summary = await ac.run_auto_build("brief", 3, 5, _fake_call_llm)
    assert called["build_characters"] is False
    assert "角色阵容规划失败" in summary


@pytest.mark.asyncio
async def test_run_auto_build_uses_imported_roster_when_available(monkeypatch):
    monkeypatch.setattr(ac, "_load_imported_world_reference", lambda: "")
    monkeypatch.setattr(ac, "_load_imported_plot_reference", lambda: "")
    monkeypatch.setattr(
        ac, "_load_imported_characters",
        lambda cap: [{"given_name": "甲", "personality": "冷静", "verbal_tic": "口头禅X"}],
    )
    monkeypatch.setattr(ac, "build_world", lambda brief, call_llm, **kw: _async_return(
        ({"tone": "x", "background": "y", "factions": [], "geography": [],
          "races": [], "power_system": [], "core_themes": []}, [])
    ))
    monkeypatch.setattr(ac, "_construct_world_core", lambda **kw: _async_return(None))

    called_outline = {"plan_character_outline": False}
    monkeypatch.setattr(ac, "plan_character_outline", lambda *a, **kw: (
        called_outline.__setitem__("plan_character_outline", True) or _async_return((None, []))
    ))
    monkeypatch.setattr(
        ac, "plan_character_roles_and_relationships",
        lambda *a, **kw: _async_return(
            ({"characters": [{"given_name": "甲", "role": "主角"}], "relationships": []}, [])
        ),
    )
    seen_outline = {}

    async def fake_build_characters(brief, outline, call_llm, **kw):
        seen_outline.update(outline)
        return [{"given_name": "甲"}], []

    monkeypatch.setattr(ac, "build_characters", fake_build_characters)
    monkeypatch.setattr(ac, "build_chapters", lambda *a, **kw: _async_return((0, [])))

    await ac.run_auto_build("brief", 3, 5, _fake_call_llm)
    assert called_outline["plan_character_outline"] is False
    entry = seen_outline["characters"][0]
    assert entry["given_name"] == "甲"
    assert entry["role"] == "主角"
    assert entry["persona"] == "冷静"
    assert entry["verbal_tic"] == "口头禅X"


@pytest.mark.asyncio
async def test_run_auto_build_falls_back_to_plan_character_outline_without_import(monkeypatch):
    monkeypatch.setattr(ac, "_load_imported_world_reference", lambda: "")
    monkeypatch.setattr(ac, "_load_imported_plot_reference", lambda: "")
    monkeypatch.setattr(ac, "_load_imported_characters", lambda cap: [])
    monkeypatch.setattr(ac, "build_world", lambda brief, call_llm, **kw: _async_return(
        ({"tone": "x", "background": "y", "factions": [], "geography": [],
          "races": [], "power_system": [], "core_themes": []}, [])
    ))
    monkeypatch.setattr(ac, "_construct_world_core", lambda **kw: _async_return(None))
    called = {"plan_character_outline": False, "roles": False}
    monkeypatch.setattr(ac, "plan_character_outline", lambda *a, **kw: (
        called.__setitem__("plan_character_outline", True) or
        _async_return(({"characters": [], "relationships": []}, []))
    ))
    monkeypatch.setattr(ac, "plan_character_roles_and_relationships", lambda *a, **kw: (
        called.__setitem__("roles", True) or _async_return((None, []))
    ))
    monkeypatch.setattr(ac, "build_characters", lambda *a, **kw: _async_return(([], [])))
    monkeypatch.setattr(ac, "build_chapters", lambda *a, **kw: _async_return((0, [])))

    await ac.run_auto_build("brief", 3, 5, _fake_call_llm)
    assert called["plan_character_outline"] is True
    assert called["roles"] is False


@pytest.mark.asyncio
async def test_run_auto_build_passes_cap_matching_character_count_to_imported_roster(monkeypatch):
    seen_cap = {}
    monkeypatch.setattr(ac, "_load_imported_world_reference", lambda: "")
    monkeypatch.setattr(ac, "_load_imported_plot_reference", lambda: "")

    def fake_load(cap):
        seen_cap["cap"] = cap
        return []

    monkeypatch.setattr(ac, "_load_imported_characters", fake_load)
    monkeypatch.setattr(ac, "build_world", lambda brief, call_llm, **kw: _async_return(
        ({"tone": "x", "background": "y", "factions": [], "geography": [],
          "races": [], "power_system": [], "core_themes": []}, [])
    ))
    monkeypatch.setattr(ac, "_construct_world_core", lambda **kw: _async_return(None))
    monkeypatch.setattr(ac, "plan_character_outline", lambda *a, **kw: _async_return(
        ({"characters": [], "relationships": []}, [])
    ))
    monkeypatch.setattr(ac, "build_characters", lambda *a, **kw: _async_return(([], [])))
    monkeypatch.setattr(ac, "build_chapters", lambda *a, **kw: _async_return((0, [])))

    await ac.run_auto_build("brief", 8, 5, _fake_call_llm)
    assert seen_cap["cap"] == 8


@pytest.mark.asyncio
async def test_run_auto_build_passes_reference_text_to_world_and_chapters(monkeypatch):
    monkeypatch.setattr(ac, "_load_imported_world_reference", lambda: "世界观参考")
    monkeypatch.setattr(ac, "_load_imported_plot_reference", lambda: "剧情参考")
    monkeypatch.setattr(ac, "_load_imported_characters", lambda cap: [])
    seen = {}

    async def fake_build_world(brief, call_llm, **kw):
        seen["world_reference"] = kw.get("reference_text")
        return {"tone": "x", "background": "y", "factions": [], "geography": [],
                "races": [], "power_system": [], "core_themes": []}, []

    monkeypatch.setattr(ac, "build_world", fake_build_world)
    monkeypatch.setattr(ac, "_construct_world_core", lambda **kw: _async_return(None))
    monkeypatch.setattr(ac, "plan_character_outline", lambda *a, **kw: _async_return(
        ({"characters": [], "relationships": []}, [])
    ))
    monkeypatch.setattr(ac, "build_characters", lambda *a, **kw: _async_return(([], [])))

    async def fake_build_chapters(brief, names, count, call_llm, **kw):
        seen["plot_reference"] = kw.get("reference_text")
        return 0, []

    monkeypatch.setattr(ac, "build_chapters", fake_build_chapters)

    await ac.run_auto_build("brief", 3, 5, _fake_call_llm)
    assert seen["world_reference"] == "世界观参考"
    assert seen["plot_reference"] == "剧情参考"
