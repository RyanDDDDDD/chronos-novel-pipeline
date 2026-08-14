"""Back-end logic of character profile management page: overview enumeration/single chapter slider rendering/delete arrangement."""
from __future__ import annotations

import engine.archive.archive_view as av
import pytest
from repo_test_helpers import save_archive, seed_lore, seed_plot


@pytest.fixture
def novel(tmp_path, monkeypatch):
    """Build a temporary active novel backed by real SQLite writes (repo_test_helpers) --
    archive_view.py reads exclusively from SQLite (2026-08-09 fix), no filesystem involved."""
    del tmp_path

    def _write_archive(ch: int, name: str, payload: dict) -> None:
        save_archive(name, ch, payload)

    import repositories
    repositories.init_repositories()
    seed_lore([{"name": "角色A"}, {"name": "角色B"}])
    seed_plot([{"chapter": 1}, {"chapter": 2}, {"chapter": 3}])

    return type("N", (), {"write": staticmethod(_write_archive)})


def test_overview_enumerates_built_and_plot(novel):
    seed_plot([{"chapter": 1}, {"chapter": 2}, {"chapter": 3}])
    novel.write(1, "角色A", {"name": "角色A", "stages": {}})
    novel.write(1, "角色B", {"name": "角色B", "stages": {}})
    novel.write(2, "角色A", {"name": "角色A", "stages": {}})
    ov = av.list_archive_overview()
    assert ov["built"] == [
        {"chapter": 1, "characters": ["角色A", "角色B"]},
        {"chapter": 2, "characters": ["角色A"]},
    ]
    assert ov["plot_chapters"] == [
        {"chapter": 1, "roster": [], "built": ["角色A", "角色B"]},
        {"chapter": 2, "roster": [], "built": ["角色A"]},
        {"chapter": 3, "roster": [], "built": []},
    ]


def test_overview_empty(novel):
    seed_plot([{"chapter": 1}, {"chapter": 2}, {"chapter": 3}])
    assert av.list_archive_overview() == {
        "built": [],
        "plot_chapters": [
            {"chapter": 1, "roster": [], "built": []},
            {"chapter": 2, "roster": [], "built": []},
            {"chapter": 3, "roster": [], "built": []},
        ],
    }


def test_render_character_profile_includes_identity_background(monkeypatch):
    arc = {
        "name": "角色A", "role": "测试角色",
        "causal_anchors": {"stance": "submissive"},
        "identity_background": "没落贵族之女，寄人篱下",
        "sliders": {},
    }
    monkeypatch.setattr(
        "engine.archive.sliders.character_rubrics", lambda _name: {},
    )
    out = av.render_character_profile("角色A", arc)
    assert out["identity_background"] == "没落贵族之女，寄人篱下"


def test_render_character_profile_flattens_arc(monkeypatch):
    arc = {
        "name": "角色A", "role": "测试角色",
        "causal_anchors": {"stance": "submissive"},
        "location": "X", "sliders": {"resistance": 4}, "gender": "female",
    }
    monkeypatch.setattr(
        "engine.archive.sliders.character_rubrics",
        lambda _name: {"resistance": {"0": "a", "1": "b", "2": "c"}},
    )
    monkeypatch.setattr(av, "render_slider", lambda rubrics, axis, value: f"{axis}@{value}")

    out = av.render_character_profile("角色A", arc)

    assert out["name"] == "角色A"
    assert out["role"] == "测试角色"
    assert out["causal_anchors"] == {"stance": "submissive"}
    assert out["location"] == "X"
    assert out["gender"] == "female"
    assert out["sliders"]["resistance"] == {"value": 4, "label": "resistance@4"}


def test_render_chapter_renders_sliders(novel, monkeypatch):
    arc = {
        "name": "角色A", "role": "测试角色",
        "causal_anchors": {"stance": "submissive"},
        "location": "X", "sliders": {"resistance": 4}, "gender": "female",
    }
    novel.write(2, "角色A", arc)

    monkeypatch.setattr(
        "engine.archive.sliders.character_rubrics",
        lambda _name: {"resistance": {"0": "a", "1": "b", "2": "c"}},
    )
    monkeypatch.setattr(av, "render_slider", lambda rubrics, axis, value: f"{axis}@{value}")

    out = av.render_chapter_archives(2)
    assert out["chapter"] == 2
    ch = out["characters"][0]
    assert ch["name"] == "角色A" and ch["role"] == "测试角色"
    assert ch["location"] == "X" and ch["gender"] == "female"
    assert ch["sliders"]["resistance"] == {"value": 4, "label": "resistance@4"}


def test_render_chapter_renders_level_text_sliders(novel, monkeypatch):
    arc = {
        "name": "角色A", "role": "测试角色",
        "causal_anchors": {"stance": "submissive"},
        "location": "X", "sliders": {"侵蚀度": {"level": 1, "text": "动摇"}}, "gender": "female",
    }
    novel.write(2, "角色A", arc)

    monkeypatch.setattr("engine.archive.sliders.character_rubrics", lambda _name: {})

    out = av.render_chapter_archives(2)
    ch = out["characters"][0]
    assert ch["sliders"]["侵蚀度"] == {"value": 1, "label": "动摇"}


