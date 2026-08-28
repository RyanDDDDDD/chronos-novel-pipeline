import asyncio
import pytest
from engine.setup_chat.tool_args import build_add_character_args
from engine.setup_chat.tools import (
    _add_character_core,
    add_character,
    add_relationship_edge,
    read_character,
    read_relationships,
    remove_relationship_edge,
)
from pydantic import ValidationError

from repo_test_helpers import init_store, lore_raw, seed_lore, seed_plot


@pytest.fixture(autouse=True)
def _real_add_character_schema():
    """add_character's @tool(...) decoration-time args_schema is the bare
    _StaticCharacterFieldsArgs placeholder -- it has no content-pack custom fields (e.g.
    a content pack's custom field). Only build_agent() overwrites .args_schema with the real,
    content-pack-aware build_add_character_args() result (see agent.py). Tests here call
    add_character.ainvoke() directly without ever running build_agent() -- they used to only
    pass by accident when some earlier-collected test file happened to call build_agent()
    first and leak the correct schema as global state (the same class of bug
    test_edit_character_placeholder_schema_has_name_field below documents for edit_character's
    `name` field), which breaks the moment this file is collected/run on its own. Rebuild it
    explicitly instead of relying on incidental cross-file test order."""
    add_character.args_schema = build_add_character_args()


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


def _prefs(**overrides: object) -> dict:
    from engine.setup_chat import setup_quality_review as sqr

    prefs: dict = {
        "disabled_setup_review_hooks": list(sqr.SETUP_WORLD_HOOK_NAMES),
    }
    prefs.update(overrides)
    return prefs


def _schema():
    return {"roles": {"甲": {"sliders": {"投入": {"levels": {"0": "a", "1": "b", "2": "c"}}}}}}


def _args(name: str) -> dict:
    """A legal and complete role entry (Plan B: the main agent fills it in directly)."""
    from engine.setup.cast.stance_schema import physique_slots

    return {
        "given_name": name, "role": "甲", "gender": "female",
        "causal_anchors": {"执念": "复仇", "渴望": "认同"},
        "physique": {k: "x" for k in physique_slots("female")},
        "clothing_color_palette": ["黑"], "clothing_materials": ["皮革"],
        "clothing_signature_outfit": "黑色皮革风日常常服",
        "clothing_accessories": ["皮质腕带"],
        "sliders": {
            "投入": {
                "level": 1,
                "text": "登场时尚有保留",
                "levels": {"0": "a", "1": "b", "2": "c"},
            }
        }, "race": "人",
        "personality": "尚待观察", "identity_background": "出身平平，家境普通",
        "性癖": "尚待观察",
        "敏感带": "尚待观察",
        "暴露程度": "尚待观察",
    }


def _full_char(name: str) -> dict:
    a = _args(name)
    return {
        "name": name, "given_name": name, "role": a["role"], "gender": a["gender"],
        "race": a["race"], "causal_anchors": a["causal_anchors"], "physique": a["physique"],
        "clothing_dna": {"color_palette": a["clothing_color_palette"],
                         "materials_preference": a["clothing_materials"],
                         "signature_outfit": a["clothing_signature_outfit"],
                         "accessories": a["clothing_accessories"]},
        "sliders": a["sliders"],
    }


@pytest.mark.asyncio
async def test_add_character_refreshes_character_scan_cache(monkeypatch, tmp_path):
    """Regression: add_character must invalidate entity_index so chapter tool returns
    recognize newly added given_name vocab, not a stale empty automaton from before cast."""
    from engine.memory_recall import entity_index
    from engine.setup.chat_summary import render_chapter_chat

    init_store()

    entity_index.invalidate_entity_vocab_cache()
    assert entity_index.scan_characters("甲在书房") == []

    await add_character.ainvoke(_args("甲"))

    chapter = {"title": "对峙", "stages": [
        {"title": "书房", "location": "书房", "description": "甲推开书房门"},
    ]}
    out = render_chapter_chat(chapter, 1)
    assert "（识别角色：甲）" in out


@pytest.mark.asyncio
async def test_add_character_appends(monkeypatch, tmp_path):
    """
Directly place the order according to the filled in fields and add, without overwriting the existing ones (the LLM will not be adjusted internally)."""
    seed_lore([_full_char("甲")])
    out = await add_character.ainvoke(_args("乙"))
    assert "已添加" in out and "乙" in out
    saved = lore_raw()
    assert {c["name"] for c in saved} == {"甲", "乙"}


