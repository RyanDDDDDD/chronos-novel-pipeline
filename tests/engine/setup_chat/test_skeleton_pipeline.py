import engine.setup_chat.skeleton_pipeline as sp
import pytest

from repo_test_helpers import seed_plot


@pytest.fixture(autouse=True)
def _reset_state():
    """All state here is process-global and ephemeral (see module docstring) —
    must not leak between tests."""
    sp._DIRECTION_SET.clear()
    sp._LENS_CHOSEN.clear()
    sp._EXT_CHOSEN.clear()
    sp._ACTIVE_TARGET = None
    sp._ACTIVE_CHAPTER = None
    sp._ACTIVE_REVIEWS.clear()
    yield
    sp._DIRECTION_SET.clear()
    sp._LENS_CHOSEN.clear()
    sp._EXT_CHOSEN.clear()
    sp._ACTIVE_TARGET = None
    sp._ACTIVE_CHAPTER = None
    sp._ACTIVE_REVIEWS.clear()


def test_resolve_chain_none_for_unrelated_tool():
    assert sp.resolve_chain("patch_chapter", {"chapter": 2}) is None
    assert sp.resolve_chain("present_choices", {}) is None


def test_direction_has_no_precondition():
    chain = sp.resolve_chain("set_chapter_direction", {"chapter": 2, "direction": "甲线"})
    assert chain is not None and not chain.blocked


def test_direction_blocked_when_timeline_missing(monkeypatch):
    monkeypatch.setattr(sp, "_missing_timeline_for", lambda ch: ["甲"])
    chain = sp.resolve_chain("set_chapter_direction", {"chapter": 2, "direction": "x"})
    assert chain.blocked and chain.missing_timeline_chars == ["甲"]
    assert chain.missing == []  # phase-order check is independent and still satisfied


def test_direction_unblocked_when_timeline_satisfied(monkeypatch):
    monkeypatch.setattr(sp, "_missing_timeline_for", lambda ch: [])
    chain = sp.resolve_chain("set_chapter_direction", {"chapter": 2, "direction": "x"})
    assert not chain.blocked


def test_lens_blocked_when_timeline_missing_even_with_direction_set(monkeypatch):
    monkeypatch.setattr(sp, "_missing_timeline_for", lambda ch: ["乙"])
    sp.set_chapter_direction(2, "甲线")
    chain = sp.resolve_chain("set_stage_lens", {"chapter": 2, "stage_num": 1, "angles": ["a"]})
    assert chain.blocked and chain.missing_timeline_chars == ["乙"]


def test_write_first_time_blocked_when_timeline_missing(monkeypatch):
    monkeypatch.setattr(sp, "_is_expanded", lambda ch, sn: False)
    monkeypatch.setattr(sp, "_missing_timeline_for", lambda ch: ["丙"])
    sp.set_chapter_direction(2, "甲线")
    sp.set_stage_lens(2, 1, ["a"])
    sp.set_stage_extensions(2, 1, [])
    chain = sp.resolve_chain(
        "write_chapter_skeleton",
        {"chapter": 2, "stages": [{"stage_num": 1, "beats": []}]},
    )
    assert chain.blocked and chain.missing_timeline_chars == ["丙"]


def test_write_revision_stays_unblocked_when_timeline_missing(monkeypatch):
    """The deliberate exclusion: revising an already-written stage must not be newly
    gated by a roster member's timeline being undone."""
    monkeypatch.setattr(sp, "_is_expanded", lambda ch, sn: True)
    monkeypatch.setattr(sp, "_missing_timeline_for", lambda ch: ["甲", "乙", "丙"])
    chain = sp.resolve_chain(
        "write_chapter_skeleton",
        {"chapter": 2, "stages": [{"stage_num": 1, "beats": []}]},
    )
    assert chain is not None and not chain.blocked


def test_active_chain_reflects_timeline_block_and_self_clears(monkeypatch):
    calls = {"missing": ["甲"]}
    monkeypatch.setattr(sp, "_missing_timeline_for", lambda ch: calls["missing"])
    chain = sp.resolve_chain("set_chapter_direction", {"chapter": 2, "direction": "x"})
    sp.gate(chain)
    assert sp.active_chain() is not None

    calls["missing"] = []  # timeline derived out-of-band
    assert sp.active_chain() is None
    assert sp._ACTIVE_TARGET is None


