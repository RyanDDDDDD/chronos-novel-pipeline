import pytest
from engine.setup_chat.chapter_review import (
    StageReview,
    TransitionReview,
    _review_llm,
    chapter_skeleton_complete,
    render_chapter_review_report,
    run_chapter_stage_review,
    run_chapter_transition_review,
    run_stage_local_review,
    stage_beats_text,
)

from repo_test_helpers import seed_plot


@pytest.mark.asyncio
async def test_review_llm_binds_review_node_params(monkeypatch):
    """_review_llm used to call get_cloud_llm() directly with no per-node override --
    style/coherence hooks had no way to configure enable_thinking/model_ref
    the way image_recognition/text_recognition/chat_identity already could. Confirms it now
    routes through bind_node_llm with the "review" node id and this novel's import_llm_params."""
    class _FakeMsg:
        content = "ok"

    class _FakeLLM:
        async def ainvoke(self, _messages):
            return _FakeMsg()

    calls: list[tuple[str, dict]] = []

    def _fake_bind_node_llm(llm, node, params):
        calls.append((node, params))
        return llm

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.bind_node_llm", _fake_bind_node_llm,
    )
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {"review": {"enable_thinking": False}}},
    )

    text, tin, tout = await _review_llm("sys", "user")
    assert text == "ok"
    assert calls == [("review", {"review": {"enable_thinking": False}})]


def test_stage_beats_text_joins_beat_texts():
    stage = {"beats": [{"text": "甲乙对峙。"}, {"text": "丙推门而入。"}]}
    assert stage_beats_text(stage) == "甲乙对峙。\n\n丙推门而入。"


def test_stage_beats_text_empty_when_no_beats():
    assert stage_beats_text({}) == ""
    assert stage_beats_text({"beats": "not-a-list"}) == ""


def test_chapter_skeleton_complete_true_when_all_stages_have_beats():
    stages = [
        {"stage_num": 1, "beats": [{"text": "甲乙对峙。"}]},
        {"stage_num": 2, "beats": [{"text": "丙推门而入。"}]},
    ]
    assert chapter_skeleton_complete(stages) is True


def test_chapter_skeleton_complete_false_when_any_stage_empty():
    stages = [
        {"stage_num": 1, "beats": [{"text": "甲乙对峙。"}]},
        {"stage_num": 2},
    ]
    assert chapter_skeleton_complete(stages) is False


def test_chapter_skeleton_complete_false_for_empty_list():
    assert chapter_skeleton_complete([]) is False


def test_stage_hook_names_is_style_only():
    import engine.setup_chat.chapter_review as cr
    assert cr.STAGE_HOOK_NAMES == ("style",)


def test_active_hooks_excludes_disabled(monkeypatch):
    import engine.setup_chat.chapter_review as cr

    class _FakeHook:
        def __init__(self, name):
            self.name = name

    monkeypatch.setattr(cr, "REVIEW_HOOKS", [_FakeHook("style"), _FakeHook("other_stage")])
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"detail_skills": [], "target_words": 3000, "disabled_buildtime_review_hooks": ["other_stage"]},
    )
    active = cr._active_hooks(("style", "other_stage"))
    assert [h.name for h in active] == ["style"]


def test_active_hooks_returns_all_when_none_disabled(monkeypatch):
    import engine.setup_chat.chapter_review as cr

    class _FakeHook:
        def __init__(self, name):
            self.name = name

    monkeypatch.setattr(cr, "REVIEW_HOOKS", [_FakeHook("style"), _FakeHook("other_stage")])
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"detail_skills": [], "target_words": 3000, "disabled_buildtime_review_hooks": []},
    )
    active = cr._active_hooks(("style", "other_stage"))
    assert [h.name for h in active] == ["style", "other_stage"]


@pytest.mark.asyncio
async def test_run_chapter_stage_review_respects_disabled_hooks(monkeypatch):
    import engine.author_loop.self_review as sr
    import engine.setup_chat.chapter_review as cr

    captured_hook_names = []

    async def fake_run_self_review(ctx, call_llm, cfg, hooks):
        captured_hook_names.append([h.name for h in hooks])
        return sr.SelfReviewVerdict("accept", 9.0, [("style", 9)], "")

    monkeypatch.setattr(cr, "run_self_review", fake_run_self_review)
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"detail_skills": [], "target_words": 3000, "disabled_buildtime_review_hooks": ["other_stage"]},
    )

    stages = [{"stage_num": 1, "beats": [{"text": "甲乙对峙。"}]}]
    await run_chapter_stage_review(stages)
    assert captured_hook_names == [["style"]]


