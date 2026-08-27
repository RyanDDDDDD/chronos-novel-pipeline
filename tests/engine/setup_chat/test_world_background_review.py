
import pytest
from api.services.setup_chat_review_feedback import REVIEW_FEEDBACK, render_review_feedback
from engine.setup_chat import world_background_review as wbr
from engine.setup_chat.world_background_review import (
    _merge_pending,
    _PendingReview,
    is_world_review_active,
)
from repo_test_helpers import get_world, init_store


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
    wbr._PENDING.clear()
    REVIEW_FEEDBACK.clear_all("n")
    REVIEW_FEEDBACK.clear_all("novel-test")
    yield
    wbr._PENDING.clear()
    REVIEW_FEEDBACK.clear_all("n")
    REVIEW_FEEDBACK.clear_all("novel-test")


async def _noop_async():
    pass


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


@pytest.mark.asyncio
async def test_run_world_review_clean_records_clean_entry_and_flushes(monkeypatch):
    class _Repo:
        def get(self):
            return {"背景": "x"}

    monkeypatch.setattr("repositories.get_world_repo", _Repo)

    async def fake_gate(bible, *, complete=None, novel_brief=None):
        return True, ""  # ok, no hint

    monkeypatch.setattr("engine.setup_chat.setup_quality_review.gate_world_bible", fake_gate)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("world",))  # schedule_* would have done this
    await wbr._run_world_review("n", _PendingReview())

    assert len(hub.notices) == 1
    assert "【通过，无需调整】世界观" in hub.notices[0][1]


@pytest.mark.asyncio
async def test_run_world_review_with_hint_runs_fix_then_records_resolved(monkeypatch):
    class _Repo:
        def get(self):
            return {"背景": "x"}

    monkeypatch.setattr("repositories.get_world_repo", _Repo)

    async def fake_gate(bible, *, complete=None, novel_brief=None):
        return False, "势力关系含糊"

    monkeypatch.setattr("engine.setup_chat.setup_quality_review.gate_world_bible", fake_gate)

    async def fake_fix(rubric):
        return "已理清三方势力关系。"

    monkeypatch.setattr(wbr, "run_world_fix_agent", fake_fix)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("world",))
    await wbr._run_world_review("n", _PendingReview())

    assert len(hub.notices) == 1
    body = hub.notices[0][1]
    assert "━━ 世界观 ━━" in body
    assert "势力关系含糊" in body and "已理清三方势力关系" in body
    assert "不要据此再手动调用工具修改" in body  # centralised notice, appended once


@pytest.mark.asyncio
async def test_run_world_review_clears_gate_and_notifies_even_on_fix_agent_exception(monkeypatch):
    """A crashed fix agent (e.g. GraphRecursionError) must still notify the chat."""
    class _Repo:
        def get(self):
            return {"背景": "x"}

    monkeypatch.setattr("repositories.get_world_repo", _Repo)

    async def fake_gate(bible, *, complete=None, novel_brief=None):
        return False, "势力关系含糊"

    monkeypatch.setattr("engine.setup_chat.setup_quality_review.gate_world_bible", fake_gate)

    async def boom(rubric):
        raise RuntimeError("Recursion limit reached")

    monkeypatch.setattr(wbr, "run_world_fix_agent", boom)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("world",))
    await wbr._run_world_review("n", _PendingReview())

    assert len(hub.notices) == 1
    body = hub.notices[0][1]
    assert "━━ 世界观 ━━" in body
    assert "后台审查异常" in body or "Recursion limit reached" in body


@pytest.mark.asyncio
async def test_run_world_review_deleted_bible_releases_barrier(monkeypatch):
    class _Repo:
        def get(self):
            return {}

    monkeypatch.setattr("repositories.get_world_repo", _Repo)
    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("world",))
    await wbr._run_world_review("n", _PendingReview())

    assert hub.notices == []
    assert REVIEW_FEEDBACK.has_pending("n") is False


def test_schedule_world_quality_review_marks_pending(monkeypatch):
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")
    import api.services.scheduler as sched
    monkeypatch.setattr(sched.SCHEDULER, "schedule_once", lambda *a, **k: None)

    wbr.schedule_world_quality_review()
    assert REVIEW_FEEDBACK.has_pending("n") is True


@pytest.mark.asyncio
async def test_world_review_barrier_two_novels_or_two_runs(monkeypatch):
    """A second pending unit holds the batch until it too resolves."""
    class _Repo:
        def get(self):
            return {"背景": "x"}

    monkeypatch.setattr("repositories.get_world_repo", _Repo)

    async def fake_gate(bible, *, complete=None, novel_brief=None):
        return True, ""

    monkeypatch.setattr("engine.setup_chat.setup_quality_review.gate_world_bible", fake_gate)
    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("world",))
    REVIEW_FEEDBACK.mark_pending("n", ("character", "甲"))  # some other review still running

    await wbr._run_world_review("n", _PendingReview())
    assert hub.notices == []  # character 甲 still pending

    # simulate character review finishing
    await hub.report_review_done(
        "n", ("character", "甲"), [])
    assert len(hub.notices) == 1
    assert "世界观" in hub.notices[0][1]


@pytest.mark.asyncio
async def test_world_review_timeout_retries_once_then_reports_timeout(monkeypatch):
    REVIEW_FEEDBACK.clear_all("n")
    scheduled: list[str] = []
    import api.services.scheduler as sched
    monkeypatch.setattr(sched.SCHEDULER, "schedule_once",
                        lambda name, *a, **k: scheduled.append(name))

    broadcasts: list[str] = []
    monkeypatch.setattr(wbr, "_broadcast",
                        lambda nid, ev: broadcasts.append(ev) or _noop_async())

    reported: list[tuple] = []

    class _Hub:
        async def report_review_done(self, nid, pkey, entries):
            reported.append((pkey, entries))

    monkeypatch.setattr("api.routes._hub_instance", lambda: _Hub())

    await wbr._on_world_review_timeout("n")
    assert scheduled and reported == []  # retried

    await wbr._on_world_review_timeout("n")
    assert len(reported) == 1
    (_pkey, entries) = reported[0]
    ((_bk, entry),) = entries
    assert entry.status.value == "timeout"


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
