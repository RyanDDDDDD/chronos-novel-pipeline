import json

import pytest
from fastapi.testclient import TestClient

from repo_test_helpers import get_world, lore_raw, seed_lore, seed_plot, seed_world


@pytest.fixture(autouse=True)
def _neutral_baseline_custom_fields(monkeypatch):
    import context.content_packs as cp

    monkeypatch.setattr(
        cp,
        "custom_fields",
        lambda: [
            cp.CustomFieldSpec(name="武器", required=True),
            cp.CustomFieldSpec(name="流派", required=True),
            cp.CustomFieldSpec(name="身份", required=True),
        ],
    )


@pytest.fixture(autouse=True)
def _disable_setup_quality_review(monkeypatch):
    """Setup Page cast POST/PATCH routes call _add_character_core, which now runs
    setup quality gate -- thin test fixtures must not trigger LLM/precheck failures."""
    import engine.modes.author_loop_skill_prefs as prefs_mod
    from engine.setup_chat import setup_quality_review as sqr

    real = prefs_mod.load_dialogue_prefs

    def _patched() -> dict:
        prefs = real()
        prefs["disabled_setup_review_hooks"] = list(
            sqr.SETUP_WORLD_HOOK_NAMES + sqr.SETUP_CAST_HOOK_NAMES
        )
        return prefs

    monkeypatch.setattr(prefs_mod, "load_dialogue_prefs", _patched)


def _seed_novel(tmp_path, monkeypatch, *, world=None, cast=None, plot=None):
    novels_root = tmp_path / "novels"
    d = novels_root / "default"
    d.mkdir(parents=True)
    (d / "novel.json").write_text(json.dumps({"name": "默认"}), encoding="utf-8")
    (novels_root / "active.json").write_text(json.dumps({"active": "default"}), encoding="utf-8")
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(novels_root))
    import repositories
    repositories.init_repositories()
    if world is not None:
        seed_world(world)
    if cast is not None:
        seed_lore(cast)
    if plot is not None:
        seed_plot(plot)


def _plot_raw():
    import repositories as repo

    return repo.get_plot_repo().list_raw()


def _character(name: str) -> dict:
    from engine.setup.cast.stance_schema import physique_slots
    return {
        "given_name": name, "role": "甲", "gender": "female",
        "causal_anchors": {"执念": "复仇"}, "physique": {k: "x" for k in physique_slots("female")},
        "clothing_color_palette": ["黑"], "clothing_materials": ["皮革"],
        "clothing_signature_outfit": "黑色皮革风日常常服",
        "clothing_accessories": ["皮质腕带"],
        "sliders": {
            "投入": {
                "level": 1,
                "text": "登场时尚有保留",
                "levels": {"0": "a", "1": "b", "2": "c"},
            }
        },
        "personality": "尚待观察", "race": "人",
        "identity_background": "出身平平，家境普通", "hobbies": [], "verbal_tic": "",
        "武器": "尚待观察", "流派": "尚待观察", "身份": "尚待观察",
    }


