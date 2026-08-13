"""Plan runner: dispatch to world_pipeline for the 6 migrated kinds
(world/schema/character/plot_chapter/plot_all/timeline) and to skeleton_pipeline
for skeleton_stage. No JSON-driven plan remains — everything else passes
through ungated."""
import engine.setup_chat.plan_runner as pr
import engine.setup_chat.world_pipeline as wp
import pytest


@pytest.fixture(autouse=True)
def _reset_world_pipeline_active_target():
    wp._ACTIVE_TARGET = None
    yield
    wp._ACTIVE_TARGET = None


def test_gate_allows_non_pipeline_tools():
    assert pr.gate_tool_call("patch_chapter", {"chapter": 1, "ops": []}) is None


def test_gate_never_blocks_readonly_or_interaction():
    for name in ("read_setup_summary", "present_choices", "load_skill", "query_character_voice"):
        assert pr.gate_tool_call(name, {}) is None


def test_gate_dispatches_pipeline_tools_to_world_pipeline(monkeypatch):
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: True)
    assert pr.gate_tool_call("add_character", {"given_name": "甲"}) is None


def test_gate_dispatches_skeleton_pipeline_tools(monkeypatch):
    import engine.setup_chat.skeleton_pipeline as sp
    monkeypatch.setattr(sp, "_is_expanded", lambda ch, sn: False)
    sp._DIRECTION_SET.add(2)
    sp._LENS_CHOSEN[(2, 1)] = ["a"]
    sp._EXT_CHOSEN[(2, 1)] = []
    try:
        msg = pr.gate_tool_call("write_chapter_skeleton",
                                {"chapter": 2, "stages": [{"stage_num": 1, "beats": []}]})
        assert msg is None
    finally:
        sp._DIRECTION_SET.discard(2)
        sp._LENS_CHOSEN.pop((2, 1), None)
        sp._EXT_CHOSEN.pop((2, 1), None)


def test_gate_dispatch_blocks_via_world_pipeline_when_upstream_missing(monkeypatch):
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: False)
    msg = pr.gate_tool_call("add_character", {"given_name": "甲"})
    assert msg and "world" in msg


def test_gate_generate_one_chapter_bypasses_chain_for_existing_chapter(monkeypatch):
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: False)
    monkeypatch.setattr(pr, "_chapter_exists", lambda ch: ch == 2)
    assert pr.gate_tool_call("generate_one_chapter", {"chapter_index": 2}) is None
    assert pr.gate_tool_call("generate_one_chapter", {"chapter_index": 9}) is not None


def test_build_plan_activation_dispatches_to_world_pipeline_first(monkeypatch):
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: False)
    wp.gate(wp.resolve_chain("add_character", {"given_name": "甲"}))
    text = pr.build_plan_activation()
    assert text and "world" in text and "character" in text


def test_build_plan_activation_dispatches_to_skeleton_pipeline_second(monkeypatch):
    import engine.setup_chat.skeleton_pipeline as sp
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: True)
    monkeypatch.setattr("engine.setup_chat.plan_runner._chapter_timeline_done", lambda ch: True)
    monkeypatch.setattr(wp, "_ACTIVE_TARGET", None)
    chain = sp.resolve_chain("set_stage_lens", {"chapter": 2, "stage_num": 1, "angles": ["a"]})
    sp.gate(chain)
    try:
        text = pr.build_plan_activation()
        assert text and "本章整体方向" in text
    finally:
        sp._ACTIVE_TARGET = None
        sp._DIRECTION_SET.clear()
        sp._LENS_CHOSEN.clear()


def test_build_plan_activation_none_without_anything_active(monkeypatch):
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: True)
    monkeypatch.setattr("engine.setup_chat.plan_runner._chapter_timeline_done", lambda ch: True)
    monkeypatch.setattr("engine.setup_chat.construction_plan._plot_chapters", lambda: set())
    import engine.setup_chat.skeleton_pipeline as sp
    monkeypatch.setattr(sp, "_ACTIVE_CHAPTER", None)
    assert pr.build_plan_activation() is None


def test_build_plan_activation_falls_back_to_world_next_focus(monkeypatch):
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: False)
    text = pr.build_plan_activation()
    assert text and "接下来该做" in text and "set_world_background" in text


def test_build_plan_activation_falls_back_to_skeleton_next_focus_after_world_done(monkeypatch):
    import engine.setup_chat.skeleton_pipeline as sp
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: True)
    monkeypatch.setattr("engine.setup_chat.plan_runner._chapter_timeline_done", lambda ch: True)
    monkeypatch.setattr(sp, "_ACTIVE_CHAPTER", 2)
    sp._DIRECTION_SET.discard(2)
    try:
        text = pr.build_plan_activation()
        assert text and "set_chapter_direction" in text
    finally:
        sp._DIRECTION_SET.discard(2)


def test_pending_invalidation_note_clears_after_read():
    pr.record_invalidation([{"id": "t1", "kind": "timeline", "title": "重建ch2",
                             "params": {"chapter": 2}}])
    pr.record_invalidation([{"id": "k1", "kind": "skeleton_stage", "title": "重扩2-1",
                             "params": {"chapter": 2, "stage_num": 1}}])
    note = pr.pending_invalidation_note()
    assert "重建ch2" in note and "重扩2-1" in note
    # 展示即消费：第二次读取应为空，不再重复提醒同一批旧失效
    assert pr.pending_invalidation_note() == ""