@pytest.mark.asyncio
async def test_parallel_add_character_all_persist(monkeypatch, tmp_path):
    """LangGraph may dispatch multiple add_character calls in parallel; roster writes must serialize."""
    seed_lore([_full_char("甲")])

    names = [f"角色{i}" for i in range(5)]
    results = await asyncio.gather(*(_add_character_core(**_args(n)) for n in names))
    assert all(r[0] for r in results), [r[1] for r in results if not r[0]]

    saved = lore_raw()
    assert {c["name"] for c in saved} == {"甲", *names}


@pytest.mark.asyncio
async def test_read_character_renders_full_card(monkeypatch, tmp_path):
    char = _full_char("甲")
    char["identity_background"] = "没落贵族之女，寄人篱下"
    char["hobbies"] = ["刺绣", "抚琴"]
    char["verbal_tic"] = "句尾爱加「呢」"
    seed_lore([char])

    out = await read_character.ainvoke({"name": "甲"})
    assert "身份背景：没落贵族之女，寄人篱下" in out
    assert "爱好：刺绣、抚琴" in out
    assert "口癖：句尾爱加「呢」" in out
    assert "因果设定：" in out
    assert "体质(physique)：" in out
    assert "登场初始滑块：" in out
    assert "{" not in out


@pytest.mark.asyncio
async def test_read_character_not_found(monkeypatch, tmp_path):
    seed_lore([_full_char("甲")])

    out = await read_character.ainvoke({"name": "乙"})
    assert "未找到" in out and "乙" in out


@pytest.mark.asyncio
async def test_add_character_appends_remaining_note_when_understaffed(monkeypatch, tmp_path):
    seed_lore([_full_char("甲")])
    import engine.modes.author_loop_skill_prefs as prefs_mod
    monkeypatch.setattr(
        prefs_mod, "load_dialogue_prefs", lambda: _prefs(auto_build_character_count=8),
    )
    out = await add_character.ainvoke(_args("乙"))
    assert "已建 2/8 人，剩余 6 人待创建" in out


@pytest.mark.asyncio
async def test_add_character_no_remaining_note_when_target_met(monkeypatch, tmp_path):
    """target=1，添加第 2 个（超出目标）不应再提示剩余人数。"""
    seed_lore([_full_char("甲")])
    import engine.modes.author_loop_skill_prefs as prefs_mod
    monkeypatch.setattr(
        prefs_mod, "load_dialogue_prefs", lambda: _prefs(auto_build_character_count=1),
    )
    out = await add_character.ainvoke(_args("乙"))
    assert "待创建" not in out


@pytest.mark.asyncio
async def test_add_character_duplicate_name(monkeypatch, tmp_path):
    seed_lore([_full_char("乙")])
    out = await add_character.ainvoke(_args("乙"))
    assert "已存在" in out


@pytest.mark.asyncio
async def test_add_character_validation_error_not_written(monkeypatch, tmp_path):
    """The field does not conform to the schema (the physique slot is missing) → Pydantic blocks and does not place the disk."""
    init_store()
    args = _args("丙")
    del args["physique"]["胸部"]
    with pytest.raises(ValidationError) as exc:
        await add_character.ainvoke(args)
    assert "胸部" in str(exc.value)
    assert lore_raw() == []


@pytest.mark.asyncio
async def test_add_character_accepts_race_not_in_world_list(monkeypatch, tmp_path):
    """Interactive path: race mismatch is no longer a hard reject; write still succeeds."""
    from engine.setup.cast import cast_validator as cv

    monkeypatch.setattr(cv, "_load_world_race_names", lambda: ["精灵族", "人类"], raising=False)
    init_store()
    args = _args("丁")
    args["race"] = "魅魔"
    out = await add_character.ainvoke(args)
    assert "已添加" in out and "丁" in out
    saved = lore_raw()
    assert saved[0]["race"] == "魅魔"


