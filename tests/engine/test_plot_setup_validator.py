"""plot setup validator: Thin package validate_plot, inject cast list (archetype has been returned to timeline, no verification)."""
import engine.modes.author_loop_skill_prefs as prefs_mod
from engine.setup.plot.validator import suggested_min_stage_count, validate_plot_chapters

_NAMES = ["甲", "乙"]


def _stub_target_words(monkeypatch, target_words: int) -> None:
    monkeypatch.setattr(
        prefs_mod, "load_dialogue_prefs",
        lambda: {"target_words": target_words},
    )


def _ok(n_stages: int = 1):
    return [{
        "chapter": 1, "title": "一", "core_xp": ["x"],
        "stages": [
            {"stage_num": i + 1, "title": "s", "location": "城", "description": "d"}
            for i in range(n_stages)
        ],
    }]


def test_valid_passes(monkeypatch):
    _stub_target_words(monkeypatch, 350)  # suggested_min_stage_count(350) == 1
    assert validate_plot_chapters(_ok(1), character_names=_NAMES) == []


def test_missing_stage_field_flagged(monkeypatch):
    _stub_target_words(monkeypatch, 350)
    ch = _ok(1); del ch[0]["stages"][0]["location"]
    assert validate_plot_chapters(ch, character_names=_NAMES)


def test_empty_stages_flagged(monkeypatch):
    _stub_target_words(monkeypatch, 350)
    ch = _ok(1); ch[0]["stages"] = []
    errs = validate_plot_chapters(ch, character_names=_NAMES)
    assert any("stages" in e for e in errs)


def test_suggested_min_stage_count_floor_values():
    assert suggested_min_stage_count(1) == 1       # degenerate small input still floors to 1
    assert suggested_min_stage_count(350) == 1      # 1 beat -> 1 stage
    assert suggested_min_stage_count(1750) == 1     # 5 beats -> exactly 1 stage's worth
    assert suggested_min_stage_count(3000) == 2     # default target_words -> 9 beats -> 2 stages
    assert suggested_min_stage_count(7000) == 4     # 20 beats -> 4 stages


def test_understaffed_chapter_rejected(monkeypatch):
    _stub_target_words(monkeypatch, 3000)  # floor == 2
    errs = validate_plot_chapters(_ok(1), character_names=_NAMES)
    assert any("仅 1 段" in e and "至少需要 2 段" in e for e in errs)


def test_chapter_meeting_floor_passes(monkeypatch):
    _stub_target_words(monkeypatch, 3000)  # floor == 2
    assert validate_plot_chapters(_ok(2), character_names=_NAMES) == []


def test_chapter_exceeding_floor_passes(monkeypatch):
    _stub_target_words(monkeypatch, 3000)  # floor == 2
    assert validate_plot_chapters(_ok(5), character_names=_NAMES) == []
