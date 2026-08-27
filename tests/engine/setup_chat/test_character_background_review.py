import asyncio

import pytest
from api.services.setup_chat_review_feedback import REVIEW_FEEDBACK, render_review_feedback
from engine.author_loop.self_review import SelfReviewVerdict


def _accept():
    return SelfReviewVerdict("accept", 9.0, [("anchors", 9)], "")


def _rewrite(feedback="人设扁平"):
    return SelfReviewVerdict("rewrite", 4.0, [("anchors", 4)], feedback)


def _make_awaitable(value):
    async def _coro(*_a, **_k):
        return value
    return _coro()


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
    from engine.setup_chat import character_background_review as cbr

    cbr._ACTIVE_CHARACTER_REVIEWS.clear()
    REVIEW_FEEDBACK.clear_all("n")
    yield
    cbr._ACTIVE_CHARACTER_REVIEWS.clear()
    REVIEW_FEEDBACK.clear_all("n")


def test_schedule_character_quality_review_registers_a_dedup_once_event(monkeypatch):
    from engine.setup_chat import character_background_review as cbr

    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")
    captured = {}

    def fake_schedule_once(name, delay_s, coro, *, dedup=False, on_timeout=None):
        captured["name"] = name
        captured["delay_s"] = delay_s
        captured["dedup"] = dedup
        captured["on_timeout"] = on_timeout

    import api.services.scheduler as sched
    monkeypatch.setattr(sched.SCHEDULER, "schedule_once", fake_schedule_once)

    cbr.schedule_character_quality_review("甲")

    assert captured["name"] == "character-fix:n:甲"
    assert captured["delay_s"] == 0.0
    assert captured["dedup"] is True
    assert captured["on_timeout"] is not None


@pytest.mark.asyncio
async def test_run_character_review_pass_records_clean_entry(monkeypatch):
    from engine.setup_chat import character_background_review as cbr

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "given_name": "甲"}]

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)

    async def fake_run_cast_review(char):
        assert char["given_name"] == "甲"
        return _accept()

    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.run_cast_review", fake_run_cast_review,
    )
    monkeypatch.setattr(
        "engine.setup.cast.cast_validator.race_mismatch_advisory", lambda char: "",
    )

    fix_agent_calls = []

    async def fail_if_called(name, rubric):
        fix_agent_calls.append((name, rubric))
        raise AssertionError("must not run fix agent when review accepts")

    monkeypatch.setattr(cbr, "run_character_fix_agent", fail_if_called)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("character", "甲"))
    await cbr._run_character_review("n", "甲")

    assert fix_agent_calls == []
    assert len(hub.notices) == 1
    novel_id, summary = hub.notices[0]
    assert novel_id == "n"
    assert "【通过，无需调整】角色「甲」" in summary


@pytest.mark.asyncio
async def test_run_character_review_rewrite_records_resolved_entry(monkeypatch):
    from engine.setup_chat import character_background_review as cbr

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "given_name": "甲"}]

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)

    async def fake_run_cast_review(char):
        return _rewrite("人设扁平")

    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.run_cast_review", fake_run_cast_review,
    )
    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.active_hooks", lambda names: [],
    )
    monkeypatch.setattr(
        "engine.setup.cast.cast_validator.race_mismatch_advisory", lambda char: "",
    )

    fix_calls = []

    async def fake_fix_agent(name, rubric):
        fix_calls.append((name, rubric))
        return "已把因果锚点从「复仇」改成更具体的「为亡母复仇」。"

    monkeypatch.setattr(cbr, "run_character_fix_agent", fake_fix_agent)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("character", "甲"))
    await cbr._run_character_review("n", "甲")

    assert fix_calls and fix_calls[0][0] == "甲"
    assert len(hub.notices) == 1
    novel_id, summary = hub.notices[0]
    assert novel_id == "n"
    assert "━━ 角色「甲」 ━━" in summary
    assert "已把因果锚点" in summary
    assert summary.count("不要据此再手动调用工具修改") == 1


@pytest.mark.asyncio
async def test_run_character_review_skips_notify_when_fix_write_loses_cas_race(monkeypatch):
    from engine.setup_chat import character_background_review as cbr

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "given_name": "甲"}]

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)

    async def fake_run_cast_review(char):
        return _rewrite("人设扁平")

    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.run_cast_review", fake_run_cast_review,
    )
    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.active_hooks", lambda names: [],
    )
    monkeypatch.setattr(
        "engine.setup.cast.cast_validator.race_mismatch_advisory", lambda char: "",
    )

    async def fake_fix_agent(name, rubric):
        return "角色「甲」在你读取之后已被修改，写入已取消。请重新读取最新数据后再改。"

    monkeypatch.setattr(cbr, "run_character_fix_agent", fake_fix_agent)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("character", "甲"))
    await cbr._run_character_review("n", "甲")

    assert hub.notices == []
    assert REVIEW_FEEDBACK.snapshot("n") == []
    assert REVIEW_FEEDBACK.has_pending("n") is False


