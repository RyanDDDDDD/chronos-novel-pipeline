import pytest

import repositories as repo
from engine.setup_chat import world_background_review as wbr
from engine.setup_chat.world_background_review import (
    _PendingReview,
    _merge_pending,
    is_world_review_active,
)
from repo_test_helpers import get_world, init_store
from utils.paths import use_novel


def test_merge_pending_prefers_complete_true():
    pending: dict[str, _PendingReview] = {}
    import engine.setup_chat.world_background_review as mod

    original = mod._PENDING
    mod._PENDING = pending
    try:
        _merge_pending("n1", complete=False, novel_brief=None)
        _merge_pending("n1", complete=True, novel_brief="brief")
        assert pending["n1"].complete is True
        assert pending["n1"].novel_brief == "brief"
    finally:
        mod._PENDING = original


@pytest.mark.asyncio
async def test_settle_broadcasts_started_when_nothing_was_running(monkeypatch):
    wbr._PENDING.clear()
    _merge_pending("n", complete=True, novel_brief="brief")

    import api.services.scheduler as sched

    monkeypatch.setattr(sched.SCHEDULER, "cancel_once", lambda name: None)

    run_calls: list[tuple[str, object]] = []

    def fake_schedule_once(name, delay_s, coro, *, dedup=False, on_timeout=None):
        run_calls.append((name, coro))

    monkeypatch.setattr(sched.SCHEDULER, "schedule_once", fake_schedule_once)

    broadcasts: list[tuple[str, str]] = []

    async def fake_broadcast(nid, event_type):
        broadcasts.append((nid, event_type))

    monkeypatch.setattr(wbr, "_broadcast", fake_broadcast)

    await wbr._settle("n")

    assert broadcasts == [("n", "world_review_started")]
    assert run_calls[0][0] == "world-review-run:n"
    assert "n" not in wbr._PENDING


@pytest.mark.asyncio
async def test_settle_passes_on_timeout_hook(monkeypatch):
    wbr._PENDING.clear()
    _merge_pending("n", complete=True, novel_brief=None)

    import api.services.scheduler as sched

    monkeypatch.setattr(sched.SCHEDULER, "cancel_once", lambda name: None)
    captured: dict = {}

    def fake_schedule_once(name, delay_s, coro, *, dedup=False, on_timeout=None):
        captured["on_timeout"] = on_timeout

    monkeypatch.setattr(sched.SCHEDULER, "schedule_once", fake_schedule_once)
    monkeypatch.setattr(wbr, "_broadcast", lambda *a, **k: _noop_async())

    await wbr._settle("n")

    assert captured["on_timeout"] is not None


async def _noop_async():
    pass


@pytest.mark.asyncio
async def test_run_world_review_runs_fix_agent_and_notifies_on_advice(monkeypatch):
    novel_id = "novel-test"
    with use_novel(novel_id):
        repo.init_repositories()
        repo.get_world_repo().save({"tone": "冷峻"})

    params = _PendingReview(complete=True, novel_brief="brief")

    async def _fake_gate(_bible, *, complete=None, novel_brief=None):
        assert complete is True
        assert novel_brief == "brief"
        return True, "设定质量建议（已写入，可按需改进）：\n\n【测试】\n请补全"

    broadcasts: list[tuple[str, str]] = []
    notices: list[str] = []

    async def fake_broadcast(nid, et):
        broadcasts.append((nid, et))

    class _Hub:
        async def trigger_system_notice_turn(self, _nid, summary):
            notices.append(summary)

    fix_calls = []

    async def fake_fix_agent(rubric):
        fix_calls.append(rubric)
        return "已把基调补充为更具体的「压抑求生」。"

    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.gate_world_bible",
        _fake_gate,
    )
    monkeypatch.setattr(wbr, "_broadcast", fake_broadcast)
    monkeypatch.setattr("api.routes._hub_instance", lambda: _Hub())
    monkeypatch.setattr(wbr, "run_world_fix_agent", fake_fix_agent)

    with use_novel(novel_id):
        await wbr._run_world_review(novel_id, params)

    assert broadcasts == [(novel_id, "world_review_done")]
    assert fix_calls and "设定质量建议" in fix_calls[0]
    assert notices and "已把基调补充" in notices[0]