@pytest.mark.asyncio
async def test_add_character_still_rejects_empty_race_when_world_has_races(monkeypatch, tmp_path):
    """Empty race stays a hard error when the world bible declares races."""
    from engine.setup.cast import cast_validator as cv

    monkeypatch.setattr(cv, "_load_world_race_names", lambda: ["精灵族", "人类"], raising=False)
    init_store()
    args = _args("戊")
    args["race"] = ""
    with pytest.raises(ValidationError) as exc:
        await add_character.ainvoke(args)
    assert "缺 race" in str(exc.value)
    assert lore_raw() == []


def test_add_character_tool_description_has_no_hardcoded_adult_example():
    """Regression: add_character is @tool-decorated with no explicit description=, so its
    docstring becomes the tool's LLM-facing description at decoration/import time -- unlike
    args_schema (rebuilt fresh per build_agent(), see agent.py), this string is never rebuilt,
    so anything hardcoded here reaches the LLM regardless of which content packs are active. The docstring
    used to hardcode 性癖 as an example of a hook-declared custom field; that concrete example
    now lives only in hooks/content_packs/<pack>/hook.py."""
    assert "性癖" not in (add_character.description or "")


def test_edit_character_placeholder_schema_has_name_field():
    """Regression: edit_character's @tool(...) decoration-time args_schema used to be the bare
    _StaticCharacterFieldsArgs placeholder (shared with add_character), which has no `name`
    field. Any test/caller invoking edit_character.ainvoke(...) before build_agent() has run at
    least once in the process (so before .args_schema gets overwritten with the real
    build_edit_character_args()) would have Pydantic silently drop the `name` kwarg as unknown,
    and the underlying async function would blow up missing a required positional argument --
    this only stayed hidden because some earlier-collected test file happened to call
    build_agent() first and leak the correct schema as global state. _EditCharacterPlaceholderArgs
    fixes this structurally (name is content-pack-independent, so it belongs on the
    placeholder itself, not just the dynamically-rebuilt schema)."""
    from engine.setup_chat.tool_args import _EditCharacterPlaceholderArgs

    assert "name" in _EditCharacterPlaceholderArgs.model_fields


def test_agent_registers_cast_tools():
    import inspect

    import engine.setup_chat.agent as a

    src = inspect.getsource(a.build_agent)
    assert "add_character" in src
    assert "construct_cast" not in src
    assert "WORLD_DIMENSION_TOOLS" in src and "construct_setup" not in src
    assert "read_relationships" in src
    assert "add_relationship_edge" in src
    assert "remove_relationship_edge" in src


@pytest.mark.asyncio
async def test_add_character_saves_identity_background_and_hobbies(monkeypatch, tmp_path):
    """身份背景是必填字段，填了原样落盘；爱好仍是可选。"""
    init_store()
    args = _args("戊")
    args["identity_background"] = "没落贵族之女，寄人篱下"
    args["hobbies"] = ["爱吃甜食", "喜欢刺绣"]
    out = await add_character.ainvoke(args)
    assert "已添加" in out
    saved = lore_raw()
    char = next(c for c in saved if c["name"] == "戊")
    assert char["identity_background"] == "没落贵族之女，寄人篱下"
    assert char["hobbies"] == ["爱吃甜食", "喜欢刺绣"]


@pytest.mark.asyncio
async def test_add_character_missing_identity_background_rejected(monkeypatch, tmp_path):
    """identity_background 缺省 → Pydantic 直接拒绝（必填字段，不落盘）。"""
    init_store()
    args = _args("丑")
    del args["identity_background"]
    with pytest.raises(ValidationError):
        await add_character.ainvoke(args)
    assert lore_raw() == []


@pytest.mark.asyncio
async def test_add_character_empty_identity_background_rejected(monkeypatch, tmp_path):
    """identity_background 填空串 → 视同未填，同样被拒绝（不落盘）。"""
    init_store()
    args = _args("寅")
    args["identity_background"] = "   "
    with pytest.raises(ValidationError):
        await add_character.ainvoke(args)
    assert lore_raw() == []


@pytest.mark.asyncio
async def test_add_character_defaults_hobbies_empty(monkeypatch, tmp_path):
    """爱好不填 → 默认空列表，不因缺省报错。"""
    init_store()
    out = await add_character.ainvoke(_args("己"))
    assert "已添加" in out
    saved = lore_raw()
    char = next(c for c in saved if c["name"] == "己")
    assert char["hobbies"] == []