@pytest.mark.asyncio
async def test_run_character_review_clears_gate_and_notifies_even_on_fix_agent_exception(monkeypatch):
    """A crashed fix agent (e.g. GraphRecursionError) must still notify the chat and
    clear the review-active flag, not leave the frontend waiting silently."""
    from engine.setup_chat import character_background_review as cbr

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "given_name": "甲"}]

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)

    async def fake_run_cast_review(char):
        return _rewrite("人设扁平")

    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.run_cast_review", fake_run_cast_review,
    )
    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.active_hooks", lambda names: [],
    )
    monkeypatch.setattr(
        "engine.setup.cast.cast_validator.race_mismatch_advisory", lambda char: "",
    )

    async def boom(name, rubric):
        raise RuntimeError("Recursion limit of 32 reached")

    monkeypatch.setattr(cbr, "run_character_fix_agent", boom)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("character", "甲"))
    await cbr._run_character_review("n", "甲")

    assert cbr.any_review_active("n") is False
    assert len(hub.notices) == 1
    novel_id, summary = hub.notices[0]
    assert novel_id == "n"
    assert "━━ 角色「甲」 ━━" in summary
    assert "异常" in summary


@pytest.mark.asyncio
async def test_run_character_review_notify_chat_false_never_touches_buffer(monkeypatch):
    """Manual cast-page edits schedule notify_chat=False: the review/fix agent still runs
    and can still write to disk, only the chat-transcript notice is suppressed."""
    from engine.setup_chat import character_background_review as cbr

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "given_name": "甲"}]

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)

    async def fake_run_cast_review(char):
        return _rewrite("人设扁平")

    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.run_cast_review", fake_run_cast_review,
    )
    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.active_hooks", lambda names: [],
    )
    monkeypatch.setattr(
        "engine.setup.cast.cast_validator.race_mismatch_advisory", lambda char: "",
    )

    fix_calls = []

    async def fake_fix_agent(name, rubric):
        fix_calls.append((name, rubric))
        return "已修复。"

    monkeypatch.setattr(cbr, "run_character_fix_agent", fake_fix_agent)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    await cbr._run_character_review("n", "甲", notify_chat=False)

    assert fix_calls and fix_calls[0][0] == "甲"  # fix agent still ran
    assert hub.notices == []  # but chat was not notified
    assert REVIEW_FEEDBACK.snapshot("n") == []
    assert REVIEW_FEEDBACK.has_pending("n") is False


def test_schedule_character_quality_review_threads_notify_chat_flag(monkeypatch):
    from engine.setup_chat import character_background_review as cbr

    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")
    captured_coro = {}

    def fake_schedule_once(name, delay_s, coro, *, dedup=False, on_timeout=None):
        captured_coro["coro"] = coro

    import api.services.scheduler as sched
    monkeypatch.setattr(sched.SCHEDULER, "schedule_once", fake_schedule_once)

    run_calls = []

    async def fake_run(novel_id, name, *, notify_chat=True):
        run_calls.append((novel_id, name, notify_chat))

    monkeypatch.setattr(cbr, "_run_character_review", fake_run)

    cbr.schedule_character_quality_review("甲", notify_chat=False)
    asyncio.run(captured_coro["coro"]())

    assert run_calls == [("n", "甲", False)]


def test_schedule_character_quality_review_marks_pending_only_when_notify_chat(monkeypatch):
    from engine.setup_chat import character_background_review as cbr

    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")
    import api.services.scheduler as sched
    monkeypatch.setattr(sched.SCHEDULER, "schedule_once", lambda *a, **k: None)

    cbr.schedule_character_quality_review("甲", notify_chat=False)
    assert REVIEW_FEEDBACK.has_pending("n") is False

    cbr.schedule_character_quality_review("乙", notify_chat=True)
    assert REVIEW_FEEDBACK.has_pending("n") is True


@pytest.mark.asyncio
async def test_run_character_review_deleted_character_releases_barrier(monkeypatch):
    from engine.setup_chat import character_background_review as cbr

    class _FakeRepo:
        def list_raw(self):
            return []  # 角色已被删

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("character", "甲"))
    await cbr._run_character_review("n", "甲")

    assert hub.notices == []
    assert REVIEW_FEEDBACK.has_pending("n") is False


