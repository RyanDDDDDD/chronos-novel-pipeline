import pytest
from engine.author_loop.self_review import SelfReviewVerdict


def _accept():
    return SelfReviewVerdict("accept", 9.0, [("anchors", 9)], "")


def _rewrite(feedback="人设扁平"):
    return SelfReviewVerdict("rewrite", 4.0, [("anchors", 4)], feedback)


class _FakeHub:
    def __init__(self):
        self.broadcasts: list[dict] = []
        self.notices: list[tuple[str, str]] = []

    async def broadcast(self, event):
        self.broadcasts.append(event)

    async def trigger_system_notice_turn(self, novel_id, summary):
        self.notices.append((novel_id, summary))


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
async def test_cancel_active_character_fix_awaits_cancelled_task(monkeypatch):
    import asyncio

    from engine.setup_chat import character_background_review as cbr

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

    await cbr.cancel_active_character_fix("n", "甲")

    assert captured_name["name"] == "character-fix:n:甲"
    assert task.cancelled()


@pytest.mark.asyncio
async def test_cancel_active_character_fix_noop_when_nothing_running(monkeypatch):
    from engine.setup_chat import character_background_review as cbr

    import api.services.scheduler as sched
    monkeypatch.setattr(sched.SCHEDULER, "cancel_once", lambda name: None)

    await cbr.cancel_active_character_fix("n", "甲")  # must not raise


@pytest.mark.asyncio
async def test_run_character_review_notifies_pass_without_fix_agent(monkeypatch):
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

    fix_agent_calls = []

    async def fail_if_called(name, rubric):
        fix_agent_calls.append((name, rubric))
        raise AssertionError("must not run fix agent when review accepts")

    monkeypatch.setattr(cbr, "run_character_fix_agent", fail_if_called)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    await cbr._run_character_review("n", "甲")

    assert fix_agent_calls == []
    assert len(hub.notices) == 1
    novel_id, summary = hub.notices[0]
    assert novel_id == "n"
    assert "审查通过" in summary


@pytest.mark.asyncio
async def test_run_character_review_runs_fix_agent_then_notifies_on_rewrite(monkeypatch):
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

    fix_calls = []

    async def fake_fix_agent(name, rubric):
        fix_calls.append((name, rubric))
        return "已把因果锚点从「复仇」改成更具体的「为亡母复仇」。"

    monkeypatch.setattr(cbr, "run_character_fix_agent", fake_fix_agent)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    await cbr._run_character_review("n", "甲")

    assert fix_calls and fix_calls[0][0] == "甲"
    assert len(hub.notices) == 1
    novel_id, summary = hub.notices[0]
    assert novel_id == "n"
    assert "已自动修复" in summary
    assert "已把因果锚点" in summary


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

    async def boom(name, rubric):
        raise RuntimeError("Recursion limit of 32 reached")

    monkeypatch.setattr(cbr, "run_character_fix_agent", boom)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    await cbr._run_character_review("n", "甲")

    assert cbr.any_review_active("n") is False
    assert len(hub.notices) == 1
    novel_id, summary = hub.notices[0]
    assert novel_id == "n"
    assert "异常" in summary


@pytest.mark.asyncio
async def test_run_character_review_skips_chat_notice_when_notify_chat_false(monkeypatch):
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
    import asyncio
    asyncio.run(captured_coro["coro"]())

    assert run_calls == [("n", "甲", False)]


@pytest.mark.asyncio
async def test_run_character_review_silently_returns_when_character_was_deleted(monkeypatch):
    from engine.setup_chat import character_background_review as cbr

    class _FakeRepo:
        def list_raw(self):
            return []  # 角色已被删

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    await cbr._run_character_review("n", "甲")

    assert hub.notices == []


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

    await cbr._run_character_review("n", "甲")

    assert fix_agent_calls == []
    assert len(hub.notices) == 1
    assert "审查通过" in hub.notices[0][1]


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
    import asyncio

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
    """Regression: cancel_active_character_fix can land while the job is still suspended
    inside the 'character_review_started' broadcast await -- i.e. before mark_review_active
    has run. If that cancellation isn't inside the try/finally, clear_review_active/
    character_review_done never fire and the frontend toast is stranded on forever, even
    though nothing is actually reviewing anymore."""
    import asyncio

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