@pytest.mark.asyncio
async def test_add_character_saves_verbal_tic(monkeypatch, tmp_path):
    """口癖创建期可选声明种子值，填了就原样落盘（后续可被 timeline delta 覆盖，见 timeline 测试）。"""
    init_store()
    args = _args("庚")
    args["verbal_tic"] = "句尾爱加「呢」，紧张时会重复最后两个字"
    out = await add_character.ainvoke(args)
    assert "已添加" in out
    saved = lore_raw()
    char = next(c for c in saved if c["name"] == "庚")
    assert char["verbal_tic"] == "句尾爱加「呢」，紧张时会重复最后两个字"


@pytest.mark.asyncio
async def test_add_character_defaults_verbal_tic_empty(monkeypatch, tmp_path):
    """不填 → 默认空字符串，不因缺省报错。"""
    init_store()
    out = await add_character.ainvoke(_args("辛"))
    assert "已添加" in out
    saved = lore_raw()
    char = next(c for c in saved if c["name"] == "辛")
    assert char["verbal_tic"] == ""


@pytest.mark.asyncio
async def test_add_character_saves_personality(monkeypatch, tmp_path):
    """人格是必填字段，填了原样落盘（后续可被 timeline delta 覆盖，见 timeline 测试）。"""
    init_store()
    args = _args("壬")
    args["personality"] = "表面嘴硬冷漠，内心其实很依恋对方"
    out = await add_character.ainvoke(args)
    assert "已添加" in out
    saved = lore_raw()
    char = next(c for c in saved if c["name"] == "壬")
    assert char["personality"] == "表面嘴硬冷漠，内心其实很依恋对方"


@pytest.mark.asyncio
async def test_add_character_missing_personality_rejected(monkeypatch, tmp_path):
    """personality 缺省 → Pydantic 直接拒绝（必填字段，不落盘）。"""
    init_store()
    args = _args("癸")
    del args["personality"]
    with pytest.raises(ValidationError):
        await add_character.ainvoke(args)
    assert lore_raw() == []


@pytest.mark.asyncio
async def test_add_character_empty_personality_rejected(monkeypatch, tmp_path):
    """personality 填空串 → 视同未填，同样被拒绝（不落盘）。"""
    init_store()
    args = _args("子")
    args["personality"] = "   "
    with pytest.raises(ValidationError):
        await add_character.ainvoke(args)
    assert lore_raw() == []


@pytest.mark.asyncio
async def test_add_character_core_returns_ok_and_char(monkeypatch, tmp_path):
    seed_lore([_full_char("甲")])
    from engine.setup_chat.tools import _add_character_core

    ok, msg, char = await _add_character_core(**_args("乙"))
    assert ok is True and "乙" in msg
    assert char is not None and char["name"] == "乙"
    saved = lore_raw()
    assert {c["name"] for c in saved} == {"甲", "乙"}


@pytest.mark.asyncio
async def test_add_character_core_rejects_duplicate(monkeypatch, tmp_path):
    seed_lore([_full_char("甲")])
    from engine.setup_chat.tools import _add_character_core

    ok, msg, char = await _add_character_core(**_args("甲"))
    assert ok is False and char is None and "已存在" in msg


@pytest.mark.asyncio
async def test_edit_character_core_updates_and_returns_char(monkeypatch, tmp_path):
    seed_lore([_full_char("甲")])
    monkeypatch.setattr(
        "engine.setup_chat.timeline_auto.schedule_timeline_cascade", lambda *a, **k: None,
    )

    from engine.setup_chat.tools import _edit_character_core

    args = _args("甲")
    args["personality"] = "改过的人格"
    ok, msg, char = await _edit_character_core(name="甲", **args)
    assert ok is True and char is not None and char["personality"] == "改过的人格"
    saved = lore_raw()
    assert saved[0]["personality"] == "改过的人格"


