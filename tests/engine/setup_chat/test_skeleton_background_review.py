import asyncio
from unittest.mock import AsyncMock

import pytest
from api.services.setup_chat_review_feedback import REVIEW_FEEDBACK, render_review_feedback
from engine.author_loop.self_review import SelfReviewVerdict
from engine.setup_chat.chapter_review import StageReview, TransitionReview


class _FakeHub:
    """Mirrors the real MessageHub.report_review_done / _maybe_flush_review_feedback so
    module tests can assert the end-to-end batched notice."""

    def __init__(self, *, busy: bool = False):
        self.broadcasts: list[dict] = []
        self.notices: list[tuple[str, str]] = []
        self._busy = busy

    async def broadcast(self, event):
        self.broadcasts.append(event)

    def is_setup_chat_busy(self, novel_id=None) -> bool:
        return self._busy

    async def trigger_system_notice_turn(self, novel_id, summary):
        self.notices.append((novel_id, summary))

    async def report_review_done(self, novel_id, pending_key, entries):
        for bkey, entry in entries:
            REVIEW_FEEDBACK.record(novel_id, bkey, entry)
        REVIEW_FEEDBACK.clear_pending(novel_id, pending_key)
        REVIEW_FEEDBACK.reset_attempt(novel_id, pending_key)
        await self._maybe_flush(novel_id)

    async def _maybe_flush(self, novel_id):
        if REVIEW_FEEDBACK.has_pending(novel_id):
            return
        entries = REVIEW_FEEDBACK.snapshot(novel_id)
        if not entries or self._busy:
            return
        REVIEW_FEEDBACK.clear_buffer(novel_id)
        await self.trigger_system_notice_turn(novel_id, render_review_feedback(entries))


@pytest.fixture(autouse=True)
def _clean_review_feedback():
    from engine.setup_chat import skeleton_pipeline as sp
    sp._ACTIVE_REVIEWS.clear()
    REVIEW_FEEDBACK.clear_all("n")
    yield
    sp._ACTIVE_REVIEWS.clear()
    REVIEW_FEEDBACK.clear_all("n")


def _accept(score=9.0):
    return SelfReviewVerdict("accept", score, [("x", int(score))], "")


def _rewrite(feedback, score=4.0):
    return SelfReviewVerdict("rewrite", score, [("x", int(score))], feedback)


# ── _collect_failing_feedback ────────────────────────────────────────────────


def test_collect_failing_feedback_empty_when_everything_accepted():
    from engine.setup_chat.skeleton_background_review import _collect_failing_feedback

    transitions = [TransitionReview(1, 2, _accept())]
    stages = [StageReview(1, _accept()), StageReview(2, _accept())]
    assert _collect_failing_feedback(transitions, stages) == {}


def test_collect_failing_feedback_attributes_transition_problems_to_to_stage():
    from engine.setup_chat.skeleton_background_review import _collect_failing_feedback

    transitions = [TransitionReview(1, 2, _rewrite("体位跳变，无过渡"))]
    out = _collect_failing_feedback(transitions, [])
    assert out == {2: ["体位跳变，无过渡"]}


def test_collect_failing_feedback_includes_stage_review_problems():
    from engine.setup_chat.skeleton_background_review import _collect_failing_feedback

    stages = [StageReview(2, _rewrite("段尾升华句"))]
    out = _collect_failing_feedback([], stages)
    assert out == {2: ["段尾升华句"]}


def test_collect_failing_feedback_merges_both_kinds_for_the_same_stage():
    from engine.setup_chat.skeleton_background_review import _collect_failing_feedback

    transitions = [TransitionReview(1, 2, _rewrite("过渡生硬"))]
    stages = [StageReview(2, _rewrite("段尾升华句"))]
    out = _collect_failing_feedback(transitions, stages)
    assert out == {2: ["过渡生硬", "段尾升华句"]}


# ── schedule_chapter_review_fix ──────────────────────────────────────────────


def test_schedule_chapter_review_fix_registers_a_dedup_once_event(monkeypatch):
    from engine.setup_chat import skeleton_background_review as sbr

    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")
    captured = {}

    def fake_schedule_once(name, delay_s, coro, *, dedup=False, on_timeout=None):
        captured["name"] = name
        captured["delay_s"] = delay_s
        captured["dedup"] = dedup
        captured["on_timeout"] = on_timeout

    import api.services.scheduler as sched
    monkeypatch.setattr(sched.SCHEDULER, "schedule_once", fake_schedule_once)

    sbr.schedule_chapter_review_fix(3)

    assert captured["name"] == "skeleton-chapter-fix:n:3"
    assert captured["delay_s"] == 0.0
    assert captured["dedup"] is True
    assert captured["on_timeout"] is not None
    assert REVIEW_FEEDBACK.has_pending("n") is True


