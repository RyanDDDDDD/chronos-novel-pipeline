import pytest

from engine.setup_chat import setup_quality_review as sqr
from engine.setup_chat.tools import (
    _add_character_core,
    _edit_character_core,
    construct_world,
    refine_world,
)
from repo_test_helpers import get_world, init_store, lore_raw, seed_lore, seed_world


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


def _world_args(**overrides):
    item = {"name": "n", "desc": "d"}
    base = {
        "tone": "T",
        "background": "B",
        "factions": [item],
        "geography": [item],
        "races": [item],
        "power_system": [item],
        "core_themes": [item],
    }
    base.update(overrides)
    return base


def _character_args(name: str) -> dict:
    from engine.setup.cast.stance_schema import physique_slots

    return {
        "given_name": name,
        "role": "甲",
        "gender": "female",
        "causal_anchors": {"执念": "复仇", "渴望": "认同"},
        "physique": {k: "x" for k in physique_slots("female")},
        "clothing_color_palette": ["黑"],
        "clothing_materials": ["皮革"],
        "clothing_signature_outfit": "黑色皮革风日常常服",
        "clothing_accessories": ["皮质腕带"],
        "sliders": {
            "投入": {
                "level": 1,
                "text": "登场时尚有保留",
                "levels": {"0": "a", "1": "b", "2": "c"},
            }
        },
        "race": "人",
        "personality": "尚待观察",
        "identity_background": "出身平平，家境普通",
        "武器": "尚待观察",
        "流派": "尚待观察",
        "身份": "尚待观察",
    }


def _full_char(name: str) -> dict:
    a = _character_args(name)
    return {
        "name": name,
        "given_name": name,
        "role": a["role"],
        "gender": a["gender"],
        "race": a["race"],
        "causal_anchors": a["causal_anchors"],
        "physique": a["physique"],
        "clothing_dna": {
            "color_palette": a["clothing_color_palette"],
            "materials_preference": a["clothing_materials"],
            "signature_outfit": a["clothing_signature_outfit"],
            "accessories": a["clothing_accessories"],
        },
        "sliders": a["sliders"],
        "personality": a["personality"],
        "identity_background": a["identity_background"],
    }


@pytest.fixture(autouse=True)
def _no_world_races(monkeypatch):
    from engine.setup.cast import cast_validator as cv

    monkeypatch.setattr(cv, "_load_world_race_names", lambda: [], raising=False)


@pytest.fixture(autouse=True)
def _no_relationship_inference(monkeypatch):
    async def noop_generate(*_args, **_kwargs):
        return []

    monkeypatch.setattr(
        "engine.setup.cast.incremental_relationship.generate_edges_for_new_character",
        noop_generate,
    )


def _valid_bible() -> dict:
    return {
        "tone": "x" * 20,
        "background": "y" * 20,
        "factions": [{"name": "甲帮", "desc": "这是一个足够长的派系描述内容"}],
        "geography": [{"name": "乌城", "desc": "这是一个足够长的地理描述内容"}],
        "races": [
            {
                "name": "人类",
                "desc": "人类社会结构复杂，文化习俗丰富，与各方势力紧密关联的日常差异明显",
            }
        ],
        "power_system": [{"name": "机制", "desc": "这是一个足够长的力量体系描述"}],
        "core_themes": [{"name": "支配", "desc": "这是一个足够长的核心主题描述"}],
    }


@pytest.mark.asyncio
async def test_gate_world_advises_without_blocking(monkeypatch):
    import engine.modes.author_loop_skill_prefs as prefs_mod

    real = prefs_mod.load_dialogue_prefs

    def _hooks_enabled() -> dict:
        prefs = real()
        prefs["disabled_setup_review_hooks"] = []
        return prefs

    monkeypatch.setattr(prefs_mod, "load_dialogue_prefs", _hooks_enabled)

    async def _rewrite(*_a, **_k):
        from engine.author_loop.self_review import SelfReviewVerdict

        return SelfReviewVerdict("rewrite", 65.0, [("setup_world_tension", 55)], "fb")

    monkeypatch.setattr(sqr, "run_world_review_with_hooks", _rewrite)
    ok, msg = await sqr.gate_world_bible({"tone": "t"})
    assert ok is True
    assert "已写入" in msg
    assert "未写入" not in msg
    assert "55" not in msg and "/100" not in msg
    assert "【" in msg
    assert "冲突张力" in msg
    assert "fb" in msg


