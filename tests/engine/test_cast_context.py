"""cast grounding: Read world_bible to get the world context; if there is no world, an error will be reported."""
import json

import pytest
from engine.setup.cast.context import load_cast_grounding


def test_grounding_reads_world(tmp_path, monkeypatch):
    base = tmp_path / "bookA"
    (base / "world").mkdir(parents=True)
    (base / "world" / "world_bible.json").write_text(json.dumps({
        "background": "题材占位", "tone": "暗黑", "core_themes": [{"name": "支配", "desc": "d"}],
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "bookA")

    g = load_cast_grounding()
    assert "题材占位" in g["world_text"] and "暗黑" in g["world_text"] and "支配" in g["world_text"]


def test_grounding_missing_world_raises(tmp_path, monkeypatch):
    (tmp_path / "bookA").mkdir(parents=True)
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "bookA")
    with pytest.raises(ValueError):
        load_cast_grounding()


def test_grounding_empty_world_raises(tmp_path, monkeypatch):
    base = tmp_path / "bookA"
    (base / "world").mkdir(parents=True)
    (base / "world" / "world_bible.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "bookA")
    with pytest.raises(ValueError):
        load_cast_grounding()
