"""JsonStore universal document write-through + save_lore/save_plot/save_archive write-through test."""
import json


def test_save_doc_writes_disk_and_updates_cache(tmp_path):
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "backend"))
    from repositories.json_store import JsonStore

    s = JsonStore()
    p = str(tmp_path / "world.json")
    s.save_doc("world_bible", p, {"tone": "dark"})
    #The disk has been updated
    assert json.loads(open(p, encoding="utf-8").read()) == {"tone": "dark"}
    #Read immediately by the same process (cache = disk image, no reset required)
    assert s.get_doc("world_bible", p) == {"tone": "dark"}


def test_get_doc_reads_disk_on_miss(tmp_path):
    from repositories.json_store import JsonStore

    p = tmp_path / "w.json"
    p.write_text(json.dumps({"a": 1}), encoding="utf-8")
    s = JsonStore()
    assert s.get_doc("w", str(p)) == {"a": 1}
    assert s.get_doc("w2", str(tmp_path / "nope.json")) is None  #File does not exist → None


def test_reset_clears_doc_cache(tmp_path, monkeypatch):
    from repositories.json_store import JsonStore

    p = str(tmp_path / "w.json")
    s = JsonStore()
    s.save_doc("w", p, {"v": 1})
    monkeypatch.setattr(s, "_scan_lore", lambda: None)
    monkeypatch.setattr(s, "_scan_plot", lambda: None)
    s.reset()
    assert s._docs == {}


# --- Task 2: save_lore / save_plot ---

def test_save_lore_writes_and_refreshes_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("repositories.json_store.lore_library_path", lambda: str(tmp_path / "lore.json"))
    from repositories.json_store import JsonStore

    s = JsonStore()
    s.save_lore([{"name": "甲", "gender": "female"}])
    assert json.loads(open(str(tmp_path / "lore.json"), encoding="utf-8").read())[0]["name"] == "甲"
    assert s.get_lore("甲")["gender"] == "female"  #Cache flushed


def test_save_plot_writes_and_refreshes(tmp_path, monkeypatch):
    monkeypatch.setattr("repositories.json_store.plot_library_path", lambda: str(tmp_path / "plot.json"))
    from repositories.json_store import JsonStore

    s = JsonStore()
    s.save_plot([{"chapter": 1, "title": "T", "stages": []}])
    assert s.get_outline(1)["title"] == "T"


# --- Task 3: save_archive ---

def test_save_archive_writes_disk_and_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("repositories.json_store.get_character_archive_dir", lambda ch: str(tmp_path))
    from repositories.json_store import JsonStore

    s = JsonStore()
    s.save_archive("甲", 1, {"name": "甲", "chapter": 1, "stages": {}})
    f = tmp_path / "甲_ch01_archive.json"
    assert f.exists() and json.loads(f.read_text(encoding="utf-8"))["name"] == "甲"
    assert s.get_archive("甲", 1)["chapter"] == 1  #cache hit