@pytest.mark.asyncio
async def test_run_character_review_runs_fix_agent_on_race_advisory_even_when_accept(monkeypatch):
    from engine.setup_chat import character_background_review as cbr

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "given_name": "甲", "race": "魅魔"}]

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)
    monkeypatch.setattr(
        "engine.setup.cast.cast_validator.race_mismatch_advisory",
        lambda char: "角色「甲」声明的种族「魅魔」不在世界设定已声明的种族列表（精灵族、人类）中。",
    )

    async def fake_run_cast_review(char):
        return _accept()

    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.run_cast_review", fake_run_cast_review,
    )
    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.active_hooks", lambda names: [],
    )

    fix_calls = []

    async def fake_fix_agent(name, feedback):
        fix_calls.append((name, feedback))
        return "已将新种族「魅魔」补充进世界设定。"

    monkeypatch.setattr(cbr, "run_character_fix_agent", fake_fix_agent)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("character", "甲"))
    await cbr._run_character_review("n", "甲")

    assert fix_calls and fix_calls[0][0] == "甲"
    assert "【种族设定】" in fix_calls[0][1]
    assert len(hub.notices) == 1
    assert "【种族设定】" in hub.notices[0][1]


@pytest.mark.asyncio
async def test_run_character_review_skips_fix_agent_when_accept_and_no_race_advisory(monkeypatch):
    from engine.setup_chat import character_background_review as cbr

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "given_name": "甲"}]

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)
    monkeypatch.setattr(
        "engine.setup.cast.cast_validator.race_mismatch_advisory",
        lambda char: "",
    )

    async def fake_run_cast_review(char):
        return _accept()

    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.run_cast_review", fake_run_cast_review,
    )

    fix_agent_calls = []

    async def fail_if_called(name, rubric):
        fix_agent_calls.append((name, rubric))
        raise AssertionError("must not run fix agent when review accepts and race matches")

    monkeypatch.setattr(cbr, "run_character_fix_agent", fail_if_called)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("character", "甲"))
    await cbr._run_character_review("n", "甲")

    assert fix_agent_calls == []
    assert len(hub.notices) == 1
    assert "【通过，无需调整】角色「甲」" in hub.notices[0][1]


@pytest.mark.asyncio
async def test_two_character_reviews_barrier_batches_into_one_notice(monkeypatch):
    from engine.setup_chat import character_background_review as cbr

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "given_name": "甲"}, {"name": "乙", "given_name": "乙"}]

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)
    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.run_cast_review",
        lambda char: _make_awaitable(_accept()))
    monkeypatch.setattr(
        "engine.setup.cast.cast_validator.race_mismatch_advisory", lambda char: "")

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("character", "甲"))
    REVIEW_FEEDBACK.mark_pending("n", ("character", "乙"))

    await cbr._run_character_review("n", "甲")
    assert hub.notices == []  # 乙 still pending

    await cbr._run_character_review("n", "乙")
    assert len(hub.notices) == 1
    assert "角色「甲」" in hub.notices[0][1] and "角色「乙」" in hub.notices[0][1]


@pytest.mark.asyncio
async def test_character_review_replacement_overwrites_in_place(monkeypatch):
    from engine.setup_chat import character_background_review as cbr

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "given_name": "甲"}]

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)
    monkeypatch.setattr(
        "engine.setup.cast.cast_validator.race_mismatch_advisory", lambda char: "")
    hub = _FakeHub(busy=True)  # hold the batch so we can observe replacement
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.run_cast_review",
        lambda char: _make_awaitable(_accept()))
    REVIEW_FEEDBACK.mark_pending("n", ("character", "甲"))
    await cbr._run_character_review("n", "甲")
    assert REVIEW_FEEDBACK.snapshot("n")[0].status.value == "clean"

    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.run_cast_review",
        lambda char: _make_awaitable(_rewrite("人设扁平")))
    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.active_hooks", lambda names: [])

    async def fake_fix(name, rubric):
        return "已修。"

    monkeypatch.setattr(cbr, "run_character_fix_agent", fake_fix)
    REVIEW_FEEDBACK.mark_pending("n", ("character", "甲"))
    await cbr._run_character_review("n", "甲")

    snap = REVIEW_FEEDBACK.snapshot("n")
    assert len(snap) == 1  # replaced in place, not appended
    assert snap[0].status.value == "resolved"


@pytest.mark.asyncio
async def test_character_review_timeout_retries_once_then_reports(monkeypatch):
    from engine.setup_chat import character_background_review as cbr

    REVIEW_FEEDBACK.clear_all("n")
    scheduled: list[str] = []
    import api.services.scheduler as sched
    monkeypatch.setattr(sched.SCHEDULER, "schedule_once",
                        lambda name, *a, **k: scheduled.append(name))

    reported: list[tuple] = []

    class _Hub:
        async def broadcast(self, event):
            pass

        async def report_review_done(self, nid, pkey, entries):
            reported.append((pkey, entries))

    monkeypatch.setattr("api.routes._hub_instance", lambda: _Hub())

    await cbr._on_character_review_timeout("n", "甲", notify_chat=True)
    assert scheduled and reported == []

    await cbr._on_character_review_timeout("n", "甲", notify_chat=True)
    assert len(reported) == 1
    (_pkey, entries) = reported[0]
    ((_bk, entry),) = entries
    assert entry.status.value == "timeout"


