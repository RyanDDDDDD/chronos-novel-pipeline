import engine.setup_chat.world_pipeline as wp
import pytest


@pytest.fixture(autouse=True)
def _reset_active_target():
    """_ACTIVE_TARGET/_ACTIVE_TIMELINE_TARGET are process-global markers (not persisted) —
    must not leak between tests."""
    wp._ACTIVE_TARGET = None
    wp._ACTIVE_TIMELINE_TARGET = None
    yield
    wp._ACTIVE_TARGET = None
    wp._ACTIVE_TIMELINE_TARGET = None


def test_stage_of_maps_every_pipeline_tool():
    assert wp.stage_of("set_world_background").kind == "world"
    assert wp.stage_of("add_world_faction").kind == "world"
    assert wp.stage_of("add_character").kind == "character"
    assert wp.stage_of("generate_one_chapter").kind == "plot_chapter"
    assert wp.stage_of("write_character_archive").kind == "timeline"


def test_stage_of_none_for_unrelated_tool():
    assert wp.stage_of("write_chapter_skeleton") is None
    assert wp.stage_of("patch_chapter") is None


def test_resolve_chain_none_when_not_a_pipeline_tool():
    assert wp.resolve_chain("write_chapter_skeleton", {}) is None


def test_resolve_chain_no_missing_when_all_upstream_done(monkeypatch):
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: True)
    chain = wp.resolve_chain("add_character", {"given_name": "甲"})
    assert chain.target.kind == "character"
    assert chain.missing_stages == []
    assert not chain.blocked
    assert [s.kind for s in chain.upcoming] == ["plot_chapter", "timeline"]


def test_resolve_chain_reports_missing_earlier_stages(monkeypatch):
    done: set[str] = set()
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: stage.kind in done)
    chain = wp.resolve_chain("add_character", {"given_name": "甲"})
    assert [s.kind for s in chain.missing_stages] == ["world"]
    assert chain.blocked


def test_resolve_chain_timeline_folds_in_sequential_chapter_rule(monkeypatch):
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: True)
    monkeypatch.setattr(
        "engine.setup_chat.plan_runner._missing_prior_timeline_chapters",
        lambda ch: [1, 2] if ch == 3 else [],
    )
    chain = wp.resolve_chain("write_character_archive", {"chapter": 3, "name": "甲"})
    assert chain.missing_stages == []
    assert chain.missing_timeline_chapters == [1, 2]
    assert chain.blocked


def test_resolve_chain_chapter_arg_ignored_for_non_timeline_stage(monkeypatch):
    """generate_one_chapter's chapter_index must not leak into the Chain's chapter
    field for the plot_chapter stage — that stage's completion doesn't depend on
    which chapter, and a stale per-chapter identity would break _ACTIVE_TARGET
    clearing (see Task 2)."""
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: True)
    chain = wp.resolve_chain("generate_one_chapter", {"chapter_index": 7})
    assert chain.chapter is None


def test_gate_allows_when_not_blocked(monkeypatch):
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: True)
    chain = wp.resolve_chain("add_character", {"given_name": "甲"})
    assert wp.gate(chain) is None
    assert wp._ACTIVE_TARGET is None


def test_gate_blocks_and_sets_active_target(monkeypatch):
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: False)
    chain = wp.resolve_chain("add_character", {"given_name": "甲"})
    msg = wp.gate(chain)
    assert msg and "world" in msg and "character" in msg
    assert wp._ACTIVE_TARGET == ("character", None)


def test_gate_clears_active_target_once_its_own_target_passes(monkeypatch):
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: False)
    blocked = wp.resolve_chain("add_character", {"given_name": "甲"})
    wp.gate(blocked)
    assert wp._ACTIVE_TARGET == ("character", None)

    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: True)
    passing = wp.resolve_chain("add_character", {"given_name": "乙"})
    assert wp.gate(passing) is None
    assert wp._ACTIVE_TARGET is None


def test_active_chain_none_when_nothing_blocked():
    assert wp.active_chain() is None


def test_active_chain_recomputes_live_and_self_clears(monkeypatch):
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: False)
    blocked = wp.resolve_chain("add_character", {"given_name": "甲"})
    wp.gate(blocked)

    chain = wp.active_chain()
    assert chain is not None and chain.target.kind == "character"
    assert [s.kind for s in chain.missing_stages] == ["world"]

    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: True)
    assert wp.active_chain() is None
    assert wp._ACTIVE_TARGET is None


def test_render_activation_includes_block_message_and_skill_bodies(monkeypatch):
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: False)
    monkeypatch.setattr(wp, "_load_skill_body", lambda name: f"<{name} 正文>")
    chain = wp.resolve_chain("add_character", {"given_name": "甲"})
    text = wp.render_activation(chain)
    assert "character" in text and "world" in text
    assert "<world-interview 正文>" in text
    assert "<character-interview 正文>" in text


def test_resolve_chain_marks_timeline_target_on_write():
    wp.resolve_chain("write_character_archive", {"chapter": 3, "name": "甲", "stages": {}})
    assert wp._ACTIVE_TIMELINE_TARGET == (3, "甲")


def test_resolve_chain_marks_timeline_target_even_when_blocked(monkeypatch):
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: False)
    chain = wp.resolve_chain("write_character_archive", {"chapter": 3, "name": "甲", "stages": {}})
    assert chain is not None and chain.blocked
    assert wp._ACTIVE_TIMELINE_TARGET == (3, "甲")