@pytest.mark.asyncio
async def test_delete_character_core_removes_from_roster(monkeypatch, tmp_path):
    _patch_empty_plot(monkeypatch, tmp_path)
    seed_lore([_full_char("甲"), _full_char("乙")])
    monkeypatch.setattr(
        "engine.archive.archive_view.delete_character_archives",
        lambda name: {"removed_stages": 0, "deleted_chapters": []},
    )
    monkeypatch.setattr(
        "engine.setup_chat.timeline_auto.schedule_timeline_cascade", lambda *a, **k: None,
    )

    from engine.setup_chat.tools import _delete_character_core

    ok, msg, _detail = await _delete_character_core("甲")
    assert ok is True and "甲" in msg
    saved = lore_raw()
    assert {c["name"] for c in saved} == {"乙"}


@pytest.mark.asyncio
async def test_delete_character_core_not_found(monkeypatch, tmp_path):
    seed_lore([_full_char("甲")])

    from engine.setup_chat.tools import _delete_character_core

    ok, msg, _detail = await _delete_character_core("不存在")
    assert ok is False and "未找到" in msg


@pytest.mark.asyncio
async def test_delete_character_core_cascades_chapter_mentioning_name(monkeypatch, tmp_path):
    _isolate_timeline(tmp_path, monkeypatch)
    _setup_roster(monkeypatch, tmp_path, ["甲", "乙"])
    _patch_edges_db(monkeypatch, tmp_path, ["甲", "乙"])
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()

    seed_plot([
        {"chapter": 1, "title": "第一章", "stages": [
            {"title": "场", "location": "阁楼", "description": "甲推开阁楼门",
             "beats": [{"text": "甲环顾四周"}]},
        ]},
        {"chapter": 2, "title": "第二章", "stages": [
            {"title": "场", "location": "庭院", "description": "乙在庭院练剑", "beats": []},
        ]},
    ])

    import utils.paths as up
    chapters_root = tmp_path / "chapters"
    monkeypatch.setattr(up, "chapters_dir", lambda: str(chapters_root))

    monkeypatch.setattr(
        "engine.archive.archive_view.delete_character_archives",
        lambda name: {"removed_stages": 0, "deleted_chapters": []},
    )
    monkeypatch.setattr(
        "engine.setup_chat.timeline_auto.schedule_timeline_cascade", lambda *a, **k: None,
    )

    from engine.setup_chat.tools import _delete_character_core

    ok, msg, detail = await _delete_character_core("甲")
    assert ok is True
    assert detail["deleted_chapters"] == [1]
    assert "第1章" in msg

    remaining_plot = _plot_raw()
    assert [c["chapter"] for c in remaining_plot] == [1]
    assert remaining_plot[0]["title"] == "第二章"
    saved_roster = lore_raw()
    assert {c["name"] for c in saved_roster} == {"乙"}


@pytest.mark.asyncio
async def test_delete_character_core_removes_relationship_edges(monkeypatch, tmp_path):
    _patch_empty_plot(monkeypatch, tmp_path)
    _setup_roster(monkeypatch, tmp_path, ["甲", "乙"])
    _patch_edges_db(monkeypatch, tmp_path, ["甲", "乙"])
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()

    out = await add_relationship_edge.ainvoke({
        "from_name": "甲", "to_name": "乙", "nature": "师徒",
        "relationship_anchor": "", "from_ref_terms": [], "to_ref_terms": [],
    })
    assert "已写入" in out

    monkeypatch.setattr(
        "engine.archive.archive_view.delete_character_archives",
        lambda name: {"removed_stages": 0, "deleted_chapters": []},
    )
    monkeypatch.setattr(
        "engine.setup_chat.timeline_auto.schedule_timeline_cascade", lambda *a, **k: None,
    )

    from engine.setup_chat.tools import _delete_character_core
    from engine.setup.cast.relationship_graph import edges_for_character, load_graph

    ok, msg, detail = await _delete_character_core("甲")
    assert ok is True
    assert detail["removed_edges"] == ["甲→乙"]
    assert edges_for_character(load_graph(), "甲") == []
    assert edges_for_character(load_graph(), "乙") == []


def test_allowed_delta_fields_includes_timeline_delta_custom_fields(monkeypatch):
    from engine.setup_chat import tools as t
    import context.content_packs as cp

    monkeypatch.setattr(
        cp, "custom_fields",
        lambda: [cp.CustomFieldSpec(name="爱好癖", timeline_delta=True)],
    )
    assert "爱好癖" in t._delta_allowed_fields()