# ── _run_chapter_review_fix ──────────────────────────────────────────────────


class _FakeRepo:
    def __init__(self, chapters):
        self.chapters = chapters
        self.saved: list = []

    def list_raw(self):
        return self.chapters

    def get_outline_with_version(self, chapter):
        ch = next((c for c in self.chapters if c.get("chapter") == chapter), None)
        if ch is None:
            return None
        return ch, 1

    def save_chapter_if_version_matches(self, chapter, data, expected_version):
        for i, c in enumerate(self.chapters):
            if c.get("chapter") == chapter:
                self.chapters[i] = data
                self.saved.append([dict(c) for c in self.chapters])
                return expected_version + 1
        return None

    def save_all(self, chapters):
        self.saved.append([dict(c) for c in chapters])
        self.chapters = chapters


def _plot(chapter=3):
    return [{"chapter": chapter, "stages": [
        {"stage_num": 1, "beats": [{"text": "第一段。"}]},
        {"stage_num": 2, "beats": [{"text": "第二段。"}]},
    ]}]


@pytest.mark.asyncio
async def test_run_chapter_review_all_pass_records_clean(monkeypatch):
    from engine.setup_chat import skeleton_background_review as sbr

    class _Repo:
        def list_raw(self):
            return [{"chapter": 3, "stages": [{"stage_num": 1, "beats": []}]}]

    monkeypatch.setattr("repositories.get_plot_repo", _Repo)

    async def _no_transitions(stages):
        return []

    async def _no_stage_issues(stages):
        return []

    monkeypatch.setattr(sbr, "run_chapter_transition_review", _no_transitions)
    monkeypatch.setattr(sbr, "run_chapter_stage_review", _no_stage_issues)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("skeleton", 3))
    await sbr._run_chapter_review_fix(3, "n")

    assert len(hub.notices) == 1
    assert "【通过，无需调整】第3章骨架" in hub.notices[0][1]


@pytest.mark.asyncio
async def test_run_chapter_review_deleted_chapter_records_resolved_error(monkeypatch):
    from engine.setup_chat import skeleton_background_review as sbr

    class _Repo:
        def list_raw(self):
            return []

    monkeypatch.setattr("repositories.get_plot_repo", _Repo)
    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("skeleton", 3))
    await sbr._run_chapter_review_fix(3, "n")

    assert len(hub.notices) == 1
    assert "━━ 第3章骨架 ━━" in hub.notices[0][1]
    assert "已被删除" in hub.notices[0][1] or "审查中止" in hub.notices[0][1]


@pytest.mark.asyncio
async def test_run_chapter_review_fix_pins_novel_id_around_repo_access(monkeypatch):
    """Regression guard: this coroutine runs on SCHEDULER's own background loop task,
    unrelated to whichever request's context originally scheduled it -- without
    use_novel() pinning, repo access would silently resolve against whatever novel
    happens to be globally active by the time the job actually fires, not the novel
    that scheduled it."""
    from engine.setup_chat import skeleton_background_review as sbr
    from utils.paths import active_novel_id

    monkeypatch.setattr("utils.paths._active_novel_id", lambda: "other-novel")

    repo = _FakeRepo(_plot())
    monkeypatch.setattr("repositories.get_plot_repo", lambda: repo)

    observed_novel_ids = []

    async def fake_transition_review(stages):
        observed_novel_ids.append(active_novel_id())
        return []

    async def fake_stage_review(stages):
        return []

    monkeypatch.setattr(sbr, "run_chapter_transition_review", fake_transition_review)
    monkeypatch.setattr(sbr, "run_chapter_stage_review", fake_stage_review)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("skeleton", 3))
    await sbr._run_chapter_review_fix(3, "n")

    assert observed_novel_ids == ["n"]  # pinned to the scheduling novel while the job ran
    assert active_novel_id() == "other-novel"  # pin released once the job finished