@pytest.mark.asyncio
async def test_run_chapter_stage_review_passes_beats_through(monkeypatch):
    import engine.author_loop.self_review as sr
    import engine.setup_chat.chapter_review as cr

    captured_beats = []

    async def fake_run_self_review(ctx, call_llm, cfg, hooks):
        captured_beats.append(ctx.beats)
        return sr.SelfReviewVerdict("accept", 9.0, [("style", 9)], "")

    monkeypatch.setattr(cr, "run_self_review", fake_run_self_review)

    stages = [
        {"stage_num": 1, "beats": [{"text": "甲乙对峙。"}, {"text": "丙推门而入。"}]},
    ]
    await run_chapter_stage_review(stages)
    assert captured_beats == [[{"text": "甲乙对峙。"}, {"text": "丙推门而入。"}]]


@pytest.mark.asyncio
async def test_run_stage_local_review_passes_beats_through(monkeypatch):
    import engine.author_loop.self_review as sr
    import engine.setup_chat.chapter_review as cr

    captured_beats = []

    async def fake_run_self_review(ctx, call_llm, cfg, hooks):
        captured_beats.append(ctx.beats)
        return sr.SelfReviewVerdict("accept", 8.0, [("x", 8)], "")

    monkeypatch.setattr(cr, "run_self_review", fake_run_self_review)

    stages = [{"stage_num": 1, "beats": [{"text": "段一。"}]}]
    await run_stage_local_review(stages, 1)
    assert captured_beats == [[{"text": "段一。"}]]


@pytest.mark.asyncio
async def test_run_chapter_transition_review_empty_for_single_stage():
    stages = [{"stage_num": 1, "beats": [{"text": "甲乙对峙。"}]}]
    assert await run_chapter_transition_review(stages) == []


@pytest.mark.asyncio
async def test_run_chapter_transition_review_covers_all_adjacent_pairs(monkeypatch):
    import engine.author_loop.self_review as sr
    import engine.setup_chat.chapter_review as cr

    captured: list[tuple[str, str]] = []

    async def fake_run_self_review(ctx, call_llm, cfg, hooks):
        captured.append((ctx.prev_beat_text, ctx.refined))
        return sr.SelfReviewVerdict("accept", 8.0, [("coherence", 8)], "")

    monkeypatch.setattr(cr, "run_self_review", fake_run_self_review)

    stages = [
        {"stage_num": 1, "beats": [{"text": "甲乙对峙。"}]},
        {"stage_num": 2, "beats": [{"text": "丙推门而入。"}]},
        {"stage_num": 3, "beats": [{"text": "三人对话。"}]},
    ]
    reviews = await run_chapter_transition_review(stages)

    assert [(r.from_stage, r.to_stage) for r in reviews] == [(1, 2), (2, 3)]
    assert captured == [
        ("甲乙对峙。", "丙推门而入。"),
        ("丙推门而入。", "三人对话。"),
    ]
    assert all(r.verdict.action == "accept" for r in reviews)


@pytest.mark.asyncio
async def test_run_chapter_transition_review_no_hooks_loaded_returns_empty(monkeypatch):
    import engine.setup_chat.chapter_review as cr

    monkeypatch.setattr(cr, "REVIEW_HOOKS", [])
    stages = [
        {"stage_num": 1, "beats": [{"text": "甲乙对峙。"}]},
        {"stage_num": 2, "beats": [{"text": "丙推门而入。"}]},
    ]
    assert await run_chapter_transition_review(stages) == []


def test_render_transition_report_empty_when_no_reviews():
    assert render_chapter_review_report([], []) == ""


def test_render_transition_report_mixes_accept_and_rewrite(monkeypatch):
    import engine.author_loop.self_review as sr

    transitions = [
        TransitionReview(1, 2, sr.SelfReviewVerdict("accept", 8.0, [("coherence", 8)], "")),
        TransitionReview(2, 3, sr.SelfReviewVerdict("rewrite", 4.0, [("coherence", 4)], "体位跳变，无过渡")),
    ]
    stages = [
        StageReview(1, sr.SelfReviewVerdict("rewrite", 5.0, [("style", 5)], "段尾升华句")),
    ]
    out = render_chapter_review_report(transitions, stages)
    assert "stage1→stage2：过渡通过（8.0/10）。" in out
    assert "stage2→stage3：过渡建议修改（4.0/10）——体位跳变，无过渡" in out
    assert "stage1：文风建议修改（5.0/10）——段尾升华句" in out