@pytest.mark.asyncio
async def test_run_world_review_clears_gate_and_notifies_even_on_fix_agent_exception(monkeypatch):
    """A crashed fix agent (e.g. GraphRecursionError) must still notify the chat, not leave
    the frontend waiting silently -- mirrors skeleton_background_review's equivalent guard."""
    novel_id = "novel-test"
    with use_novel(novel_id):
        repo.init_repositories()
        repo.get_world_repo().save({"tone": "冷峻"})

    params = _PendingReview(complete=True, novel_brief="brief")

    async def _fake_gate(_bible, *, complete=None, novel_brief=None):
        return True, "设定质量建议（已写入，可按需改进）：\n\n【测试】\n请补全"

    broadcasts: list[tuple[str, str]] = []
    notices: list[str] = []

    async def fake_broadcast(nid, et):
        broadcasts.append((nid, et))

    class _Hub:
        async def trigger_system_notice_turn(self, _nid, summary):
            notices.append(summary)

    async def boom(rubric):
        raise RuntimeError("Recursion limit of 32 reached")

    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.gate_world_bible",
        _fake_gate,
    )
    monkeypatch.setattr(wbr, "_broadcast", fake_broadcast)
    monkeypatch.setattr("api.routes._hub_instance", lambda: _Hub())
    monkeypatch.setattr(wbr, "run_world_fix_agent", boom)

    with use_novel(novel_id):
        await wbr._run_world_review(novel_id, params)

    assert broadcasts == [(novel_id, "world_review_done")]
    assert len(notices) == 1
    assert "异常" in notices[0]


@pytest.mark.asyncio
async def test_run_world_review_notifies_on_accept_without_fix_agent(monkeypatch):
    novel_id = "novel-test"
    with use_novel(novel_id):
        repo.init_repositories()
        repo.get_world_repo().save({"tone": "冷峻"})

    params = _PendingReview(complete=True, novel_brief=None)

    async def _fake_gate(_bible, *, complete=None, novel_brief=None):
        return True, ""  # accept: no advisory rubric

    notices: list[str] = []

    class _Hub:
        async def trigger_system_notice_turn(self, _nid, summary):
            notices.append(summary)

    fix_calls = []

    async def fail_if_called(rubric):
        fix_calls.append(rubric)
        raise AssertionError("must not run fix agent on accept")

    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.gate_world_bible",
        _fake_gate,
    )
    monkeypatch.setattr(wbr, "_broadcast", lambda *a, **k: _noop())
    monkeypatch.setattr("api.routes._hub_instance", lambda: _Hub())
    monkeypatch.setattr(wbr, "run_world_fix_agent", fail_if_called)

    with use_novel(novel_id):
        await wbr._run_world_review(novel_id, params)

    assert fix_calls == []
    assert notices and "审查通过" in notices[0]


async def _noop():
    return None


@pytest.mark.asyncio
async def test_cancel_active_world_review_or_fix_awaits_cancelled_task(monkeypatch):
    import asyncio

    async def long_running():
        await asyncio.sleep(3600)

    task = asyncio.create_task(long_running())
    captured_name = {}

    def fake_cancel_once(name):
        captured_name["name"] = name
        task.cancel()
        return task

    import api.services.scheduler as sched
    monkeypatch.setattr(sched.SCHEDULER, "cancel_once", fake_cancel_once)

    await wbr.cancel_active_world_review_or_fix("n")

    assert captured_name["name"] == "world-review-run:n"
    assert task.cancelled()


@pytest.mark.asyncio
async def test_construct_world_schedules_background_review(monkeypatch):
    from engine.setup_chat.tools import construct_world
    from tests.engine.setup_chat.test_tools import _world_args

    init_store()

    scheduled: list[dict] = []

    def _fake_schedule(**kwargs):
        scheduled.append(kwargs)

    monkeypatch.setattr(
        "engine.setup_chat.world_background_review.schedule_world_quality_review",
        _fake_schedule,
    )

    out = await construct_world.ainvoke(_world_args(tone="冷峻"))
    assert "已写入 worldview" in out or "已写入世界观" in out
    assert "设定质量建议" not in out
    saved = get_world()
    assert saved is not None
    assert saved["tone"] == "冷峻"
    assert scheduled == [{"complete": True}]


def test_is_world_review_active(monkeypatch):
    import api.services.scheduler as sched

    monkeypatch.setattr(sched.SCHEDULER, "has_active_once", lambda name: name == "world-review-run:n")
    assert is_world_review_active("n") is True
    assert is_world_review_active("other") is False
