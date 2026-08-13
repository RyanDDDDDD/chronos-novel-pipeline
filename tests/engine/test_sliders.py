"""Tests for engine.archive.sliders — per-character rubric lookup/rendering/guardrails."""

RUBRICS = {
    "羁绊": {"0": "陌生", "1": "心动", "2": "交付"},
    "依恋": {"0": "毫无", "1": "萌芽", "2": "沉溺"},
}


def test_axes_of_derives_from_data():
    from engine.archive.sliders import axes_of
    assert axes_of(RUBRICS) == ["羁绊", "依恋"]
    assert axes_of({}) == []


def test_character_rubrics_reads_own_lore_entry(monkeypatch):
    from engine.archive import sliders as sl

    class _FakeRepo:
        def list_raw(self):
            return [
                {
                    "name": "角色甲",
                    "sliders": {
                        "投入": {
                            "level": 1, "text": "x",
                            "levels": {"0": "a", "1": "b", "2": "c"},
                        },
                        "旧轴未迁移": {"level": 0, "text": "y"},  # 无 levels
                    },
                },
                {"name": "角色乙", "sliders": {}},
            ]

    monkeypatch.setattr("repositories.get_lore_repo", lambda: _FakeRepo())
    r = sl.character_rubrics("角色甲")
    assert r == {"投入": {"0": "a", "1": "b", "2": "c"}}  # 未迁移轴不出现在 rubrics 里
    assert sl.character_rubrics("角色乙") == {}
    assert sl.character_rubrics("不存在的角色") == {}


def test_render_number_to_text():
    from engine.archive.sliders import render_slider
    assert render_slider(RUBRICS, "羁绊", 1) == "心动"
    assert render_slider(RUBRICS, "依恋", 2) == "沉溺"


def test_render_clamps_out_of_range():
    from engine.archive.sliders import render_slider
    assert render_slider(RUBRICS, "羁绊", 9) == "交付"
    assert render_slider(RUBRICS, "羁绊", -3) == "陌生"


def test_render_dynamic_scale():
    from engine.archive.sliders import render_slider
    wide = {"信任": {"0": "陌生", "10": "交付"}}
    assert render_slider(wide, "信任", 10) == "交付"
    assert render_slider(wide, "信任", 99) == "交付"
    assert render_slider(wide, "信任", 0) == "陌生"


def test_render_missing_falls_back():
    from engine.archive.sliders import render_slider
    assert render_slider({}, "羁绊", 1) == "羁绊:1"


def test_parse_label_exact_and_fallbacks():
    from engine.archive.sliders import parse_slider_label
    assert parse_slider_label(RUBRICS, "羁绊", "心动") == 1
    assert parse_slider_label(RUBRICS, "依恋", "沉溺") == 2
    assert parse_slider_label(RUBRICS, "羁绊", "心动（欲拒还迎）") == 1
    assert parse_slider_label(RUBRICS, "羁绊", "2") == 2
    assert parse_slider_label(RUBRICS, "羁绊", "莫名其妙") is None


def test_guardrail_allows_forward_and_small_drop():
    from engine.archive.sliders import check_slider_regression
    assert check_slider_regression(RUBRICS, {"羁绊": 0, "依恋": 0}, {"羁绊": 2, "依恋": 1}) == []
    assert check_slider_regression(RUBRICS, {"羁绊": 2}, {"羁绊": 0}, reverse_threshold=2) == []


def test_guardrail_flags_large_drop():
    from engine.archive.sliders import check_slider_regression
    a = check_slider_regression(RUBRICS, {"羁绊": 5}, {"羁绊": 1})
    assert len(a) == 1 and "羁绊" in a[0]
    b = check_slider_regression(RUBRICS, {"依恋": 4}, {"依恋": 0})
    assert len(b) == 1 and "依恋" in b[0]


FULL_RUBRICS = {
    "羁绊": {
        "0": "陌生。礼貌而疏离，视对方为外人。",
        "1": "心动。开始在意对方的目光，欲拒还迎。",
        "2": "交付。毫无保留地依附，情感彻底交出。",
    }
}


def test_axis_tags_strips_to_leading_phrase():
    from engine.archive.sliders import axis_tags
    tags = axis_tags(FULL_RUBRICS, "羁绊")
    assert "心动" in tags and "交付" in tags
    assert all("。" not in t for t in tags)


def test_parse_matches_leading_tag_full_sentence():
    from engine.archive.sliders import parse_slider_label
    assert parse_slider_label(FULL_RUBRICS, "羁绊", "交付。毫无保留地依附") == 2


def test_render_axis_choices_lists_closed_tag_set():
    from engine.archive.sliders import render_axis_choices
    txt = render_axis_choices(FULL_RUBRICS, "羁绊")
    assert "心动" in txt and "交付" in txt


def test_valid_levels_returns_int_key_set():
    from engine.archive.sliders import valid_levels
    rubrics = {"侵蚀度": {"0": "清醒", "1": "动摇", "2": "沦陷"}}
    assert valid_levels(rubrics, "侵蚀度") == {0, 1, 2}


def test_valid_levels_empty_when_axis_missing():
    from engine.archive.sliders import valid_levels
    rubrics = {"侵蚀度": {"0": "清醒"}}
    assert valid_levels(rubrics, "不存在轴") == set()