def test_resolve_chain_does_not_mark_timeline_target_for_other_tools():
    wp.resolve_chain("add_character", {"given_name": "甲"})
    assert wp._ACTIVE_TIMELINE_TARGET is None


def test_resolve_chain_ignores_missing_name_for_timeline_marking():
    wp.resolve_chain("write_character_archive", {"chapter": 3, "stages": {}})  # no "name"
    assert wp._ACTIVE_TIMELINE_TARGET is None


def test_clear_timeline_active_only_clears_matching_target():
    wp._ACTIVE_TIMELINE_TARGET = (3, "甲")
    wp.clear_timeline_active(3, "乙")
    assert wp._ACTIVE_TIMELINE_TARGET == (3, "甲")
    wp.clear_timeline_active(4, "甲")
    assert wp._ACTIVE_TIMELINE_TARGET == (3, "甲")
    wp.clear_timeline_active(3, "甲")
    assert wp._ACTIVE_TIMELINE_TARGET is None


def test_active_timeline_seed_injection_none_when_no_active_target():
    assert wp.active_timeline_seed_injection() is None


def test_active_timeline_seed_injection_renders_seed_when_active(monkeypatch):
    monkeypatch.setattr(
        "engine.setup_chat.timeline_seed.build_timeline_seed",
        lambda name, chapter: {"name": name, "chapter": chapter, "mode": "cold_start",
                                "prior": {}, "stages": [{"stage_num": 1, "location": "屋内",
                                "description": "开场描述XYZ", "known_clothing": None}],
                                "rubric": {}, "lore": {}, "physique_current": {}},
    )
    wp._ACTIVE_TIMELINE_TARGET = (5, "甲")
    out = wp.active_timeline_seed_injection()
    assert out is not None
    assert "开场描述XYZ" in out
    assert "第5章" in out or "第 5 章" in out
    assert "甲" in out


def test_active_timeline_seed_injection_none_when_no_stages(monkeypatch):
    monkeypatch.setattr(
        "engine.setup_chat.timeline_seed.build_timeline_seed",
        lambda name, chapter: {"name": name, "chapter": chapter, "mode": "cold_start",
                                "prior": {}, "stages": [], "rubric": {}, "lore": {},
                                "physique_current": {}},
    )
    wp._ACTIVE_TIMELINE_TARGET = (5, "甲")
    assert wp.active_timeline_seed_injection() is None


def test_render_block_message_for_timeline_points_to_archive_page():
    from engine.setup_chat.world_pipeline import Chain, WORLD_STAGES, render_block_message

    timeline_stage = next(s for s in WORLD_STAGES if s.kind == "timeline")
    chain = Chain(target=timeline_stage, chapter=2, missing_stages=[], upcoming=[])
    msg = render_block_message(chain)
    assert "自动构建" in msg
    assert "角色档案页面" in msg


def test_timeline_stage_has_no_skill_body_injected(monkeypatch):
    from engine.setup_chat import world_pipeline as wp

    timeline_stage = next(s for s in wp.WORLD_STAGES if s.kind == "timeline")
    chain = wp.Chain(target=timeline_stage, chapter=1, missing_stages=[], upcoming=[])
    rendered = wp.render_activation(chain)
    assert "逐角色编排" not in rendered


def test_next_focus_returns_world_when_nothing_built(monkeypatch):
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: False)
    chain = wp.next_focus()
    assert chain is not None and chain.target.kind == "world" and not chain.blocked


def test_next_focus_returns_first_incomplete_stage(monkeypatch):
    done = {"world"}
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: stage.kind in done)
    chain = wp.next_focus()
    assert chain is not None and chain.target.kind == "character" and not chain.blocked


def test_next_focus_picks_earliest_unfinished_timeline_chapter(monkeypatch):
    monkeypatch.setattr(wp, "_stage_done",
                        lambda stage, chapter: stage.kind != "timeline")
    monkeypatch.setattr("engine.setup_chat.construction_plan._plot_chapters",
                        lambda: {1, 2, 3})
    # next_focus() does `from engine.setup_chat.plan_runner import _chapter_timeline_done`
    # as a local import at call time, so patching the source module attribute
    # (not `wp._chapter_timeline_done`, which doesn't exist) takes effect.
    monkeypatch.setattr("engine.setup_chat.plan_runner._chapter_timeline_done", lambda ch: ch != 2)
    chain = wp.next_focus()
    assert chain is not None and chain.target.kind == "timeline" and chain.chapter == 2
    assert not chain.blocked


def test_next_focus_none_when_everything_done(monkeypatch):
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: True)
    monkeypatch.setattr("engine.setup_chat.construction_plan._plot_chapters", lambda: {1})
    monkeypatch.setattr("engine.setup_chat.plan_runner._chapter_timeline_done", lambda ch: True)
    assert wp.next_focus() is None


def test_render_activation_unblocked_chain_says_next_step_not_blocked(monkeypatch):
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: False)
    chain = wp.next_focus()
    text = wp.render_activation(chain)
    assert "现在还不能做" not in text
    assert "set_world_background" in text


def test_active_timeline_target_reflects_global(monkeypatch):
    monkeypatch.setattr(wp, "_ACTIVE_TIMELINE_TARGET", None)
    assert wp.active_timeline_target() is None
    monkeypatch.setattr(wp, "_ACTIVE_TIMELINE_TARGET", (3, "角色A"))
    assert wp.active_timeline_target() == (3, "角色A")
