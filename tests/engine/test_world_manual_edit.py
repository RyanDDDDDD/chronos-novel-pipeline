"""patch_world_field: manual-edit merge-one-field-and-write-through for world_bible."""
import json

from engine.setup.world.manual_edit import patch_world_field
from repo_test_helpers import get_world, init_store, seed_world


def test_patch_scalar_field_merges_without_touching_others(monkeypatch, tmp_path):
    del monkeypatch, tmp_path
    seed_world({"background": "旧背景", "tone": "旧基调"})

    ok, msg = patch_world_field("background", "新背景")
    assert ok is True and "background" in msg
    saved = get_world()
    assert saved is not None
    assert saved["background"] == "新背景"
    assert saved["tone"] == "旧基调"


def test_patch_list_field_replaces_whole_array(monkeypatch, tmp_path):
    del monkeypatch, tmp_path
    seed_world({"factions": [{"name": "旧势力", "desc": "x"}]})

    ok, _msg = patch_world_field("factions", [{"name": "新势力", "desc": "y"}, {"name": "势力2", "desc": "z"}])
    assert ok is True
    saved = get_world()
    assert saved is not None
    assert [f["name"] for f in saved["factions"]] == ["新势力", "势力2"]


def test_patch_power_system_field_replaces_whole_array(monkeypatch, tmp_path):
    del monkeypatch, tmp_path
    seed_world({"power_system": "旧文本"})

    ok, _msg = patch_world_field("power_system", [{"name": "蛊虫", "desc": "y"}])
    assert ok is True
    saved = get_world()
    assert saved is not None
    assert saved["power_system"] == [{"name": "蛊虫", "desc": "y"}]


def test_patch_unknown_field_rejected(monkeypatch, tmp_path):
    del monkeypatch, tmp_path
    seed_world({})

    ok, msg = patch_world_field("not_a_real_field", "x")
    assert ok is False and "未知字段" in msg


def test_patch_creates_doc_when_missing(monkeypatch, tmp_path):
    del monkeypatch, tmp_path
    init_store()

    ok, _msg = patch_world_field("tone", "阴郁")
    assert ok is True
    saved = get_world()
    assert saved is not None
    assert saved["tone"] == "阴郁"


def test_patch_named_list_field_invalidates_entity_vocab_cache(monkeypatch, tmp_path):
    """A power_system/factions/geography/races edit adds/renames scannable entity names --
    the process-level Aho-Corasick vocab cache (entity_index.py) must be invalidated so
    recall_relevant_context picks up the new name on the very next turn, without requiring a
    novel switch or server restart."""
    del tmp_path
    seed_world({"power_system": [{"name": "旧名", "desc": "d"}]})

    calls = []
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.invalidate_entity_vocab_cache",
        lambda: calls.append(1),
    )

    ok, _msg = patch_world_field("power_system", [{"name": "新名", "desc": "d2"}])
    assert ok is True
    assert calls == [1]


def test_patch_scalar_field_does_not_invalidate_entity_vocab_cache(monkeypatch, tmp_path):
    """tone/background are free text, never scanned for entity names -- invalidating
    the cache for these would just be wasted work on every save."""
    del tmp_path
    seed_world({"tone": "旧基调"})

    calls = []
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.invalidate_entity_vocab_cache",
        lambda: calls.append(1),
    )

    ok, _msg = patch_world_field("tone", "新基调")
    assert ok is True
    assert calls == []


def test_patch_core_themes_field_invalidates_entity_vocab_cache(monkeypatch, tmp_path):
    """core_themes now participates in recall (via optional keywords) -- editing
    it must invalidate the cache same as power_system/factions/geography/races."""
    del tmp_path
    seed_world({"core_themes": [{"name": "旧主题", "desc": "d"}]})

    calls = []
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.invalidate_entity_vocab_cache",
        lambda: calls.append(1),
    )

    ok, _msg = patch_world_field("core_themes", [{"name": "新主题", "desc": "d"}])
    assert ok is True
    assert calls == [1]
