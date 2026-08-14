import inspect

import pytest
from engine.setup_chat.tools import edit_character
from pydantic import ValidationError

from repo_test_helpers import init_store, lore_raw, save_archive, seed_lore, seed_plot


@pytest.fixture(autouse=True)
def _no_world_races(monkeypatch):
    from engine.setup.cast import cast_validator as cv
    monkeypatch.setattr(cv, "_load_world_race_names", lambda: [], raising=False)


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


def _schema():
    return {"roles": {"甲": {"sliders": {"投入": {"levels": {"0": "a", "1": "b", "2": "c"}}}}}}


def _character_args(given_name: str, *, role: str = "甲") -> dict:
    from engine.setup.cast.stance_schema import physique_slots

    return {
        "given_name": given_name, "role": role, "gender": "female",
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
        "武器": "尚待观察",
        "流派": "尚待观察",
        "身份": "尚待观察",
    }


def _edit_args(lookup: str, given_name: str | None = None, **kwargs) -> dict:
    return {"name": lookup, **_character_args(given_name or lookup, **kwargs)}


def _full_char(name: str, *, role: str = "甲") -> dict:
    body = _character_args(name, role=role)
    return {
        "name": name, "given_name": name, "role": body["role"], "gender": body["gender"],
        "race": body["race"], "causal_anchors": body["causal_anchors"], "physique": body["physique"],
        "clothing_dna": {
            "color_palette": body["clothing_color_palette"],
            "materials_preference": body["clothing_materials"],
            "signature_outfit": body["clothing_signature_outfit"],
            "accessories": body["clothing_accessories"],
        },
        "sliders": body["sliders"],
    }


def _isolate_archive_paths(monkeypatch, tmp_path):
    """archive_view reads SQLite only (2026-08-09); repo isolation comes from engine conftest."""
    del monkeypatch, tmp_path
    init_store()


def _isolate_timeline(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    import repositories
    repositories.reset_repositories()


@pytest.mark.asyncio
async def test_edit_character_ok(monkeypatch, tmp_path):
    seed_lore([_full_char("甲"), _full_char("乙")])
    _isolate_archive_paths(monkeypatch, tmp_path)

    out = await edit_character.ainvoke(_edit_args("甲", role="甲"))
    assert "已更新角色「甲」" in out
    assert "角色位 甲" in out
    saved = lore_raw()
    assert saved[0]["role"] == "甲" and saved[1]["name"] == "乙"


@pytest.mark.asyncio
async def test_edit_character_not_found(monkeypatch, tmp_path):
    del monkeypatch, tmp_path
    seed_lore([_full_char("甲")])

    out = await edit_character.ainvoke(_edit_args("丙"))
    assert "未找到" in out and "甲" in out


@pytest.mark.asyncio
async def test_edit_character_validation_error_not_written(monkeypatch, tmp_path):
    del monkeypatch, tmp_path
    seed_lore([_full_char("甲", role="x")])

    args = _edit_args("甲")
    del args["physique"]["胸部"]
    with pytest.raises(ValidationError) as exc:
        await edit_character.ainvoke(args)
    assert "胸部" in str(exc.value)
    assert lore_raw()[0]["role"] == "x"


@pytest.mark.asyncio
async def test_edit_character_clears_timeline_and_archives(monkeypatch, tmp_path):
    _isolate_timeline(tmp_path, monkeypatch)
    seed_lore([_full_char("甲"), _full_char("乙")])
    seed_plot([{"chapter": 1}])

    from context import character_timeline as ct
    ct.append_stage("甲", 1, 1, {"state": {}})

    save_archive("甲", 1, {"name": "甲", "stages": {}})
    save_archive("乙", 1, {"name": "乙", "stages": {}})

    out = await edit_character.ainvoke(_edit_args("甲", role="甲"))
    assert "已更新角色「甲」" in out
    assert "已清空" in out
    assert ct.load_timeline("甲")["snapshots"] == []

    from repositories import get_archive_repo

    assert get_archive_repo().get("甲", 1) is None
    assert get_archive_repo().get("乙", 1) is not None


@pytest.mark.asyncio
async def test_edit_character_rename_conflict(monkeypatch, tmp_path):
    del monkeypatch, tmp_path
    seed_lore([_full_char("甲"), _full_char("乙")])

    out = await edit_character.ainvoke(_edit_args("甲", given_name="乙"))
    assert "已存在" in out
    assert lore_raw()[0]["name"] == "甲"


def test_agent_registers_edit_tools():
    import engine.setup_chat.agent as a

    src = inspect.getsource(a.build_agent)
    assert "edit_character" in src
    assert "WORLD_DIMENSION_TOOLS" in src or "set_world_background" in src
    assert "write_setup" not in src
