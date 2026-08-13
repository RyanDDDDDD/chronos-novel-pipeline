"""scripts/strip_plot_clothing_field.py: retire the per-stage clothing key from every novel's
plot_library.json (see docs/superpowers/specs/2026-07-19-retire-plot-clothing-field-design.md)."""
import json

import pytest

from scripts.strip_plot_clothing_field import strip_plot_clothing_field
from tests.conftest import seed_registry_novel


@pytest.fixture
def novels_root(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.delenv("CHRONOS_ACTIVE_NOVEL", raising=False)
    return tmp_path


def _seed_novel(novels_root, nid: str, name: str, plot: list[dict] | None = None) -> None:
    seed_registry_novel(novels_root, nid, name)
    if plot is not None:
        (novels_root / nid / "plot" / "plot_library.json").write_text(
            json.dumps(plot, ensure_ascii=False), encoding="utf-8"
        )


def test_strips_clothing_across_novels_and_skips_clean_ones(novels_root):
    _seed_novel(novels_root, "novel-a", "甲部", plot=[
        {"chapter": 1, "title": "一", "core_xp": [], "stages": [
            {"stage_num": 1, "title": "s1", "location": "屋内", "description": "d",
             "characters": {"甲": {}}, "clothing": {"甲": "校服"}},
            {"stage_num": 2, "title": "s2", "location": "屋外", "description": "d2",
             "characters": {"甲": {}}},
        ]},
    ])
    _seed_novel(novels_root, "novel-b", "乙部", plot=[
        {"chapter": 1, "title": "一", "core_xp": [], "stages": [
            {"stage_num": 1, "title": "s1", "location": "野", "description": "d3",
             "characters": {"甲": {}}},  # already clean
        ]},
    ])
    _seed_novel(novels_root, "novel-c", "丙部")  # no plot_library.json at all

    affected = strip_plot_clothing_field()

    assert affected == {"novel-a": 1}
    saved_a = json.loads((novels_root / "novel-a" / "plot" / "plot_library.json")
                         .read_text(encoding="utf-8"))
    assert "clothing" not in saved_a[0]["stages"][0]
    assert saved_a[0]["stages"][0]["characters"] == {"甲": {}}  # untouched
    saved_b = json.loads((novels_root / "novel-b" / "plot" / "plot_library.json")
                         .read_text(encoding="utf-8"))
    assert saved_b[0]["stages"][0]["location"] == "野"  # untouched, byte-shape aside


def test_noop_when_no_clothing_anywhere(novels_root):
    _seed_novel(novels_root, "novel-a", "甲部", plot=[
        {"chapter": 1, "title": "一", "core_xp": [], "stages": [
            {"stage_num": 1, "title": "s1", "location": "野", "description": "d",
             "characters": {"甲": {}}},
        ]},
    ])
    assert strip_plot_clothing_field() == {}


def test_noop_when_no_novels_exist(novels_root):
    assert strip_plot_clothing_field() == {}