@pytest.mark.asyncio
async def test_all_hooks_disabled_accepts(monkeypatch):
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {
            "disabled_setup_review_hooks": list(
                sqr.SETUP_WORLD_HOOK_NAMES + sqr.SETUP_CAST_HOOK_NAMES
            ),
        },
    )
    ok, msg = await sqr.gate_world_bible(_valid_bible())
    assert ok is True
    assert msg == ""


@pytest.mark.asyncio
async def test_gate_character_accepts_on_pass(monkeypatch):
    async def _accept(*_a, **_k):
        from engine.author_loop.self_review import SelfReviewVerdict

        return SelfReviewVerdict("accept", 90.0, [("setup_cast_anchors", 85)], "")

    monkeypatch.setattr(sqr, "run_cast_review", _accept)
    ok, msg = await sqr.gate_character({"given_name": "测试"})
    assert ok is True
    assert msg == ""


def test_format_agent_rubric_no_scores():
    from engine.author_loop.review.review_loader import REVIEW_HOOKS
    from engine.author_loop.self_review import SelfReviewVerdict

    hooks = [h for h in REVIEW_HOOKS if h.name == "setup_world_tension"]
    verdict = SelfReviewVerdict("rewrite", 65.0, [("setup_world_tension", 55)], "需要具体冲突")
    rubric = sqr.format_agent_rubric(verdict, hooks)
    assert "55" not in rubric
    assert "/100" not in rubric
    assert "【冲突张力】" in rubric
    assert "需要具体冲突" in rubric


@pytest.mark.asyncio
async def test_construct_world_persists_without_inline_review_hint(monkeypatch):
    init_store()

    scheduled: list[bool] = []

    def _schedule(*, complete=None, novel_brief=None):
        scheduled.append(complete is True)

    monkeypatch.setattr(
        "engine.setup_chat.world_background_review.schedule_world_quality_review",
        _schedule,
    )

    out = await construct_world.ainvoke(_world_args(tone="冷峻"))
    assert "已写入世界观" in out
    assert "设定质量建议" not in out
    assert get_world() is not None
    assert scheduled == [True]


@pytest.mark.asyncio
async def test_refine_world_persists_without_inline_review_hint(monkeypatch):
    seed_world({"tone": "orig"})

    scheduled: list[bool] = []

    def _schedule(*, complete=None, novel_brief=None):
        scheduled.append(complete is True)

    monkeypatch.setattr(
        "engine.setup_chat.world_background_review.schedule_world_quality_review",
        _schedule,
    )

    out = await refine_world.ainvoke(_world_args(tone="黑暗"))
    assert "已更新世界观" in out
    assert "设定质量建议" not in out
    saved = get_world()
    assert saved is not None
    assert saved["tone"] == "黑暗"
    assert scheduled == [True]


@pytest.mark.asyncio
async def test_add_character_core_persists_and_schedules_review(monkeypatch):
    seed_lore([_full_char("甲")])
    scheduled = []
    visual_tags_scheduled = []
    monkeypatch.setattr(
        "engine.setup_chat.character_background_review.schedule_character_quality_review",
        lambda name, **_kwargs: scheduled.append(name),
    )
    monkeypatch.setattr(
        "engine.setup_chat.character_visual_tags.schedule_extract_visual_tags",
        lambda name: visual_tags_scheduled.append(name),
    )

    ok, msg, char = await _add_character_core(**_character_args("乙"))
    assert ok is True
    assert char is not None
    assert {c["name"] for c in lore_raw()} == {"甲", "乙"}
    assert scheduled == ["乙"]
    assert visual_tags_scheduled == ["乙"]


@pytest.mark.asyncio
async def test_edit_character_core_persists_without_inline_gate(monkeypatch):
    seed_lore([_full_char("甲")])
    monkeypatch.setattr(
        "engine.setup_chat.timeline_auto.schedule_timeline_cascade",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "engine.setup_chat.character_background_review.schedule_character_quality_review",
        lambda name, **_kwargs: None,
    )
    monkeypatch.setattr(
        "engine.setup_chat.character_background_review.cancel_active_character_fix",
        lambda novel_id, name: _noop_coro(),
    )

    args = _character_args("甲")
    args["personality"] = "改过的人格"
    ok, msg, char = await _edit_character_core(name="甲", **args)
    assert ok is True
    assert char is not None
    assert lore_raw()[0]["personality"] == "改过的人格"


async def _noop_coro():
    return None


def test_active_hooks_is_importable_as_public_name():
    from engine.setup_chat.setup_quality_review import active_hooks

    hooks = active_hooks(("setup_cast_anchors",))
    assert isinstance(hooks, list)