def test_lens_requires_direction():
    chain = sp.resolve_chain("set_stage_lens", {"chapter": 2, "stage_num": 1, "angles": ["a"]})
    assert chain.blocked and chain.missing == [sp.SkeletonPhase.DIRECTION]


def test_lens_ok_once_direction_set():
    sp.set_chapter_direction(2, "甲线")
    chain = sp.resolve_chain("set_stage_lens", {"chapter": 2, "stage_num": 1, "angles": ["a"]})
    assert not chain.blocked


def test_extensions_requires_direction_and_lens_in_order():
    chain = sp.resolve_chain("set_stage_extensions", {"chapter": 2, "stage_num": 1, "extensions": []})
    assert chain.missing == [sp.SkeletonPhase.DIRECTION, sp.SkeletonPhase.LENS]

    sp.set_chapter_direction(2, "甲线")
    chain = sp.resolve_chain("set_stage_extensions", {"chapter": 2, "stage_num": 1, "extensions": []})
    assert chain.missing == [sp.SkeletonPhase.LENS]

    sp.set_stage_lens(2, 1, ["a"])
    chain = sp.resolve_chain("set_stage_extensions", {"chapter": 2, "stage_num": 1, "extensions": []})
    assert not chain.blocked


def test_write_requires_all_three_for_first_time_stage(monkeypatch):
    monkeypatch.setattr(sp, "_is_expanded", lambda ch, sn: False)
    chain = sp.resolve_chain(
        "write_chapter_skeleton",
        {"chapter": 2, "stages": [{"stage_num": 1, "beats": []}]},
    )
    assert chain.missing == [sp.SkeletonPhase.DIRECTION, sp.SkeletonPhase.LENS, sp.SkeletonPhase.EXTENSIONS]

    sp.set_chapter_direction(2, "甲线")
    sp.set_stage_lens(2, 1, ["a"])
    sp.set_stage_extensions(2, 1, [])
    chain = sp.resolve_chain(
        "write_chapter_skeleton",
        {"chapter": 2, "stages": [{"stage_num": 1, "beats": []}]},
    )
    assert not chain.blocked


def test_write_bypasses_gate_entirely_for_revision(monkeypatch):
    """A stage that already has beats is treated as an edit — same trust level as
    patch_chapter, no phase requirement."""
    monkeypatch.setattr(sp, "_is_expanded", lambda ch, sn: True)
    chain = sp.resolve_chain(
        "write_chapter_skeleton",
        {"chapter": 2, "stages": [{"stage_num": 1, "beats": []}]},
    )
    assert chain is not None and not chain.blocked


def test_write_rejects_two_first_time_stages_in_one_call(monkeypatch):
    monkeypatch.setattr(sp, "_is_expanded", lambda ch, sn: False)
    sp.set_chapter_direction(2, "甲线")
    sp.set_stage_lens(2, 1, ["a"])
    sp.set_stage_extensions(2, 1, [])
    sp.set_stage_lens(2, 2, ["b"])
    sp.set_stage_extensions(2, 2, [])
    chain = sp.resolve_chain("write_chapter_skeleton", {"chapter": 2, "stages": [
        {"stage_num": 1, "beats": []}, {"stage_num": 2, "beats": []},
    ]})
    assert chain.blocked and chain.batch_violation is not None


def test_write_allows_one_first_time_plus_many_revision_stages(monkeypatch):
    expanded = {2}  # stage 2 already has beats, stage 1 doesn't
    monkeypatch.setattr(sp, "_is_expanded", lambda ch, sn: sn in expanded)
    sp.set_chapter_direction(2, "甲线")
    sp.set_stage_lens(2, 1, ["a"])
    sp.set_stage_extensions(2, 1, [])
    chain = sp.resolve_chain("write_chapter_skeleton", {"chapter": 2, "stages": [
        {"stage_num": 1, "beats": []}, {"stage_num": 2, "beats": []},
    ]})
    assert chain is not None and not chain.blocked