@pytest.mark.asyncio
async def test_run_character_fix_agent_tools_include_add_world_race(monkeypatch):
    from engine.setup_chat import character_background_review as cbr

    captured = {}

    async def fake_run_single_shot(*, node_name, tools, prompt, task_text):
        captured["tools"] = tools
        captured["task_text"] = task_text
        return "已修复。"

    monkeypatch.setattr(
        "engine.setup_chat.fix_agent_runner.run_single_shot_fix_agent", fake_run_single_shot,
    )

    result = await cbr.run_character_fix_agent("甲", "【种族设定】\n种族不匹配。")

    assert result == "已修复。"
    assert any(getattr(t, "name", None) == "add_world_race" for t in captured["tools"])
    assert "请按反馈修改" in captured["task_text"]


def test_active_review_tracking_add_discard_aggregate():
    from engine.setup_chat import character_background_review as cbr

    assert cbr.any_review_active("n") is False
    cbr.mark_review_active("n", "甲")
    assert cbr.any_review_active("n") is True
    cbr.mark_review_active("n", "乙")
    cbr.clear_review_active("n", "甲")
    assert cbr.any_review_active("n") is True  # 乙 still active
    cbr.clear_review_active("n", "乙")
    assert cbr.any_review_active("n") is False


@pytest.mark.asyncio
async def test_run_character_review_broadcasts_started_and_done(monkeypatch):
    from engine.setup_chat import character_background_review as cbr

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "given_name": "甲"}]

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)

    async def fake_run_cast_review(char):
        return _accept()

    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.run_cast_review", fake_run_cast_review,
    )

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    await cbr._run_character_review("n", "甲")

    assert hub.broadcasts[0] == {"type": "character_review_started", "novel_id": "n"}
    assert hub.broadcasts[1] == {"type": "character_review_done", "novel_id": "n"}
    assert cbr.any_review_active("n") is False


@pytest.mark.asyncio
async def test_run_character_review_does_not_rebroadcast_started_when_overlapping(monkeypatch):
    from engine.setup_chat import character_background_review as cbr

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "given_name": "甲"}, {"name": "乙", "given_name": "乙"}]

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)

    gate = asyncio.Event()

    async def fake_run_cast_review(char):
        await gate.wait()
        return _accept()

    monkeypatch.setattr(
        "engine.setup_chat.setup_quality_review.run_cast_review", fake_run_cast_review,
    )

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    t1 = asyncio.create_task(cbr._run_character_review("n", "甲"))
    await asyncio.sleep(0)  # let t1 mark itself active before t2 starts
    t2 = asyncio.create_task(cbr._run_character_review("n", "乙"))
    await asyncio.sleep(0)
    gate.set()
    await asyncio.gather(t1, t2)

    started = [b for b in hub.broadcasts if b["type"] == "character_review_started"]
    done = [b for b in hub.broadcasts if b["type"] == "character_review_done"]
    assert len(started) == 1  # only the first job broadcasts "started"
    assert len(done) == 1     # only the last job to finish broadcasts "done"


@pytest.mark.asyncio
async def test_run_character_review_cancelled_during_started_broadcast_still_emits_done(monkeypatch):
    """Regression: cancellation can land while the job is still suspended
    inside the 'character_review_started' broadcast await -- i.e. before mark_review_active
    has run. If that cancellation isn't inside the try/finally, clear_review_active/
    character_review_done never fire and the frontend toast is stranded on forever, even
    though nothing is actually reviewing anymore."""
    from engine.setup_chat import character_background_review as cbr

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "given_name": "甲"}]

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)

    class _BlockingHub(_FakeHub):
        def __init__(self):
            super().__init__()
            self.started_broadcasting = asyncio.Event()

        async def broadcast(self, event):
            await super().broadcast(event)
            if event["type"] == "character_review_started":
                self.started_broadcasting.set()
                await asyncio.sleep(3600)  # simulate cancellation landing mid-broadcast

    hub = _BlockingHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    task = asyncio.create_task(cbr._run_character_review("n", "甲"))
    await hub.started_broadcasting.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cbr.any_review_active("n") is False
    done = [b for b in hub.broadcasts if b["type"] == "character_review_done"]
    assert len(done) == 1  # frontend toast must be told to clear even though cancelled