def test_allowed_delta_fields_excludes_non_timeline_custom_fields(monkeypatch):
    from engine.setup_chat import tools as t
    import context.content_packs as cp

    monkeypatch.setattr(
        cp, "custom_fields",
        lambda: [cp.CustomFieldSpec(name="仅存储字段", timeline_delta=False)],
    )
    assert "仅存储字段" not in t._delta_allowed_fields()


@pytest.mark.asyncio
async def test_add_character_fires_relationship_inference_when_roster_nonempty(monkeypatch, tmp_path):
    seed_lore([_full_char("甲")])
    calls = []

    async def fake_generate(new_char, existing_roster, **kw):
        calls.append((new_char.get("name"), [c.get("name") for c in existing_roster]))
        return []

    monkeypatch.setattr(
        "engine.setup.cast.incremental_relationship.generate_edges_for_new_character", fake_generate,
    )

    await add_character.ainvoke(_args("乙"))

    from engine.setup_chat.tools import _pending_relationship_tasks
    if _pending_relationship_tasks:
        import asyncio
        await asyncio.gather(*_pending_relationship_tasks)

    assert calls == [("乙", ["甲"])]


@pytest.mark.asyncio
async def test_add_character_skips_inference_for_first_character(monkeypatch, tmp_path):
    init_store()
    calls = []

    async def fake_generate(new_char, existing_roster, **kw):
        calls.append(new_char)
        return []

    monkeypatch.setattr(
        "engine.setup.cast.incremental_relationship.generate_edges_for_new_character", fake_generate,
    )

    await add_character.ainvoke(_args("甲"))

    from engine.setup_chat.tools import _pending_relationship_tasks
    if _pending_relationship_tasks:
        import asyncio
        await asyncio.gather(*_pending_relationship_tasks)

    assert calls == []  # 第一个角色，没有已有花名册可关联，不该 fire


def _setup_roster(_monkeypatch, _tmp_path, names):
    seed_lore([_full_char(n) for n in names])


def _patch_empty_plot(_monkeypatch, _tmp_path):
    """Isolates get_plot_repo() from real novel data for tests that don't care about plot
    content but still exercise _delete_character_core's plot-scan step (which must never see
    real chapters, since a false-positive text match would cascade-delete them)."""
    seed_plot([])


def _patch_edges_db(monkeypatch, tmp_path, names: list[str] | None = None):
    """Route relationship edge IO to an isolated sqlite db under tmp_path.

    When `names` is given, also seed those characters into the isolated db's lore_characters
    so append_edge's character_id FK resolution succeeds (edges live in a different file from
    the novel's main chronos.sqlite3 roster)."""
    db = str(tmp_path / "edges.sqlite3")
    import engine.setup.cast.relationship_graph as rg

    real_load = rg.load_graph
    real_append = rg.append_edge
    real_remove = rg.remove_edge
    monkeypatch.setattr(rg, "load_graph", lambda path=None: real_load(db))
    monkeypatch.setattr(rg, "append_edge", lambda edge, path=None: real_append(edge, path=db))
    monkeypatch.setattr(rg, "remove_edge", lambda frm, to, path=None: real_remove(frm, to, path=db))
    if names:
        from repositories.sqlite_store import get_connection
        conn = get_connection(db)
        for i, name in enumerate(names):
            conn.execute(
                "INSERT INTO lore_characters (name, data_json, seq) VALUES (?, '{}', ?)",
                (name, i),
            )
        conn.commit()
    return db


def _plot_raw():
    import repositories as repo

    repo.init_repositories()
    return repo.get_plot_repo().list_raw()


def _isolate_timeline(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "test-novel")
    (tmp_path / "test-novel").mkdir(parents=True, exist_ok=True)
    import repositories

    repositories.init_repositories("test-novel")


@pytest.mark.asyncio
async def test_read_relationships_no_edges(monkeypatch, tmp_path):
    _setup_roster(monkeypatch, tmp_path, ["甲", "乙"])
    _patch_edges_db(monkeypatch, tmp_path, ["甲", "乙"])

    out = await read_relationships.ainvoke({"name": "甲"})
    assert "没有任何边" in out and "甲" in out