def test_gate_blocks_and_sets_active_target():
    chain = sp.resolve_chain("set_stage_lens", {"chapter": 2, "stage_num": 1, "angles": ["a"]})
    msg = sp.gate(chain)
    assert msg and "本章整体方向" in msg
    assert sp._ACTIVE_TARGET == (2, 1, sp.SkeletonPhase.LENS)


def test_gate_allows_and_clears_active_target_when_unblocked():
    sp.set_chapter_direction(2, "甲线")
    chain = sp.resolve_chain("set_stage_lens", {"chapter": 2, "stage_num": 1, "angles": ["a"]})
    assert sp.gate(chain) is None
    assert sp._ACTIVE_TARGET is None


def test_gate_batch_violation_does_not_touch_active_target(monkeypatch):
    monkeypatch.setattr(sp, "_is_expanded", lambda ch, sn: False)
    sp.set_chapter_direction(2, "甲线")
    sp.set_stage_lens(2, 1, ["a"]); sp.set_stage_extensions(2, 1, [])
    sp.set_stage_lens(2, 2, ["b"]); sp.set_stage_extensions(2, 2, [])
    chain = sp.resolve_chain("write_chapter_skeleton", {"chapter": 2, "stages": [
        {"stage_num": 1, "beats": []}, {"stage_num": 2, "beats": []},
    ]})
    msg = sp.gate(chain)
    assert msg is not None
    assert sp._ACTIVE_TARGET is None


def test_clear_stage_markers_removes_lens_and_extensions():
    sp.set_stage_lens(2, 1, ["a"])
    sp.set_stage_extensions(2, 1, [])
    sp.clear_stage_markers(2, 1)
    assert (2, 1) not in sp._LENS_CHOSEN
    assert (2, 1) not in sp._EXT_CHOSEN


def test_active_chain_none_when_nothing_blocked():
    assert sp.active_chain() is None


def test_active_chain_recomputes_live_and_self_clears():
    chain = sp.resolve_chain("set_stage_lens", {"chapter": 2, "stage_num": 1, "angles": ["a"]})
    sp.gate(chain)
    assert sp.active_chain() is not None

    sp.set_chapter_direction(2, "甲线")  # satisfied out-of-band
    assert sp.active_chain() is None
    assert sp._ACTIVE_TARGET is None


def test_render_activation_includes_block_message_and_skill_body(monkeypatch):
    monkeypatch.setattr(sp, "_load_skill_body", lambda name: f"<{name} 正文>")
    chain = sp.resolve_chain("set_stage_lens", {"chapter": 2, "stage_num": 1, "angles": ["a"]})
    text = sp.render_activation(chain)
    assert "本章整体方向" in text
    assert "<skeleton-expansion 正文>" in text


def test_render_block_message_names_missing_timeline_chars(monkeypatch):
    monkeypatch.setattr(sp, "_missing_timeline_for", lambda ch: ["甲", "乙"])
    chain = sp.resolve_chain("set_chapter_direction", {"chapter": 2, "direction": "x"})
    msg = sp.render_block_message(chain)
    assert "甲、乙" in msg
    assert "角色档案" in msg
    assert "等待角色档案自动推演完成" in msg


def test_render_block_message_omits_timeline_line_when_satisfied(monkeypatch):
    monkeypatch.setattr(sp, "_missing_timeline_for", lambda ch: [])
    chain = sp.resolve_chain("set_stage_lens", {"chapter": 2, "stage_num": 1, "angles": ["a"]})
    msg = sp.render_block_message(chain)
    assert "等待角色档案自动推演完成" not in msg
    assert "本章整体方向" in msg  # existing DIRECTION-missing message still there


def test_render_activation_does_not_inject_dedicated_skill_for_missing_archive(monkeypatch):
    """Missing character archives block on the engine's automatic background derivation
    (timeline_auto.py) -- there is no dedicated skill for the agent to load, unlike
    skeleton-expansion which always gets injected."""
    def fake_load(name):
        return f"<{name} 正文>"

    monkeypatch.setattr(sp, "_load_skill_body", fake_load)
    monkeypatch.setattr(sp, "_missing_timeline_for", lambda ch: ["甲"])
    chain = sp.resolve_chain("set_chapter_direction", {"chapter": 2, "direction": "x"})
    text = sp.render_activation(chain)
    assert "timeline-derivation" not in text
    assert "角色档案" in text
    assert "<skeleton-expansion 正文>" in text


