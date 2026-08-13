"""One-shot migration: fold old role-keyed character_schema.json rubrics into each
character's own sliders.levels where the axis name matches; leave the rest for
edit_character to backfill later (see 2026-07-30 spec)."""
import json
import os

import pytest


def _write_novel(tmp_path, schema: dict, characters: list[dict]) -> str:
    novel_dir = tmp_path / "novel-x"
    os.makedirs(novel_dir / "world", exist_ok=True)
    os.makedirs(novel_dir / "lore", exist_ok=True)
    (novel_dir / "world" / "character_schema.json").write_text(
        json.dumps(schema, ensure_ascii=False), encoding="utf-8"
    )
    (novel_dir / "lore" / "character_lore_library.json").write_text(
        json.dumps(characters, ensure_ascii=False), encoding="utf-8"
    )
    return str(novel_dir)


def test_matching_axis_gets_levels_copied(tmp_path):
    from scripts.migrate_slider_schema import migrate_novel

    schema = {"roles": {"某类角色": {"sliders": {
        "投入": {"levels": {"0": "克制", "1": "掌控", "2": "君临"}},
    }}}}
    characters = [{
        "name": "角色甲", "role": "某类角色",
        "sliders": {"投入": {"level": 1, "text": "略有保留的描述"}},
    }]
    novel_dir = _write_novel(tmp_path, schema, characters)

    result = migrate_novel(novel_dir)

    saved = json.loads((tmp_path / "novel-x" / "lore" / "character_lore_library.json").read_text(encoding="utf-8"))
    assert saved[0]["sliders"]["投入"]["levels"] == {"0": "克制", "1": "掌控", "2": "君临"}
    assert ("角色甲", "投入") in result["migrated"]
    assert result["skipped"] == []


def test_mismatched_axis_is_skipped_not_guessed(tmp_path):
    from scripts.migrate_slider_schema import migrate_novel

    schema = {"roles": {"某类角色": {"sliders": {
        "沦陷进度": {"levels": {"0": "懵懂", "1": "略有保留", "2": "全情投入"}},
    }}}}
    characters = [{
        "name": "角色甲", "role": "某类角色",
        "sliders": {"成长主动性": {"level": 2, "text": "已有的具体描述"}},
    }]
    novel_dir = _write_novel(tmp_path, schema, characters)

    result = migrate_novel(novel_dir)

    saved = json.loads((tmp_path / "novel-x" / "lore" / "character_lore_library.json").read_text(encoding="utf-8"))
    assert "levels" not in saved[0]["sliders"]["成长主动性"]
    assert result["migrated"] == []
    assert ("角色甲", "成长主动性") in result["skipped"]


def test_already_migrated_axis_left_untouched(tmp_path):
    from scripts.migrate_slider_schema import migrate_novel

    schema = {"roles": {"某类角色": {"sliders": {
        "投入": {"levels": {"0": "新a", "1": "新b", "2": "新c"}},
    }}}}
    characters = [{
        "name": "角色甲", "role": "某类角色",
        "sliders": {"投入": {
            "level": 1, "text": "x",
            "levels": {"0": "旧a", "1": "旧b", "2": "旧c"},
        }},
    }]
    novel_dir = _write_novel(tmp_path, schema, characters)

    result = migrate_novel(novel_dir)

    saved = json.loads((tmp_path / "novel-x" / "lore" / "character_lore_library.json").read_text(encoding="utf-8"))
    assert saved[0]["sliders"]["投入"]["levels"] == {"0": "旧a", "1": "旧b", "2": "旧c"}
    assert result["migrated"] == [] and result["skipped"] == []


def test_no_schema_file_is_noop(tmp_path):
    from scripts.migrate_slider_schema import migrate_novel

    novel_dir = tmp_path / "novel-y"
    os.makedirs(novel_dir / "lore", exist_ok=True)
    (novel_dir / "lore" / "character_lore_library.json").write_text(
        json.dumps([{"name": "角色甲", "role": "某类角色", "sliders": {"投入": {"level": 0, "text": "x"}}}]),
        encoding="utf-8",
    )
    result = migrate_novel(str(novel_dir))
    assert result == {"migrated": [], "skipped": [("角色甲", "投入")]}
