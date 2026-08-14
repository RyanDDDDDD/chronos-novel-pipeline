"""tests/scripts/test_flatten_character_archives.py"""
import json

from scripts.flatten_character_archives import flatten_character_archives

from repo_test_helpers import seed_lore, seed_plot

_NOVEL_ID = "test-novel"


def _common_setup(tmp_path, monkeypatch, lore, plot):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", _NOVEL_ID)
    (tmp_path / _NOVEL_ID).mkdir(parents=True, exist_ok=True)
    import repositories

    repositories.init_repositories(_NOVEL_ID)
    seed_lore(lore)
    seed_plot(plot)

    def _arc_dir(ch: int) -> str:
        d = tmp_path / _NOVEL_ID / "chapters" / f"第{ch}章" / "characters"
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    import utils.paths as paths_mod
    monkeypatch.setattr(paths_mod, "get_character_archive_dir", _arc_dir)

    return _arc_dir


def _write_legacy_archive(arc_dir, name: str, chapter: int, payload: dict) -> None:
    path = f"{arc_dir(chapter)}/{name}_ch{chapter:02d}_archive.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def test_collapses_multi_stage_timeline_and_flattens_archive(tmp_path, monkeypatch):
    lore = [{"name": "甲", "given_name": "甲", "role": "同质堕落型",
             "causal_anchors": {}, "sliders": {}}]
    plot = [
        {"chapter": 1, "title": "一", "core_xp": [], "stages": [
            {"stage_num": 1, "title": "s", "location": "屋内", "description": "事件",
             "characters": {"甲": {}}},
            {"stage_num": 2, "title": "s2", "location": "屋外", "description": "续",
             "characters": {"甲": {}}},
        ]},
        {"chapter": 2, "title": "二", "core_xp": [], "stages": [
            {"stage_num": 1, "title": "s", "location": "屋外", "description": "续章",
             "characters": {"甲": {}}},
        ]},
    ]
    arc_dir = _common_setup(tmp_path, monkeypatch, lore, plot)

    from context import character_timeline
    character_timeline.append_stage("甲", 1, 1, {"personality": "外冷内热", "clothing": "室内便装"})
    character_timeline.append_stage("甲", 1, 2, {"clothing": "室外大衣"})
    character_timeline.append_stage("甲", 2, 1, {"personality": "依旧外冷内热"})  # 单快照章节

    # Legacy nested archive.json files on disk for both chapters (pre-migration shape).
    _write_legacy_archive(arc_dir, "甲", 1, {
        "name": "甲", "role": "同质堕落型", "extensions": {},
        "stages": {"1": {"personality": "旧"}, "2": {"personality": "旧"}},
    })
    _write_legacy_archive(arc_dir, "甲", 2, {
        "name": "甲", "role": "同质堕落型", "extensions": {},
        "stages": {"1": {"personality": "旧"}},
    })

    affected = flatten_character_archives()

    assert affected == {"甲": [1, 2]}
    snaps = character_timeline.load_timeline("甲")["snapshots"]
    ch1_snaps = [s for s in snaps if s["chapter"] == 1]
    assert len(ch1_snaps) == 1
    assert ch1_snaps[0]["stage"] == 1
    assert ch1_snaps[0]["delta"]["personality"] == "外冷内热"

    import repositories
    arch1 = repositories.get_archive_repo().get("甲", 1)
    arch2 = repositories.get_archive_repo().get("甲", 2)
    assert arch1 is not None and arch2 is not None
    assert "stages" not in arch1.model_dump()
    assert arch1.personality == "外冷内热"
    assert "stages" not in arch2.model_dump()
    assert arch2.personality == "依旧外冷内热"


def test_skips_chapters_without_an_existing_archive_file(tmp_path, monkeypatch):
    lore = [{"name": "甲", "given_name": "甲", "role": "同质堕落型",
             "causal_anchors": {}, "sliders": {}}]
    plot = [{"chapter": 1, "title": "一", "core_xp": [], "stages": [
        {"stage_num": 1, "title": "s", "location": "屋内", "description": "事件",
         "characters": {"甲": {}}},
    ]}]
    _common_setup(tmp_path, monkeypatch, lore, plot)

    from context import character_timeline
    character_timeline.append_stage("甲", 1, 1, {"personality": "外冷内热"})

    # No archive.json written to disk for chapter 1.
    affected = flatten_character_archives()
    assert affected == {}


def test_noop_when_no_timeline_data_exists(tmp_path, monkeypatch):
    lore = [{"name": "甲", "given_name": "甲", "role": "同质堕落型",
             "causal_anchors": {}, "sliders": {}}]
    _common_setup(tmp_path, monkeypatch, lore, [])

    affected = flatten_character_archives()
    assert affected == {}
