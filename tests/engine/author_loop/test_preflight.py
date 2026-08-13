"""The author starts testing the aggregation behavior of the front gate collect_author_loop_blockers.

Only the orchestration logic of "collecting blocking reasons according to four types of products, not fail-fast" is verified; each product's own verification details
(validate_roster/load_prebuilt_skeleton/render_world_summary) have respective tests here
Pile them and focus on the act of preflight aggregating the missing items into a list."""
from __future__ import annotations

import pytest

from engine.author_loop import preflight
from engine.author_loop.build import SkeletonNotBuiltError


@pytest.fixture(autouse=True)
def _reset_review_active():
    import engine.setup_chat.skeleton_pipeline as sp
    sp._ACTIVE_REVIEWS.clear()
    yield
    sp._ACTIVE_REVIEWS.clear()


class _Repo:
    def __init__(self, value):
        self._value = value

    def get(self, *a, **k):
        return self._value

    def list_raw(self):
        return self._value


def _patch(
    monkeypatch,
    *,
    world_summary: str = "有世界设定文本",
    roster: list[dict] | None = None,
    roster_errors: list[str] | None = None,
    skeleton_error: str | None = None,
) -> None:
    """
Pile four product sources, all legal by default."""
    if roster is None:
        roster = [{"name": "甲"}]
    monkeypatch.setattr("repositories.get_world_repo", lambda: _Repo({"logline": "x"}))
    monkeypatch.setattr(
        "engine.setup.world.summary.render_world_summary", lambda wb: world_summary
    )
    monkeypatch.setattr("repositories.get_lore_repo", lambda: _Repo(roster))
    monkeypatch.setattr(
        "engine.setup.cast.cast_validator.validate_roster",
        lambda r: list(roster_errors or []),
    )

    def _skeleton(chapter: int):
        if skeleton_error is not None:
            raise SkeletonNotBuiltError(skeleton_error)
        return [{"intent": "x"}]

    monkeypatch.setattr("engine.author_loop.build.load_prebuilt_skeleton", _skeleton)


def test_all_present_no_blockers(monkeypatch):
    _patch(monkeypatch)
    assert preflight.collect_author_loop_blockers(1) == []


def test_world_missing_blocks(monkeypatch):
    _patch(monkeypatch, world_summary="")
    blockers = preflight.collect_author_loop_blockers(1)
    assert any("世界观" in b for b in blockers)


def test_empty_roster_blocks_without_calling_validate(monkeypatch):
    #The roster is empty: "Role not built" is reported, and validate_roster is no longer adjusted (otherwise the empty library will generate a lot of missing field noise)
    called = {"validate": False}

    def _boom(_r):
        called["validate"] = True
        return ["不该被调用"]

    _patch(monkeypatch, roster=[])
    monkeypatch.setattr("engine.setup.cast.cast_validator.validate_roster", _boom)
    blockers = preflight.collect_author_loop_blockers(1)
    assert any("角色" in b for b in blockers)
    assert called["validate"] is False


def test_invalid_roster_surfaces_field_errors(monkeypatch):
    _patch(monkeypatch, roster_errors=["[甲] physique 缺基础子字段「胸部」"])
    blockers = preflight.collect_author_loop_blockers(1)
    assert any("physique 缺基础子字段" in b for b in blockers)


def test_roster_race_mismatch_still_blocks_preflight(monkeypatch):
    """Regression: interactive-path race-membership relaxation must not leak into preflight."""
    from engine.setup.cast import cast_validator as cv
    from engine.setup.cast.stance_schema import physique_slots

    char = {
        "name": "甲", "given_name": "甲", "role": "甲", "gender": "female",
        "clothing_dna": {"color_palette": ["黑"], "materials_preference": ["丝"],
                         "signature_outfit": "测试招牌常服", "accessories": []},
        "causal_anchors": {"执念": "x"}, "sliders": {"投入": 0},
        "physique": {k: "x" for k in physique_slots("female")},
        "race": "龙族",
        "personality": "尚待观察",
        "identity_background": "出身平平",
        "性癖": "尚待观察",
        "敏感带": "尚待观察",
        "暴露程度": "尚待观察",
    }
    monkeypatch.setattr("repositories.get_lore_repo", lambda: _Repo([char]))
    monkeypatch.setattr(cv, "_load_world_race_names", lambda: ["精灵族", "人类"], raising=False)

    blockers = preflight._roster_blockers()
    assert any("不在世界设定种族" in b and "龙族" in b for b in blockers)


def test_skeleton_missing_blocks_for_started_chapter(monkeypatch):
    _patch(monkeypatch, skeleton_error="第 3 章 stage 1 尚未扩写骨架")
    blockers = preflight.collect_author_loop_blockers(3)
    assert any("尚未扩写骨架" in b for b in blockers)


def test_collects_all_not_fail_fast(monkeypatch):
    #The world view, characters, and skeleton are all missing at the same time: collect all three categories at once, don’t stop at the first one
    _patch(
        monkeypatch,
        world_summary="",
        roster_errors=["[甲] causal_anchors 须为非空对象"],
        skeleton_error="第 1 章无 plot/stages",
    )
    blockers = preflight.collect_author_loop_blockers(1)
    assert any("世界观" in b for b in blockers)
    assert any("causal_anchors" in b for b in blockers)
    assert any("plot/stages" in b for b in blockers)


def test_chapter_review_active_blocks_without_checking_skeleton(monkeypatch):
    """While a background review/fix job owns this chapter's stages, author_loop must
    not even attempt to read them -- reports the review blocker and stops, without calling
    load_prebuilt_skeleton at all."""
    import engine.setup_chat.skeleton_pipeline as sp

    _patch(monkeypatch)
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")
    sp.mark_review_active("n", 3)

    called = {"skeleton": False}

    def _boom(chapter):
        called["skeleton"] = True
        return [{"intent": "x"}]

    monkeypatch.setattr("engine.author_loop.build.load_prebuilt_skeleton", _boom)
    try:
        blockers = preflight.collect_author_loop_blockers(3)
    finally:
        sp.clear_review_active("n", 3)

    assert any("审查" in b for b in blockers)
    assert called["skeleton"] is False


def test_chapter_review_active_does_not_block_other_chapters(monkeypatch):
    import engine.setup_chat.skeleton_pipeline as sp

    _patch(monkeypatch)
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")
    sp.mark_review_active("n", 3)
    try:
        blockers = preflight.collect_author_loop_blockers(1)
    finally:
        sp.clear_review_active("n", 3)

    assert blockers == []