def test_render_activation_omits_timeline_derivation_skill_when_satisfied(monkeypatch):
    def fake_load(name):
        return f"<{name} 正文>"

    monkeypatch.setattr(sp, "_load_skill_body", fake_load)
    monkeypatch.setattr(sp, "_missing_timeline_for", lambda ch: [])
    chain = sp.resolve_chain("set_stage_lens", {"chapter": 2, "stage_num": 1, "angles": ["a"]})
    text = sp.render_activation(chain)
    assert "timeline-derivation" not in text
    assert "<skeleton-expansion 正文>" in text


def test_next_focus_none_when_no_active_chapter(monkeypatch):
    monkeypatch.setattr(sp, "_ACTIVE_CHAPTER", None)
    assert sp.next_focus() is None


def test_next_focus_returns_direction_when_not_set(monkeypatch):
    monkeypatch.setattr(sp, "_ACTIVE_CHAPTER", 2)
    sp._DIRECTION_SET.discard(2)
    try:
        chain = sp.next_focus()
        assert chain is not None and chain.target == sp.SkeletonPhase.DIRECTION
    finally:
        sp._DIRECTION_SET.discard(2)


def test_next_focus_returns_lens_for_first_unexpanded_stage(monkeypatch):
    monkeypatch.setattr(sp, "_ACTIVE_CHAPTER", 2)
    monkeypatch.setattr(sp, "_chapter_stage_nums", lambda ch: [1, 2])
    monkeypatch.setattr(sp, "_is_expanded", lambda ch, sn: False)
    monkeypatch.setattr(sp, "_missing_timeline_for", lambda ch: [])
    sp._DIRECTION_SET.add(2)
    sp._LENS_CHOSEN.pop((2, 1), None)
    try:
        chain = sp.next_focus()
        assert chain is not None
        assert chain.stage_num == 1 and chain.target == sp.SkeletonPhase.LENS
    finally:
        sp._DIRECTION_SET.discard(2)


def test_next_focus_skips_already_expanded_stages(monkeypatch):
    monkeypatch.setattr(sp, "_ACTIVE_CHAPTER", 2)
    monkeypatch.setattr(sp, "_chapter_stage_nums", lambda ch: [1, 2])
    monkeypatch.setattr(sp, "_is_expanded", lambda ch, sn: sn == 1)
    monkeypatch.setattr(sp, "_missing_timeline_for", lambda ch: [])
    sp._DIRECTION_SET.add(2)
    sp._LENS_CHOSEN.pop((2, 2), None)
    try:
        chain = sp.next_focus()
        assert chain is not None
        assert chain.stage_num == 2 and chain.target == sp.SkeletonPhase.LENS
    finally:
        sp._DIRECTION_SET.discard(2)


def test_next_focus_none_when_all_stages_expanded(monkeypatch):
    monkeypatch.setattr(sp, "_ACTIVE_CHAPTER", 2)
    monkeypatch.setattr(sp, "_chapter_stage_nums", lambda ch: [1, 2])
    monkeypatch.setattr(sp, "_is_expanded", lambda ch, sn: True)
    sp._DIRECTION_SET.add(2)
    try:
        assert sp.next_focus() is None
    finally:
        sp._DIRECTION_SET.discard(2)


def test_render_activation_unblocked_chain_says_next_step_not_blocked(monkeypatch):
    monkeypatch.setattr(sp, "_ACTIVE_CHAPTER", 2)
    sp._DIRECTION_SET.discard(2)
    try:
        chain = sp.next_focus()
        text = sp.render_activation(chain)
        assert "现在还不能做" not in text
        assert "set_chapter_direction" in text
    finally:
        sp._DIRECTION_SET.discard(2)


class _FakePlotRepo:
    def __init__(self, chapters):
        self._chapters = chapters

    def list_raw(self):
        return self._chapters


_ROSTER_CHAPTER = [{"chapter": 3, "stages": [
    {"stage_num": 1, "description": "甲乙对峙"},
    {"stage_num": 2, "description": "乙丙同行"},
]}]