@pytest.mark.asyncio
async def test_add_relationship_edge_then_read_both_directions(monkeypatch, tmp_path):
    _setup_roster(monkeypatch, tmp_path, ["甲", "乙"])
    _patch_edges_db(monkeypatch, tmp_path, ["甲", "乙"])

    out = await add_relationship_edge.ainvoke({
        "from_name": "甲", "to_name": "乙", "nature": "师徒",
        "relationship_anchor": "", "from_ref_terms": [], "to_ref_terms": ["师傅"],
    })
    assert "已写入" in out and "甲" in out and "乙" in out

    from_side = await read_relationships.ainvoke({"name": "甲"})
    to_side = await read_relationships.ainvoke({"name": "乙"})
    assert "师徒" in from_side
    assert "师徒" in to_side


@pytest.mark.asyncio
async def test_add_relationship_edge_rejects_unknown_name(monkeypatch, tmp_path):
    _setup_roster(monkeypatch, tmp_path, ["甲"])
    db_path = _patch_edges_db(monkeypatch, tmp_path, ["甲"])

    out = await add_relationship_edge.ainvoke({
        "from_name": "甲", "to_name": "路人", "nature": "世仇",
        "relationship_anchor": "", "from_ref_terms": [], "to_ref_terms": [],
    })
    assert "校验未通过" in out and "路人" in out
    from engine.setup.cast.relationship_graph import load_graph
    assert load_graph(db_path)["edges"] == {}


@pytest.mark.asyncio
async def test_remove_relationship_edge_removes_and_is_idempotent(monkeypatch, tmp_path):
    _setup_roster(monkeypatch, tmp_path, ["甲", "乙"])
    _patch_edges_db(monkeypatch, tmp_path, ["甲", "乙"])

    await add_relationship_edge.ainvoke({
        "from_name": "甲", "to_name": "乙", "nature": "世仇",
        "relationship_anchor": "", "from_ref_terms": [], "to_ref_terms": [],
    })
    out = await remove_relationship_edge.ainvoke({"from_name": "甲", "to_name": "乙"})
    assert "已删除" in out

    after = await read_relationships.ainvoke({"name": "甲"})
    assert "没有任何边" in after

    out2 = await remove_relationship_edge.ainvoke({"from_name": "甲", "to_name": "乙"})
    assert "没有找到" in out2


def test_delete_character_args_requires_nonempty_name():
    from engine.setup_chat.tool_args import DeleteCharacterArgs

    with pytest.raises(ValidationError):
        DeleteCharacterArgs(name="")
    assert DeleteCharacterArgs(name="甲").name == "甲"


def test_delete_chapter_args_requires_chapter_at_least_one():
    from engine.setup_chat.tool_args import DeleteChapterArgs

    with pytest.raises(ValidationError):
        DeleteChapterArgs(chapter=0)
    assert DeleteChapterArgs(chapter=3).chapter == 3


@pytest.mark.asyncio
async def test_delete_character_tool_forwards_to_core(monkeypatch, tmp_path):
    _patch_empty_plot(monkeypatch, tmp_path)
    _setup_roster(monkeypatch, tmp_path, ["甲"])
    _patch_edges_db(monkeypatch, tmp_path, ["甲"])
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "engine.archive.archive_view.delete_character_archives",
        lambda name: {"removed_stages": 0, "deleted_chapters": []},
    )
    monkeypatch.setattr(
        "engine.setup_chat.timeline_auto.schedule_timeline_cascade", lambda *a, **k: None,
    )

    from engine.setup_chat.tools import delete_character

    out = await delete_character.ainvoke({"name": "甲"})
    assert "已删除角色「甲」" in out


@pytest.mark.asyncio
async def test_delete_chapter_tool_forwards_to_core(monkeypatch, tmp_path):
    _isolate_timeline(tmp_path, monkeypatch)
    seed_plot([{"chapter": 1, "title": "一", "stages": []}])
    import utils.paths as up
    chapters_root = tmp_path / "chapters"
    monkeypatch.setattr(up, "chapters_dir", lambda: str(chapters_root))

    from engine.setup_chat.tools import delete_chapter

    out = await delete_chapter.ainvoke({"chapter": 1})
    assert "已删除第 1 章" in out


def test_agent_registers_delete_tools():
    import inspect

    import engine.setup_chat.agent as a

    src = inspect.getsource(a.build_agent)
    assert "delete_character" in src
    assert "delete_chapter" in src