@pytest.mark.asyncio
async def test_run_chapter_stage_review_covers_every_stage_including_first(monkeypatch):
    import engine.author_loop.self_review as sr
    import engine.setup_chat.chapter_review as cr

    captured: list[tuple[str, str | None]] = []

    async def fake_run_self_review(ctx, call_llm, cfg, hooks):
        captured.append((ctx.refined, ctx.prev_beat_text))
        return sr.SelfReviewVerdict("accept", 9.0, [("style", 9)], "")

    monkeypatch.setattr(cr, "run_self_review", fake_run_self_review)

    stages = [
        {"stage_num": 1, "beats": [{"text": "甲乙对峙。"}]},
        {"stage_num": 2, "beats": [{"text": "丙推门而入。"}]},
    ]
    reviews = await run_chapter_stage_review(stages)

    assert [r.stage_num for r in reviews] == [1, 2]
    assert captured == [("甲乙对峙。", None), ("丙推门而入。", None)]
    assert all(r.verdict.action == "accept" for r in reviews)


@pytest.mark.asyncio
async def test_run_chapter_stage_review_no_hooks_loaded_returns_empty(monkeypatch):
    import engine.setup_chat.chapter_review as cr

    monkeypatch.setattr(cr, "REVIEW_HOOKS", [])
    stages = [{"stage_num": 1, "beats": [{"text": "甲乙对峙。"}]}]
    assert await run_chapter_stage_review(stages) == []


@pytest.mark.asyncio
async def test_run_chapter_stage_review_empty_for_no_stages():
    assert await run_chapter_stage_review([]) == []


@pytest.mark.asyncio
async def test_run_stage_local_review_empty_when_target_stage_has_no_beats():
    stages = [
        {"stage_num": 1, "beats": [{"text": "甲乙对峙。"}]},
        {"stage_num": 2},  # 未分拍
    ]
    assert await run_stage_local_review(stages, 2) == ([], [])


@pytest.mark.asyncio
async def test_run_stage_local_review_checks_target_and_both_neighbors(monkeypatch):
    import engine.author_loop.self_review as sr
    import engine.setup_chat.chapter_review as cr

    captured: list[tuple[str | None, str]] = []

    async def fake_run_self_review(ctx, call_llm, cfg, hooks):
        captured.append((ctx.prev_beat_text, ctx.refined))
        return sr.SelfReviewVerdict("accept", 8.0, [("x", 8)], "")
    monkeypatch.setattr(cr, "run_self_review", fake_run_self_review)

    stages = [
        {"stage_num": 1, "beats": [{"text": "段一。"}]},
        {"stage_num": 2, "beats": [{"text": "段二。"}]},
        {"stage_num": 3, "beats": [{"text": "段三。"}]},
    ]
    transitions, stage_reviews = await run_stage_local_review(stages, 2)

    assert [(t.from_stage, t.to_stage) for t in transitions] == [(1, 2), (2, 3)]
    assert [s.stage_num for s in stage_reviews] == [2]
    # 只查目标段自己(无 prev) + 两条过渡(各带 prev/refined)
    assert (None, "段二。") in captured
    assert ("段一。", "段二。") in captured
    assert ("段二。", "段三。") in captured


@pytest.mark.asyncio
async def test_run_stage_local_review_skips_neighbor_without_beats(monkeypatch):
    import engine.author_loop.self_review as sr
    import engine.setup_chat.chapter_review as cr

    async def fake_run_self_review(ctx, call_llm, cfg, hooks):
        return sr.SelfReviewVerdict("accept", 8.0, [("x", 8)], "")
    monkeypatch.setattr(cr, "run_self_review", fake_run_self_review)

    stages = [
        {"stage_num": 1},  # 未分拍,不该被查
        {"stage_num": 2, "beats": [{"text": "段二。"}]},
        {"stage_num": 3, "beats": [{"text": "段三。"}]},
    ]
    transitions, stage_reviews = await run_stage_local_review(stages, 2)

    assert [(t.from_stage, t.to_stage) for t in transitions] == [(2, 3)]
    assert [s.stage_num for s in stage_reviews] == [2]


@pytest.mark.asyncio
async def test_run_stage_local_review_first_stage_has_no_prev_transition(monkeypatch):
    import engine.author_loop.self_review as sr
    import engine.setup_chat.chapter_review as cr

    async def fake_run_self_review(ctx, call_llm, cfg, hooks):
        return sr.SelfReviewVerdict("accept", 8.0, [("x", 8)], "")
    monkeypatch.setattr(cr, "run_self_review", fake_run_self_review)

    stages = [
        {"stage_num": 1, "beats": [{"text": "段一。"}]},
        {"stage_num": 2, "beats": [{"text": "段二。"}]},
    ]
    transitions, stage_reviews = await run_stage_local_review(stages, 1)

    assert [(t.from_stage, t.to_stage) for t in transitions] == [(1, 2)]
    assert [s.stage_num for s in stage_reviews] == [1]