def test_chapter_roster_unions_and_dedups_across_stages(monkeypatch):
    monkeypatch.setattr("repositories.get_plot_repo", lambda: _FakePlotRepo(_ROSTER_CHAPTER))
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: [n for n in ("甲", "乙", "丙") if n in text],
    )
    assert sp._chapter_roster(3) == ["甲", "乙", "丙"]


def test_chapter_roster_empty_for_unknown_chapter(monkeypatch):
    monkeypatch.setattr("repositories.get_plot_repo", lambda: _FakePlotRepo(_ROSTER_CHAPTER))
    assert sp._chapter_roster(99) == []


def test_missing_timeline_for_empty_roster_is_satisfied(monkeypatch):
    monkeypatch.setattr("repositories.get_plot_repo", lambda: _FakePlotRepo([]))
    assert sp._missing_timeline_for(1) == []


def test_missing_timeline_for_returns_only_undone_names(monkeypatch):
    monkeypatch.setattr("repositories.get_plot_repo", lambda: _FakePlotRepo(_ROSTER_CHAPTER))
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: [n for n in ("甲", "乙", "丙") if n in text],
    )
    from engine.setup_chat import construction_plan as cp

    done = {"甲", "乙"}  # 丙 not derived yet

    def fake_status(task):
        name = (task.get("params") or {}).get("name")
        return "done" if name in done else "pending"

    monkeypatch.setattr(cp, "derive_task_status", fake_status)
    assert sp._missing_timeline_for(3) == ["丙"]


def test_missing_timeline_for_all_done_returns_empty(monkeypatch):
    monkeypatch.setattr("repositories.get_plot_repo", lambda: _FakePlotRepo(_ROSTER_CHAPTER))
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: [n for n in ("甲", "乙", "丙") if n in text],
    )
    from engine.setup_chat import construction_plan as cp

    monkeypatch.setattr(cp, "derive_task_status", lambda task: "done")
    assert sp._missing_timeline_for(3) == []


def test_resolve_chain_marks_chapter_active_on_direction(monkeypatch):
    sp._ACTIVE_CHAPTER = None
    sp._DIRECTION_SET.clear()
    sp.resolve_chain("set_chapter_direction", {"chapter": 5, "direction": "x"})
    assert sp._ACTIVE_CHAPTER == 5


def test_resolve_chain_marks_chapter_active_even_when_blocked(monkeypatch):
    sp._ACTIVE_CHAPTER = None
    sp._DIRECTION_SET.clear()
    sp._LENS_CHOSEN.clear()
    #set_stage_lens with no prior direction → blocked chain, but chapter should still be marked
    chain = sp.resolve_chain("set_stage_lens", {"chapter": 6, "stage_num": 1, "angles": ["a"]})
    assert chain is not None and chain.blocked
    assert sp._ACTIVE_CHAPTER == 6


def test_resolve_chain_switches_active_chapter(monkeypatch):
    sp._ACTIVE_CHAPTER = None
    sp._DIRECTION_SET.clear()
    sp.resolve_chain("set_chapter_direction", {"chapter": 1, "direction": "x"})
    assert sp._ACTIVE_CHAPTER == 1
    sp.resolve_chain("set_chapter_direction", {"chapter": 2, "direction": "y"})
    assert sp._ACTIVE_CHAPTER == 2


def test_clear_chapter_active_only_clears_matching_chapter():
    sp._ACTIVE_CHAPTER = 3
    sp.clear_chapter_active(4)
    assert sp._ACTIVE_CHAPTER == 3
    sp.clear_chapter_active(3)
    assert sp._ACTIVE_CHAPTER is None


def test_active_seed_injection_none_when_no_active_chapter(monkeypatch, tmp_path):
    sp._ACTIVE_CHAPTER = None
    assert sp.active_seed_injection() is None


def test_active_seed_injection_renders_seed_when_active(monkeypatch, tmp_path):
    del monkeypatch, tmp_path
    seed_plot([{"chapter": 7, "title": "七", "stages": [
        {"stage_num": 1, "description": "开场描述XYZ", "characters": {"甲": {}}},
    ]}])

    sp._ACTIVE_CHAPTER = 7
    out = sp.active_seed_injection()
    assert out is not None
    assert "开场描述XYZ" in out
    assert "第7章" in out or "第 7 章" in out