def test_render_chapter_forwards_hobbies(novel, monkeypatch):
    arc = {
        "name": "角色A", "role": "测试角色",
        "causal_anchors": {"stance": "submissive"},
        "hobbies": ["爱吃甜食", "喜欢刺绣"],
        "sliders": {"侵蚀度": {"level": 1, "text": "动摇"}},
    }
    novel.write(2, "角色A", arc)

    monkeypatch.setattr("engine.archive.sliders.character_rubrics", lambda _name: {})

    ch = av.render_chapter_archives(2)["characters"][0]
    assert ch["hobbies"] == ["爱吃甜食", "喜欢刺绣"]


def test_render_chapter_empty(novel, monkeypatch):
    monkeypatch.setattr("engine.archive.sliders.character_rubrics", lambda _name: {})
    assert av.render_chapter_archives(9) == {"chapter": 9, "characters": []}


def test_delete_from_removes_archives_timeline_and_cache(novel):
    from repositories import get_archive_repo

    novel.write(1, "角色A", {"name": "角色A", "stages": {}})
    novel.write(2, "角色A", {"name": "角色A", "stages": {}})
    novel.write(3, "角色A", {"name": "角色A", "stages": {}})

    from context import character_timeline as ct
    for ch in (1, 2, 3):
        ct.append_stage("角色A", ch, 1, {})

    res = av.delete_archives_from(2)
    assert res["from_chapter"] == 2
    assert res["deleted"]["chapters"] == [2, 3]
    assert res["deleted"]["characters"] == ["角色A"]
    assert get_archive_repo().get("角色A", 1) is not None
    assert get_archive_repo().get("角色A", 2) is None
    assert get_archive_repo().get("角色A", 3) is None
    assert "角色A" in ct.list_timeline_names()
    assert [s["chapter"] for s in ct.load_timeline("角色A")["snapshots"]] == [1]


def test_delete_character_archives_removes_only_that_character(novel):
    from repositories import get_archive_repo

    novel.write(1, "角色A", {"name": "角色A", "stages": {}})
    novel.write(1, "角色B", {"name": "角色B", "stages": {}})
    novel.write(2, "角色A", {"name": "角色A", "stages": {}})

    res = av.delete_character_archives("角色A")
    assert res["name"] == "角色A"
    assert res["deleted_chapters"] == [1, 2]
    assert get_archive_repo().get("角色A", 1) is None
    assert get_archive_repo().get("角色B", 1) is not None
    assert get_archive_repo().get("角色A", 2) is None


def test_delete_character_archives_also_clears_that_characters_timeline(novel):
    """Regression: delete_character_archives used to only delete archive.json and leave the
    timeline untouched, relying on the CALLER to separately truncate it -- a fragile pattern
    where any future caller that forgot to pair the two calls would silently desync them
    again (missing_timeline_targets() only checks timeline presence, so a stale-but-present
    timeline snapshot would make "一键构建" think this chapter was already built forever, even
    though its archive.json was just deleted). This must now be self-contained, mirroring
    delete_archives_from's own self-contained design -- no external truncate_from call
    required."""
    novel.write(1, "角色A", {"name": "角色A", "stages": {}})
    novel.write(1, "角色B", {"name": "角色B", "stages": {}})
    novel.write(2, "角色A", {"name": "角色A", "stages": {}})

    from context import character_timeline as ct
    ct.append_stage("角色A", 1, 1, {})
    ct.append_stage("角色A", 2, 1, {})
    ct.append_stage("角色B", 1, 1, {})

    res = av.delete_character_archives("角色A")
    assert res["removed_stages"] == 2
    assert "角色A" not in ct.list_timeline_names()
    assert "角色B" in ct.list_timeline_names()


def test_render_archive_summary_formats_causal_anchors_and_profile():
    chars = [{
        "name": "角色A", "role": "测试角色",
        "causal_anchors": {"stance": "submissive", "empty_field": ""},
        "location": "X", "self_ref": {"_default": "我"}, "verbal_tic": "呢",
        "sliders": {"resistance": 4},
    }]
    out = av.render_archive_summary(2, chars)
    assert out.splitlines()[0] == "第 2 章角色档案："
    assert "- 角色A（测试角色）" in out
    assert "    · stance：submissive" in out
    assert "empty_field" not in out
    assert "@X" in out
    assert "自称：我" in out
    assert "口癖：呢" in out


def test_render_archive_summary_empty_chars():
    assert av.render_archive_summary(3, []) == "第 3 章角色档案："


def test_list_archive_overview_plot_chapters_include_roster_and_built(monkeypatch):
    plot = [{"chapter": 1, "title": "一", "core_xp": [], "stages": [
        {"stage_num": 1, "location": "L", "description": "甲乙登场"}]}]
    import repositories
    repositories.init_repositories()
    seed_plot(plot)
    #roster is now derived at read time by scanning stage `description` via entity_index.
    #scan_characters instead of reading a persisted `characters` field.
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: [n for n in ("甲", "乙") if n in text],
    )

    out = av.list_archive_overview()
    assert out["plot_chapters"] == [{"chapter": 1, "roster": ["甲", "乙"], "built": []}]