@pytest.mark.asyncio
async def test_run_stage_local_review_no_hooks_loaded_returns_empty(monkeypatch):
    import engine.setup_chat.chapter_review as cr

    monkeypatch.setattr(cr, "REVIEW_HOOKS", [])
    stages = [
        {"stage_num": 1, "beats": [{"text": "段一。"}]},
        {"stage_num": 2, "beats": [{"text": "段二。"}]},
    ]
    assert await run_stage_local_review(stages, 1) == ([], [])


@pytest.mark.asyncio
async def test_maybe_schedule_marks_reviewed_and_skips_when_is_reviewed(monkeypatch, tmp_path):
    from engine.setup_chat.chapter_review import (
        chapter_skeleton_reviewed,
        maybe_schedule_skeleton_chapter_review,
    )

    seed_plot([{
        "chapter": 1,
        "stages": [{"stage_num": 1, "description": "d", "beats": [{"text": "拍"}]}],
    }])

    scheduled = []
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_background_review.schedule_chapter_review_fix",
        lambda chapter: scheduled.append(chapter),
    )
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")

    stages = [{"stage_num": 1, "beats": [{"text": "拍"}]}]
    await maybe_schedule_skeleton_chapter_review(1, stages, is_reviewed=True)
    assert scheduled == []
    assert chapter_skeleton_reviewed(1) is True


@pytest.mark.asyncio
async def test_maybe_schedule_skips_when_chapter_already_reviewed(monkeypatch, tmp_path):
    from engine.setup_chat.chapter_review import maybe_schedule_skeleton_chapter_review

    seed_plot([{
        "chapter": 1, "skeleton_reviewed": True,
        "stages": [{"stage_num": 1, "description": "d", "beats": [{"text": "拍"}]}],
    }])

    scheduled = []
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_background_review.schedule_chapter_review_fix",
        lambda chapter: scheduled.append(chapter),
    )
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")

    stages = [{"stage_num": 1, "beats": [{"text": "改后拍"}]}]
    await maybe_schedule_skeleton_chapter_review(1, stages, is_reviewed=False)
    assert scheduled == []


@pytest.mark.asyncio
async def test_maybe_schedule_broadcasts_started_when_novel_idle(monkeypatch, tmp_path):
    """Regression: scheduling must emit skeleton_review_started before mark_review_active,
    otherwise _run_chapter_review_fix sees any_review_active=True and the frontend toast
    never appears (patch_text_fragment / write_chapter_skeleton paths)."""
    from engine.setup_chat.chapter_review import maybe_schedule_skeleton_chapter_review

    seed_plot([{
        "chapter": 1,
        "stages": [{"stage_num": 1, "description": "d", "beats": [{"text": "拍"}]}],
    }])

    broadcasts: list[dict] = []

    class _FakeHub:
        async def broadcast(self, ev):
            broadcasts.append(ev)

    monkeypatch.setattr("api.routes._hub_instance", lambda: _FakeHub())
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_background_review.schedule_chapter_review_fix",
        lambda chapter: None,
    )
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "novel-15")

    stages = [{"stage_num": 1, "beats": [{"text": "拍"}]}]
    await maybe_schedule_skeleton_chapter_review(1, stages, is_reviewed=False)

    assert broadcasts == [{"type": "skeleton_review_started", "novel_id": "novel-15"}]


@pytest.mark.asyncio
async def test_maybe_schedule_invalidates_reviewed_when_is_reviewed_false(monkeypatch, tmp_path):
    from engine.setup_chat.chapter_review import (
        chapter_skeleton_reviewed,
        maybe_schedule_skeleton_chapter_review,
    )

    seed_plot([{
        "chapter": 1,
        "skeleton_reviewed": True,
        "stages": [{"stage_num": 1, "description": "d", "beats": [{"text": "拍"}]}],
    }])

    scheduled: list[int] = []
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_background_review.schedule_chapter_review_fix",
        lambda chapter: scheduled.append(chapter),
    )
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")

    stages = [{"stage_num": 1, "beats": [{"text": "拍"}]}]
    await maybe_schedule_skeleton_chapter_review(
        1, stages, is_reviewed=False, invalidate_reviewed=True,
    )

    assert scheduled == [1]
    assert chapter_skeleton_reviewed(1) is False
