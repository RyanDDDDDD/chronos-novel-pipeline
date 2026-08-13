"""scripts/ai_word_report.py: AI 特征词/句式密度诊断——静态整章密度计算。"""
from scripts.ai_word_report import compute_chapter_density


def test_compute_chapter_density_counts_words_and_flags_over_threshold(monkeypatch):
    import engine.execution.style_guard as style_guard_mod

    monkeypatch.setattr(style_guard_mod, "WORD_THRESHOLDS", {"仿佛": 0, "似乎": 5})
    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: [])

    content = "他仿佛想说什么。" * 3  # "仿佛" 出现 3 次，阈值 0 -> 超标；"似乎" 0 次不入 word_hits

    stats = compute_chapter_density(content)

    assert stats["length"] == len(content)
    assert stats["word_hits"] == {"仿佛": 3}
    assert stats["word_total"] == 3
    assert stats["pattern_total"] == 0
    assert stats["grand_total"] == 3
    assert stats["over_threshold"] == ["仿佛"]


def test_compute_chapter_density_counts_pattern_hits(monkeypatch):
    import engine.execution.style_guard as style_guard_mod

    patterns = style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`")
    monkeypatch.setattr(style_guard_mod, "WORD_THRESHOLDS", {})
    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: patterns)

    content = "他不是喜欢她，而是习惯了。"

    stats = compute_chapter_density(content)

    assert stats["word_total"] == 0
    assert stats["pattern_total"] == 1
    assert stats["grand_total"] == 1


def test_compute_chapter_density_empty_content_has_zero_density(monkeypatch):
    import engine.execution.style_guard as style_guard_mod

    monkeypatch.setattr(style_guard_mod, "WORD_THRESHOLDS", {"仿佛": 0})
    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: [])

    stats = compute_chapter_density("")

    assert stats["length"] == 0
    assert stats["density"] == 0.0
    assert stats["over_threshold"] == []
