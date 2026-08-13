"""plot grounding reads: cast list/world summary (personality lives on timeline, grounding no longer reads it)."""
import pytest
from engine.setup.plot.context import load_plot_grounding
from repo_test_helpers import seed_lore, seed_world


def test_grounding_reads_cast(monkeypatch):
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "bookA")
    from repositories import reset_repositories
    reset_repositories()
    seed_lore([
        {"name": "甲", "causal_anchors": {"stance": "submissive", "wound": "w"}},
        {"name": "乙", "causal_anchors": {"stance": "dominant", "drive": "d"}},
    ])

    g = load_plot_grounding()
    assert g["character_names"] == ["甲", "乙"]
    assert "archetypes" not in g  # personality lives on timeline; grounding no longer returns it
    assert "甲" in g["cast_text"] and "乙" in g["cast_text"]
    assert g["world_text"] == ""  #None world_bible


def test_grounding_includes_world_when_present(monkeypatch):
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "bookA")
    from repositories import reset_repositories
    reset_repositories()
    seed_lore([{"name": "甲", "causal_anchors": {}}])
    seed_world({"background": "题材占位", "tone": "暗黑"})

    g = load_plot_grounding()
    assert "题材占位" in g["world_text"]


def test_grounding_empty_cast_raises(monkeypatch):
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "bookA")
    from repositories import reset_repositories
    reset_repositories()
    seed_lore([])
    with pytest.raises(ValueError):
        load_plot_grounding()