@pytest.mark.asyncio
async def test_run_chapter_review_fix_clears_gate_and_notifies_even_on_llm_exception(
    monkeypatch,
):
    """A background job must never leave a chapter permanently locked."""
    from engine.setup_chat import skeleton_background_review as sbr
    from engine.setup_chat import skeleton_pipeline as sp

    repo = _FakeRepo(_plot())
    monkeypatch.setattr("repositories.get_plot_repo", lambda: repo)

    async def boom(stages):
        raise RuntimeError("LLM 超时")

    monkeypatch.setattr(sbr, "run_chapter_transition_review", boom)

    async def fake_stage_review(stages):
        return []

    monkeypatch.setattr(sbr, "run_chapter_stage_review", fake_stage_review)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("skeleton", 3))
    await sbr._run_chapter_review_fix(3, "n")

    assert sp.is_review_active("n", 3) is False
    assert len(hub.notices) == 1
    assert "━━ 第3章骨架 ━━" in hub.notices[0][1]
    assert "异常" in hub.notices[0][1]


@pytest.mark.asyncio
async def test_run_chapter_review_fix_does_not_rebroadcast_started_when_another_chapter_active(
    monkeypatch,
):
    from engine.setup_chat import skeleton_background_review as sbr
    from engine.setup_chat import skeleton_pipeline as sp

    sp.mark_review_active("n", 99)  # a different chapter already "reviewing"

    repo = _FakeRepo(_plot())
    monkeypatch.setattr("repositories.get_plot_repo", lambda: repo)

    async def fake_transition_review(stages):
        return []

    async def fake_stage_review(stages):
        return []

    monkeypatch.setattr(sbr, "run_chapter_transition_review", fake_transition_review)
    monkeypatch.setattr(sbr, "run_chapter_stage_review", fake_stage_review)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("skeleton", 3))
    await sbr._run_chapter_review_fix(3, "n")

    types = [b["type"] for b in hub.broadcasts]
    assert "skeleton_review_started" not in types  # chapter 99 was already active
    assert "skeleton_review_done" not in types  # chapter 99 is still active after 3 finishes
    assert sp.is_review_active("n", 99) is True  # untouched


@pytest.mark.asyncio
async def test_run_chapter_review_fix_cancellation_leaves_active_flag_set_and_skips_events(
    monkeypatch,
):
    """A cancelled run must not broadcast done, must not clear _ACTIVE_REVIEWS, and must not
    fire the chat notification."""
    from engine.setup_chat import skeleton_background_review as sbr
    from engine.setup_chat import skeleton_pipeline as sp

    async def boom(stages):
        raise asyncio.CancelledError()

    monkeypatch.setattr(sbr, "run_chapter_transition_review", boom)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)
    monkeypatch.setattr("repositories.get_plot_repo", lambda: _FakeRepo(_plot()))

    REVIEW_FEEDBACK.mark_pending("n", ("skeleton", 3))
    with pytest.raises(asyncio.CancelledError):
        await sbr._run_chapter_review_fix(3, "n")

    assert sp.is_review_active("n", 3) is True  # still marked active, not cleared
    assert hub.notices == []
    assert "skeleton_review_done" not in [b["type"] for b in hub.broadcasts]


@pytest.mark.asyncio
async def test_run_chapter_review_fix_runs_fix_agent_once_then_notifies_without_re_review(
    monkeypatch,
):
    """Single-pass: review runs exactly once; if it flags problems, the fix agent runs once
    and the result is reported as-is -- no second review call."""
    from engine.setup_chat import skeleton_background_review as sbr
    from engine.setup_chat import skeleton_pipeline as sp

    repo = _FakeRepo(_plot())
    monkeypatch.setattr("repositories.get_plot_repo", lambda: repo)

    review_call_count = {"n": 0}

    async def fake_transition_review(stages):
        return []

    async def fake_stage_review(stages):
        review_call_count["n"] += 1
        return [StageReview(2, _rewrite("段尾升华句"))]

    monkeypatch.setattr(sbr, "run_chapter_transition_review", fake_transition_review)
    monkeypatch.setattr(sbr, "run_chapter_stage_review", fake_stage_review)

    fix_calls = []

    async def fake_fix_agent(chapter, failing):
        fix_calls.append((chapter, failing))
        return "已重新生成 stage 2。"

    monkeypatch.setattr(sbr, "run_chapter_skeleton_fix_agent", fake_fix_agent)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("skeleton", 3))
    await sbr._run_chapter_review_fix(3, "n")

    assert review_call_count["n"] == 1  # exactly one review pass, no re-review
    assert fix_calls == [(3, {2: ["段尾升华句"]})]
    assert sp.is_review_active("n", 3) is False
    assert len(hub.notices) == 1
    assert "━━ 第3章骨架 ━━" in hub.notices[0][1]
    assert "已重新生成 stage 2" in hub.notices[0][1]