def test_record_invalidation_dedupes_by_id():
    pr.record_invalidation([{"id": "t1", "kind": "timeline", "title": "a", "params": {}}])
    pr.record_invalidation([{"id": "t1", "kind": "timeline", "title": "a", "params": {}}])
    note = pr.pending_invalidation_note()
    assert note.count("失效：a。") == 1


def test_gate_blocks_world_dimension_tools_in_auto_mode_when_world_missing(monkeypatch):
    monkeypatch.setattr("engine.setup_chat.mode.is_auto_mode", lambda: True)
    monkeypatch.setattr(
        "engine.setup_chat.construction_plan.derive_task_status",
        lambda task: "pending" if task["kind"] == "world" else "done",
    )
    result = pr.gate_tool_call("set_world_background", {"background": "x"})
    assert result is not None
    assert "auto_build_setup" in result


def test_gate_allows_world_dimension_tools_in_manual_mode(monkeypatch):
    monkeypatch.setattr("engine.setup_chat.mode.is_auto_mode", lambda: False)
    monkeypatch.setattr(
        "engine.setup_chat.construction_plan.derive_task_status",
        lambda task: "pending",
    )
    result = pr.gate_tool_call("set_world_background", {"background": "x"})
    assert result is None


def test_gate_allows_world_dimension_tools_in_auto_mode_when_world_already_built(monkeypatch):
    """A deliberate full-world redo must still work in AUTO mode once world is complete."""
    monkeypatch.setattr("engine.setup_chat.mode.is_auto_mode", lambda: True)
    monkeypatch.setattr(
        "engine.setup_chat.construction_plan.derive_task_status",
        lambda task: "done",
    )
    result = pr.gate_tool_call("set_world_background", {"background": "x"})
    assert result is None


def test_gate_blocks_interactive_skeleton_tools_in_auto_mode_when_chapter_virgin(monkeypatch):
    monkeypatch.setattr("engine.setup_chat.mode.is_auto_mode", lambda: True)
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_pipeline.chapter_remaining_stage_nums", lambda ch: [1, 2],
    )
    result = pr.gate_tool_call("set_chapter_direction", {"chapter": 3, "direction": "x"})
    assert result is not None
    assert "auto_expand_skeleton" in result


def test_gate_allows_interactive_skeleton_tools_in_manual_mode(monkeypatch):
    monkeypatch.setattr("engine.setup_chat.mode.is_auto_mode", lambda: False)
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_pipeline.chapter_remaining_stage_nums", lambda ch: [1, 2],
    )
    result = pr.gate_tool_call("set_chapter_direction", {"chapter": 3, "direction": "x"})
    assert result is None


def test_gate_blocks_interactive_skeleton_tools_in_auto_mode_when_chapter_has_partial_progress(
    monkeypatch,
):
    """A chapter with some stages already expanded (e.g. switched into AUTO mid-chapter) must
    still be steered toward auto_expand_skeleton for a still-remaining direction/stage call --
    this used to fall through unchanged, letting the ReAct loop plow through the remaining
    stages one tool call at a time and risk exhausting the recursion limit on large chapters."""
    monkeypatch.setattr("engine.setup_chat.mode.is_auto_mode", lambda: True)
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_pipeline.chapter_remaining_stage_nums", lambda ch: [2],
    )
    result = pr.gate_tool_call("set_chapter_direction", {"chapter": 3, "direction": "x"})
    assert result is not None
    assert "auto_expand_skeleton" in result


def test_gate_allows_pure_revision_of_already_expanded_stage_in_auto_mode_with_other_progress(
    monkeypatch,
):
    """A revision call on a stage that's already expanded must pass through even when the
    chapter still has other remaining stages -- only first-time advances on still-remaining
    stages get redirected to auto_expand_skeleton, not legitimate edits."""
    monkeypatch.setattr("engine.setup_chat.mode.is_auto_mode", lambda: True)
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_pipeline.chapter_remaining_stage_nums", lambda ch: [2],
    )
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_pipeline._is_expanded", lambda ch, sn: sn == 1,
    )
    result = pr.gate_tool_call(
        "write_chapter_skeleton",
        {"chapter": 3, "stages": [{"stage_num": 1, "overview": "revise this"}]},
    )
    assert result is None


def test_gate_blocks_first_time_write_of_remaining_stage_in_auto_mode(monkeypatch):
    monkeypatch.setattr("engine.setup_chat.mode.is_auto_mode", lambda: True)
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_pipeline.chapter_remaining_stage_nums", lambda ch: [1, 2],
    )
    monkeypatch.setattr("engine.setup_chat.skeleton_pipeline._is_expanded", lambda ch, sn: False)
    result = pr.gate_tool_call(
        "write_chapter_skeleton",
        {"chapter": 3, "stages": [{"stage_num": 1, "overview": ""}]},
    )
    assert result is not None
    assert "auto_expand_skeleton" in result


def test_gate_allows_interactive_skeleton_tools_when_chapter_fully_expanded(monkeypatch):
    """Nothing left to expand at all -- AUTO mode has nothing to steer toward, falls through to
    the normal gate (which allows a revision-style set_chapter_direction call unconditionally)."""
    monkeypatch.setattr("engine.setup_chat.mode.is_auto_mode", lambda: True)
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_pipeline.chapter_remaining_stage_nums", lambda ch: [],
    )
    result = pr.gate_tool_call("set_chapter_direction", {"chapter": 3, "direction": "x"})
    assert result is None
