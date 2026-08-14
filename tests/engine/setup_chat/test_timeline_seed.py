from engine.setup_chat import timeline_seed as ts
from repo_test_helpers import seed_lore, seed_plot


def _setup(monkeypatch, tmp_path, lore, plot):
    del tmp_path
    seed_lore(lore)
    seed_plot(plot)
    #_chapter_roster/_relevant_stages now scan `description` via entity_index.scan_characters
    #instead of reading a `characters` field -- deterministic stub, no real lore/cache needed.
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: [n for n in ("甲", "乙") if n in text],
    )


_LORE = [{"name": "甲", "given_name": "甲", "role": "同质堕落型",
          "causal_anchors": {}, "sliders": {"侵蚀度": {
              "level": 0, "text": "清醒",
              "levels": {"0": "清醒。理智在。", "1": "动摇。"},
          }}}]
_PLOT = [
    {"chapter": 0, "title": "prior", "core_xp": [], "stages": []},
    {"chapter": 1, "title": "一", "core_xp": [], "stages": [
        {"stage_num": 1, "title": "s", "location": "屋内", "description": "甲登场"}]},
]
_SCHEMA = {}


def test_cold_start_when_no_prior(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _LORE, _PLOT)
    seed = ts.build_timeline_seed("甲", 1)
    assert seed["mode"] == "cold_start"
    assert [s["stage_num"] for s in seed["stages"]] == [1]
    assert seed["rubric"]["侵蚀度"] == [(0, "清醒。理智在。"), (1, "动摇。")]


def test_rolling_uses_prior_delta(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _LORE, _PLOT)
    #Bury a prior delta in ch0/stage1 (simulation pre-order has been archived)
    from context import character_timeline
    character_timeline.append_stage("甲", 0, 1, {"self_ref": {"_default": ["人家"]}})
    seed = ts.build_timeline_seed("甲", 1)
    assert seed["mode"] == "rolling"
    assert seed["prior"].get("self_ref") == {"_default": ["人家"]}


def test_absent_character_has_no_stages(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _LORE, _PLOT)
    seed = ts.build_timeline_seed("乙", 1)  #B is not in plot
    assert seed["stages"] == []


def test_seed_does_not_include_archetype_menu(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _LORE, _PLOT)
    seed = ts.build_timeline_seed("甲", 1)
    assert "archetypes" not in seed


def test_seed_includes_physique_current(monkeypatch, tmp_path):
    lore = [{"name": "甲", "given_name": "甲", "role": "同质堕落型", "causal_anchors": {},
             "sliders": {"侵蚀度": 0}, "physique": {"面容": "冷峻", "胸部": "结实"}}]
    _setup(monkeypatch, tmp_path, lore, _PLOT)
    seed = ts.build_timeline_seed("甲", 1)
    assert seed["physique_current"] == {"面容": "冷峻", "胸部": "结实"}  #The Chinese key is still brought out


def test_render_timeline_seed_includes_clothing_dna(monkeypatch, tmp_path):
    lore = [{"name": "甲", "given_name": "甲", "role": "同质堕落型", "causal_anchors": {},
             "sliders": {"侵蚀度": {"level": 1, "text": "已有轻微裂痕"}},
             "clothing_dna": {
                 "color_palette": ["白"],
                 "materials_preference": ["棉"],
                 "signature_outfit": "及膝白裙",
                 "accessories": ["银链"],
             }}]
    _setup(monkeypatch, tmp_path, lore, _PLOT)
    seed = ts.build_timeline_seed("甲", 1)
    out = ts.render_timeline_seed(seed)
    assert "招牌常服=及膝白裙" in out
    assert "配饰=银链" in out


def test_render_timeline_seed_cold_start(monkeypatch, tmp_path):
    lore = [{"name": "甲", "given_name": "甲", "role": "同质堕落型", "causal_anchors": {},
             "sliders": {"侵蚀度": {"level": 1, "text": "已有轻微裂痕"}},
             "identity_background": "没落贵族之女", "hobbies": ["刺绣"]}]
    _setup(monkeypatch, tmp_path, lore, _PLOT)
    seed = ts.build_timeline_seed("甲", 1)
    out = ts.render_timeline_seed(seed)
    assert "首次出场(cold_start)" in out
    assert "登场初始滑块" in out and "侵蚀度：档位1·已有轻微裂痕" in out
    assert "身份背景：没落贵族之女" in out
    assert "爱好：刺绣" in out
    assert "{" not in out


def test_render_timeline_seed_rolling(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _LORE, _PLOT)
    from context import character_timeline
    character_timeline.append_stage("甲", 0, 1, {"self_ref": {"_default": ["人家"]}})
    seed = ts.build_timeline_seed("甲", 1)
    out = ts.render_timeline_seed(seed)
    assert "滚动(rolling)" in out
    assert "前序自称" in out
    assert "人家" in out