@pytest.mark.asyncio
async def test_run_chapter_review_fix_skips_fix_agent_when_nothing_failed(monkeypatch):
    from engine.setup_chat import skeleton_background_review as sbr

    repo = _FakeRepo(_plot())
    monkeypatch.setattr("repositories.get_plot_repo", lambda: repo)

    async def fake_transition_review(stages):
        return []

    async def fake_stage_review(stages):
        return [StageReview(1, _accept()), StageReview(2, _accept())]

    monkeypatch.setattr(sbr, "run_chapter_transition_review", fake_transition_review)
    monkeypatch.setattr(sbr, "run_chapter_stage_review", fake_stage_review)

    fix_calls = []

    async def fail_if_called(chapter, failing):
        fix_calls.append((chapter, failing))
        raise AssertionError("must not run fix agent when nothing failed review")

    monkeypatch.setattr(sbr, "run_chapter_skeleton_fix_agent", fail_if_called)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("skeleton", 3))
    await sbr._run_chapter_review_fix(3, "n")

    assert fix_calls == []
    assert len(hub.notices) == 1
    assert "【通过，无需调整】第3章骨架" in hub.notices[0][1]


@pytest.mark.asyncio
async def test_regenerate_stage_tool_for_regenerates_and_saves(monkeypatch):
    from engine.setup_chat import skeleton_background_review as sbr

    repo = _FakeRepo(_plot())
    monkeypatch.setattr("repositories.get_plot_repo", lambda: repo)

    async def fake_generate(chapter, stage_num, *, overview, is_revision):
        assert (chapter, stage_num, overview, is_revision) == (3, 2, "段尾升华句", True)
        return [{"text": "修复后的第二段。", "sensation_notes": []}]

    monkeypatch.setattr(sbr.skeleton_writer, "generate_stage_beats", fake_generate)

    async def fake_fill_dialogue_drafts(chapter, by_num, generated):
        pass

    monkeypatch.setattr("engine.setup_chat.tools._fill_dialogue_drafts", fake_fill_dialogue_drafts)

    tool = sbr._regenerate_stage_tool_for(3)
    out = await tool.ainvoke({"stage_num": 2, "guidance": "段尾升华句"})

    assert "已按反馈重新生成" in out
    assert repo.chapters[0]["stages"][1]["beats"][0]["text"] == "修复后的第二段。"


@pytest.mark.asyncio
async def test_run_chapter_skeleton_fix_agent_invokes_shared_runner(monkeypatch):
    from engine.setup_chat import skeleton_background_review as sbr

    captured = {}

    async def fake_run_single_shot(*, node_name, tools, prompt, task_text):
        captured["node_name"] = node_name
        captured["task_text"] = task_text
        return "已重新生成 stage 2。"

    monkeypatch.setattr(
        "engine.setup_chat.fix_agent_runner.run_single_shot_fix_agent", fake_run_single_shot,
    )

    result = await sbr.run_chapter_skeleton_fix_agent(3, {2: ["段尾升华句"]})

    assert result == "已重新生成 stage 2。"
    assert captured["node_name"] == "chapter_skeleton_fix_agent"
    assert "段尾升华句" in captured["task_text"]


@pytest.mark.asyncio
async def test_skeleton_review_timeout_retries_once_then_reports(monkeypatch):
    from engine.setup_chat import skeleton_background_review as sbr
    from engine.setup_chat import skeleton_pipeline

    REVIEW_FEEDBACK.clear_all("n")
    scheduled: list = []
    import api.services.scheduler as sched
    monkeypatch.setattr(sched.SCHEDULER, "schedule_once", lambda *a, **k: scheduled.append(a))
    monkeypatch.setattr(skeleton_pipeline, "clear_review_active", lambda *a: None)
    monkeypatch.setattr(skeleton_pipeline, "any_review_active", lambda nid: False)
    monkeypatch.setattr(sbr, "_broadcast_skeleton_event", AsyncMock())

    reported: list = []

    class _Hub:
        async def report_review_done(self, nid, pkey, entries):
            reported.append((pkey, entries))

    monkeypatch.setattr("api.routes._hub_instance", lambda: _Hub())

    await sbr._on_chapter_review_timeout("n", 3)
    assert scheduled and not reported

    await sbr._on_chapter_review_timeout("n", 3)
    assert reported and reported[0][1][0][1].status.value == "timeout"