def test_active_seed_injection_none_when_chapter_has_no_plot(monkeypatch, tmp_path):
    del monkeypatch, tmp_path
    seed_plot([])

    sp._ACTIVE_CHAPTER = 99
    assert sp.active_seed_injection() is None


def test_mark_review_active_scoped_per_novel():
    sp.mark_review_active("novel-A", 3)
    assert sp.is_review_active("novel-A", 3) is True
    assert sp.is_review_active("novel-B", 3) is False  # different novel, same chapter number


def test_clear_review_active_is_a_noop_when_not_active():
    sp.clear_review_active("novel-A", 3)  # must not raise
    assert sp.is_review_active("novel-A", 3) is False


def test_any_review_active_reflects_the_novels_own_set():
    assert sp.any_review_active("novel-A") is False
    sp.mark_review_active("novel-A", 3)
    assert sp.any_review_active("novel-A") is True
    sp.mark_review_active("novel-A", 5)
    sp.clear_review_active("novel-A", 3)
    assert sp.any_review_active("novel-A") is True  # chapter 5 still active
    sp.clear_review_active("novel-A", 5)
    assert sp.any_review_active("novel-A") is False


def test_gate_no_longer_checks_active_reviews():
    """Removed in this round: set_chapter_direction/set_stage_lens/set_stage_extensions never
    write stages[].beats, so they can't race a background review job's save_all() -- there's
    nothing for gate() to guard against here anymore."""
    sp.mark_review_active("n", 2)
    chain = sp.resolve_chain("set_chapter_direction", {"chapter": 2, "direction": "x"})
    assert sp.gate(chain) is None  # unblocked, same as if nothing were marked active


def test_chapter_fully_unexpanded_false_when_no_plot():
    assert sp.chapter_fully_unexpanded(99) is False


def test_chapter_fully_unexpanded_true_when_no_stage_has_beats():
    seed_plot([{"chapter": 3, "stages": [
        {"stage_num": 1, "description": "x"}, {"stage_num": 2, "description": "y"},
    ]}])
    assert sp.chapter_fully_unexpanded(3) is True


def test_chapter_fully_unexpanded_false_when_any_stage_has_beats():
    seed_plot([{"chapter": 3, "stages": [
        {"stage_num": 1, "description": "x", "beats": [{"text": "已扩"}]},
        {"stage_num": 2, "description": "y"},
    ]}])
    assert sp.chapter_fully_unexpanded(3) is False


def test_chapter_remaining_stage_nums_empty_when_no_plot():
    assert sp.chapter_remaining_stage_nums(99) == []


def test_chapter_remaining_stage_nums_all_stages_when_virgin():
    seed_plot([{"chapter": 3, "stages": [
        {"stage_num": 1, "description": "x"}, {"stage_num": 2, "description": "y"},
    ]}])
    assert sp.chapter_remaining_stage_nums(3) == [1, 2]


def test_chapter_remaining_stage_nums_excludes_already_expanded_stages():
    seed_plot([{"chapter": 3, "stages": [
        {"stage_num": 1, "description": "x", "beats": [{"text": "已扩"}]},
        {"stage_num": 2, "description": "y"},
    ]}])
    assert sp.chapter_remaining_stage_nums(3) == [2]


def test_chapter_remaining_stage_nums_empty_when_fully_expanded():
    seed_plot([{"chapter": 3, "stages": [
        {"stage_num": 1, "description": "x", "beats": [{"text": "已扩"}]},
        {"stage_num": 2, "description": "y", "beats": [{"text": "已扩"}]},
    ]}])
    assert sp.chapter_remaining_stage_nums(3) == []


def test_is_direction_set_false_by_default():
    assert sp.is_direction_set(3) is False


def test_is_direction_set_true_after_set_chapter_direction():
    sp.set_chapter_direction(3, "x")
    assert sp.is_direction_set(3) is True


def test_active_chapter_reflects_global(monkeypatch):
    monkeypatch.setattr(sp, "_ACTIVE_CHAPTER", None)
    assert sp.active_chapter() is None
    monkeypatch.setattr(sp, "_ACTIVE_CHAPTER", 7)
    assert sp.active_chapter() == 7