def test_patch_world_field(tmp_path, monkeypatch):
    _seed_novel(tmp_path, monkeypatch, world={"background": "旧"})
    client = TestClient(app_under_test())
    r = client.patch("/api/setup/world", json={"field": "background", "value": "新"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert get_world()["background"] == "新"


def test_patch_world_unknown_field_400(tmp_path, monkeypatch):
    _seed_novel(tmp_path, monkeypatch, world={})
    client = TestClient(app_under_test())
    r = client.patch("/api/setup/world", json={"field": "nonsense", "value": "x"})
    assert r.status_code == 400 and r.json()["ok"] is False


def test_post_cast_adds_character(tmp_path, monkeypatch):
    _seed_novel(tmp_path, monkeypatch, cast=[])
    client = TestClient(app_under_test())
    r = client.post("/api/setup/cast", json=_character("乙"))
    assert r.status_code == 200 and r.json()["ok"] is True
    assert {c["name"] for c in lore_raw()} == {"乙"}


def test_post_cast_character_does_not_notify_chat(tmp_path, monkeypatch):
    """Manual cast-page create must not inject a system-notice turn into the chat
    transcript -- see _add_character_core's notify_chat param."""
    _seed_novel(tmp_path, monkeypatch, cast=[])
    captured = {}

    async def fake_add_character_core(*, notify_chat=True, **_kwargs):
        captured["notify_chat"] = notify_chat
        return True, "已添加角色「乙」。", {"name": "乙", "given_name": "乙"}

    monkeypatch.setattr(
        "engine.setup_chat.tools._add_character_core", fake_add_character_core,
    )
    client = TestClient(app_under_test())
    r = client.post("/api/setup/cast", json=_character("乙"))
    assert r.status_code == 200 and r.json()["ok"] is True
    assert captured["notify_chat"] is False


def test_post_cast_forwards_content_pack_custom_fields(tmp_path, monkeypatch):
    """Regression: a content-pack-declared custom field (e.g. 武器) reaches add_character
    through **extra, not a named param -- this route's body-to-kwargs mapping must forward it
    by name too, or marking such a field required breaks manual cast editing entirely."""
    import context.content_packs as cp
    monkeypatch.setattr(
        cp, "custom_fields",
        lambda: [cp.CustomFieldSpec(name="武器", required=True)],
    )
    _seed_novel(tmp_path, monkeypatch, cast=[])
    client = TestClient(app_under_test())
    char = _character("乙")
    char["武器"] = "长枪"
    r = client.post("/api/setup/cast", json=char)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert lore_raw()[0]["武器"] == "长枪"


def test_patch_cast_character_manual_visual_tags_override(tmp_path, monkeypatch):
    """Cast detail panel manual edit round trip: an explicit portrait_visual_tags in the
    PATCH body is saved as-is and does not trigger auto re-extraction (see
    _edit_character_core's portrait_visual_tags param) when appearance fields are
    unchanged from the stored character."""
    char = _character("甲")
    char["name"] = char["given_name"]
    char["clothing_dna"] = {
        "color_palette": char.pop("clothing_color_palette"),
        "materials_preference": char.pop("clothing_materials"),
        "signature_outfit": char.pop("clothing_signature_outfit"),
        "accessories": char.pop("clothing_accessories"),
    }
    char["portrait_visual_tags"] = "1girl, old tags"
    _seed_novel(tmp_path, monkeypatch, cast=[char])
    monkeypatch.setattr(
        "engine.archive.archive_view.delete_character_archives",
        lambda name: {"removed_stages": 0, "deleted_chapters": []},
    )

    schedule_calls = []
    monkeypatch.setattr(
        "engine.setup_chat.character_visual_tags.schedule_extract_visual_tags",
        lambda name: schedule_calls.append(name),
    )

    client = TestClient(app_under_test())
    body = _character("甲")
    body["portrait_visual_tags"] = "1girl, hand-typed tags"
    r = client.patch("/api/setup/cast/甲", json=body)

    assert r.status_code == 200 and r.json()["ok"] is True
    assert schedule_calls == []
    assert lore_raw()[0]["portrait_visual_tags"] == "1girl, hand-typed tags"


def test_patch_cast_character_omitted_visual_tags_preserves_cache(tmp_path, monkeypatch):
    """A PATCH body without portrait_visual_tags at all (e.g. an older frontend build, or a
    non-cast-panel caller) must not clear the cached tags -- omission means "didn't touch
    this field", not "clear it"."""
    char = _character("甲")
    char["name"] = char["given_name"]
    char["clothing_dna"] = {
        "color_palette": char.pop("clothing_color_palette"),
        "materials_preference": char.pop("clothing_materials"),
        "signature_outfit": char.pop("clothing_signature_outfit"),
        "accessories": char.pop("clothing_accessories"),
    }
    char["portrait_visual_tags"] = "1girl, old tags"
    _seed_novel(tmp_path, monkeypatch, cast=[char])
    monkeypatch.setattr(
        "engine.archive.archive_view.delete_character_archives",
        lambda name: {"removed_stages": 0, "deleted_chapters": []},
    )
    monkeypatch.setattr(
        "engine.setup_chat.character_visual_tags.schedule_extract_visual_tags",
        lambda name: None,
    )

    client = TestClient(app_under_test())
    r = client.patch("/api/setup/cast/甲", json=_character("甲"))

    assert r.status_code == 200 and r.json()["ok"] is True
    assert lore_raw()[0]["portrait_visual_tags"] == "1girl, old tags"


def test_patch_cast_character_does_not_notify_chat(tmp_path, monkeypatch):
    """Manual cast-page edit must not inject a system-notice turn into the chat transcript
    -- see _edit_character_core's notify_chat param."""
    char = _character("甲")
    char["name"] = char["given_name"]
    _seed_novel(tmp_path, monkeypatch, cast=[char])
    captured = {}

    async def fake_edit_character_core(*, notify_chat=True, **_kwargs):
        captured["notify_chat"] = notify_chat
        return True, "已更新角色「甲」。", {"name": "甲", "given_name": "甲"}

    monkeypatch.setattr(
        "engine.setup_chat.tools._edit_character_core", fake_edit_character_core,
    )
    client = TestClient(app_under_test())
    r = client.patch("/api/setup/cast/甲", json=_character("甲"))
    assert r.status_code == 200 and r.json()["ok"] is True
    assert captured["notify_chat"] is False


def test_patch_cast_character_not_found_404(tmp_path, monkeypatch):
    char = _character("甲")
    char["name"] = char["given_name"]
    _seed_novel(tmp_path, monkeypatch, cast=[char])
    client = TestClient(app_under_test())
    r = client.patch("/api/setup/cast/不存在", json=_character("不存在"))
    assert r.status_code == 404 and r.json()["ok"] is False


def test_delete_cast_character(tmp_path, monkeypatch):
    char = _character("甲")
    char["name"] = char["given_name"]
    _seed_novel(tmp_path, monkeypatch, cast=[char])
    monkeypatch.setattr(
        "engine.archive.archive_view.delete_character_archives",
        lambda name: {"removed_stages": 0, "deleted_chapters": []},
    )
    client = TestClient(app_under_test())
    r = client.delete("/api/setup/cast/甲")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert lore_raw() == []


def test_patch_plot_chapter_title(tmp_path, monkeypatch):
    _seed_novel(tmp_path, monkeypatch, plot=[{"chapter": 1, "title": "旧", "stages": []}])
    client = TestClient(app_under_test())
    r = client.patch("/api/setup/plot/1", json={"title": "新标题"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert _plot_raw()[0]["title"] == "新标题"


def test_read_relationship_graph_uses_load_graph(tmp_path, monkeypatch):
    _seed_novel(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {"男主→女甲": {"from": "男主", "to": "女甲", "nature": "x"}}},
    )
    client = TestClient(app_under_test())
    resp = client.get("/api/setup/relationship-graph")
    assert resp.status_code == 200
    assert resp.json()["graph"]["edges"]["男主→女甲"]["nature"] == "x"


def test_patch_plot_skeleton_stage_replace(tmp_path, monkeypatch):
    char = _character("甲")
    char["name"] = char["given_name"]
    import engine.modes.author_loop_skill_prefs as prefs_mod
    monkeypatch.setattr(
        prefs_mod, "load_dialogue_prefs",
        lambda: {"target_words": 350},
    )
    _seed_novel(tmp_path, monkeypatch, cast=[char], plot=[{
        "chapter": 1, "title": "第一章", "core_xp": [],
        "stages": [{"stage_num": 1, "title": "开场", "location": "客厅", "description": "旧"}],
    }])
    client = TestClient(app_under_test())
    r = client.patch(
        "/api/setup/plot/1/skeleton",
        json={"op": "replace", "stage_num": 1, "fields": {"description": "新描述"}},
    )
    assert r.status_code == 200 and r.json()["ok"] is True
    assert _plot_raw()[0]["stages"][0]["description"] == "新描述"


def test_patch_plot_skeleton_stage_remove_rejected(tmp_path, monkeypatch):
    char = _character("甲")
    char["name"] = char["given_name"]
    _seed_novel(tmp_path, monkeypatch, cast=[char], plot=[{
        "chapter": 1, "title": "第一章", "core_xp": [],
        "stages": [{"stage_num": 1, "title": "开场", "location": "客厅", "description": "旧"}],
    }])
    client = TestClient(app_under_test())
    r = client.patch(
        "/api/setup/plot/1/skeleton",
        json={"op": "remove", "stage_num": 1},
    )
    assert r.status_code == 400 and r.json()["ok"] is False
    assert len(_plot_raw()[0]["stages"]) == 1


def app_under_test():
    from api.hub import app
    return app