@pytest.mark.asyncio
async def test_add_character_persists_without_inline_quality_gate(monkeypatch, tmp_path):
    """Write-first: add_character persists immediately with no inline quality gate."""
    seed_lore([_full_char("甲")])
    monkeypatch.setattr(
        "engine.setup_chat.character_visual_tags.schedule_extract_visual_tags",
        lambda name: None,
    )

    out = await add_character.ainvoke(_args("乙"))

    assert "已添加" in out and "乙" in out
    assert any(c.get("name") == "乙" for c in lore_raw())
    del tmp_path


@pytest.mark.asyncio
async def test_edit_character_persists_under_new_name(monkeypatch, tmp_path):
    from engine.setup_chat.tools import _edit_character_core

    seed_lore([_full_char("甲")])
    monkeypatch.setattr(
        "engine.setup_chat.timeline_auto.schedule_timeline_cascade", lambda *a, **k: None,
    )

    args = _args("甲")
    args["given_name"] = "甲改名"
    ok, msg, char = await _edit_character_core(name="甲", **args)

    assert ok is True and char is not None
    assert any(c.get("name") == "甲改名" for c in lore_raw())
    del tmp_path, msg


@pytest.mark.asyncio
async def test_add_character_stores_portrait_identity_tags(monkeypatch, tmp_path):
    seed_lore([_full_char("甲")])
    monkeypatch.setattr(
        "engine.setup_chat.character_visual_tags.schedule_extract_visual_tags", lambda name: None,
    )

    await add_character.ainvoke({
        **_args("乙"), "portrait_identity_tags": "  shiroko (blue archive), blue archive  ",
    })

    stored = next(c for c in lore_raw() if c.get("name") == "乙")
    assert stored["portrait_identity_tags"] == "shiroko (blue archive), blue archive"
    del tmp_path


@pytest.mark.asyncio
async def test_edit_character_identity_tags_set_and_preserve(monkeypatch, tmp_path):
    from engine.setup_chat.tools import _edit_character_core

    base = _full_char("甲")
    base["portrait_identity_tags"] = "old anchor"
    seed_lore([base])
    monkeypatch.setattr(
        "engine.setup_chat.timeline_auto.schedule_timeline_cascade", lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "engine.setup_chat.character_visual_tags.schedule_extract_visual_tags", lambda name: None,
    )

    # omitting the field keeps the stored anchor
    ok, _, _ = await _edit_character_core(name="甲", **_args("甲"))
    assert ok
    assert next(c for c in lore_raw() if c["name"] == "甲")["portrait_identity_tags"] == "old anchor"

    # passing it overrides (and strips)
    ok, _, _ = await _edit_character_core(
        name="甲", portrait_identity_tags="  shiroko (blue archive)  ", **_args("甲"),
    )
    assert ok
    assert next(c for c in lore_raw() if c["name"] == "甲")["portrait_identity_tags"] == "shiroko (blue archive)"
    del tmp_path


@pytest.mark.asyncio
async def test_edit_character_never_reextracts_or_clobbers_portrait_tags(monkeypatch, tmp_path):
    from engine.setup_chat.tools import _edit_character_core

    base = _full_char("甲")
    base["portrait_visual_tags"] = "1girl, stored"
    base["portrait_path"] = "甲-1.png"
    seed_lore([base])
    monkeypatch.setattr(
        "engine.setup_chat.timeline_auto.schedule_timeline_cascade", lambda *a, **k: None,
    )
    reextract: list[str] = []
    monkeypatch.setattr(
        "engine.setup_chat.character_visual_tags.schedule_extract_visual_tags",
        lambda name: reextract.append(name),
    )

    # a physique change: stored portrait_visual_tags + portrait_path carried forward verbatim,
    # and no background re-extraction is scheduled.
    args = _args("甲")
    args["physique"] = {k: "changed" for k in args["physique"]}
    ok, _, _ = await _edit_character_core(name="甲", **args)
    assert ok
    stored = next(c for c in lore_raw() if c["name"] == "甲")
    assert stored["portrait_visual_tags"] == "1girl, stored"
    assert stored["portrait_path"] == "甲-1.png"
    assert reextract == []
    del tmp_path
