# tests/repositories/test_json_store.py
import json

import pytest
from repositories.json_store import JsonStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    lore = tmp_path / "lore.json"
    lore.write_text(json.dumps([{"name": "甲", "gender": "female", "role": "lead"}]), encoding="utf-8")
    plot = tmp_path / "plot.json"
    plot.write_text(json.dumps({"第1章": {"title": "T", "stages": []}}), encoding="utf-8")
    monkeypatch.setattr("repositories.json_store.lore_library_path", lambda: str(lore))
    monkeypatch.setattr("repositories.json_store.plot_library_path", lambda: str(plot))
    s = JsonStore()
    s.scan()
    return s

def test_get_lore(store):
    assert store.get_lore("甲")["gender"] == "female"
    assert store.get_lore("无")  is None

def test_get_outline(store):
    assert store.get_outline(1)["title"] == "T"

def test_archive_cache_put_get_evict(store):
    store.put_archive("甲", 2, {"name": "甲", "chapter": 2})
    assert store.get_archive("甲", 2)["chapter"] == 2
    assert store.evict_archive_from(2) == 1
    #The touch pad path does not exist → Return to None
    monkey_dir = "/nonexistent"
    import repositories.json_store as m
    m.get_character_archive_dir = lambda ch: monkey_dir
    assert store.get_archive("甲", 2) is None
