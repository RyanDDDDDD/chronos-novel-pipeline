import asyncio
from unittest.mock import AsyncMock

import pytest
from api.services.setup_chat_review_feedback import REVIEW_FEEDBACK, render_review_feedback
from repo_test_helpers import seed_lore, seed_plot


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
    from engine.setup_chat import timeline_auto
    timeline_auto._CASCADE_PENDING.clear()
    REVIEW_FEEDBACK.clear_all("n")
    yield
    timeline_auto._CASCADE_PENDING.clear()
    REVIEW_FEEDBACK.clear_all("n")


def _seed(tmp_path, monkeypatch, plot, *, scan_names: tuple[str, ...] = ("甲", "乙")):
    del tmp_path
    seed_lore([{"name": n} for n in scan_names])
    seed_plot(plot)
    #missing_timeline_targets derives roster via timeline_seed._chapter_roster, which now scans
    #`description` via entity_index.scan_characters instead of reading a `characters` field.
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: [n for n in scan_names if n in text],
    )


def test_missing_timeline_targets_new_chapter_all_missing(monkeypatch, tmp_path):
    from engine.setup_chat.timeline_auto import missing_timeline_targets
    plot = [{"chapter": 1, "title": "一", "core_xp": [], "stages": [
        {"stage_num": 1, "location": "屋内", "description": "甲乙登场"}]}]
    _seed(tmp_path, monkeypatch, plot)
    out = missing_timeline_targets(1)
    assert out == [(1, "甲"), (1, "乙")]


def test_missing_timeline_targets_skips_already_built(monkeypatch, tmp_path):
    from engine.setup_chat.timeline_auto import missing_timeline_targets
    plot = [{"chapter": 1, "title": "一", "core_xp": [], "stages": [
        {"stage_num": 1, "location": "屋内", "description": "甲乙登场"}]}]
    _seed(tmp_path, monkeypatch, plot)
    from context import character_timeline
    character_timeline.append_stage("甲", 1, 1, {"personality": "已推过"})
    out = missing_timeline_targets(1)
    assert out == [(1, "乙")]


def test_missing_timeline_targets_sorted_by_chapter_ascending(monkeypatch, tmp_path):
    from engine.setup_chat.timeline_auto import missing_timeline_targets
    plot = [
        {"chapter": 1, "title": "一", "core_xp": [], "stages": [
            {"stage_num": 1, "location": "A", "description": "甲登场"}]},
        {"chapter": 2, "title": "二", "core_xp": [], "stages": [
            {"stage_num": 1, "location": "B", "description": "甲续场"}]},
    ]
    _seed(tmp_path, monkeypatch, plot)
    out = missing_timeline_targets(1)
    assert [c for c, _ in out] == [1, 2]


def test_missing_timeline_targets_names_filters_and_skips_absent_chapters(monkeypatch, tmp_path):
    from engine.setup_chat.timeline_auto import missing_timeline_targets
    plot = [
        {"chapter": 1, "title": "一", "core_xp": [], "stages": [
            {"stage_num": 1, "location": "A", "description": "甲乙登场"}]},
        {"chapter": 2, "title": "二", "core_xp": [], "stages": [
            {"stage_num": 1, "location": "B", "description": "乙续场"}]},
    ]
    _seed(tmp_path, monkeypatch, plot)
    out = missing_timeline_targets(1, names="甲")
    assert out == [(1, "甲")]  #第2章乙没有甲出场，不该出现


def test_missing_timeline_targets_respects_max_chapter(monkeypatch, tmp_path):
    from engine.setup_chat.timeline_auto import missing_timeline_targets
    plot = [
        {"chapter": 1, "title": "一", "core_xp": [], "stages": [
            {"stage_num": 1, "location": "A", "description": "甲登场"}]},
        {"chapter": 2, "title": "二", "core_xp": [], "stages": [
            {"stage_num": 1, "location": "B", "description": "甲续场"}]},
    ]
    _seed(tmp_path, monkeypatch, plot)
    out = missing_timeline_targets(1, max_chapter=1)
    assert out == [(1, "甲")]


def _seed_lore_and_plot(tmp_path, monkeypatch, lore, plot):
    del tmp_path
    seed_lore(lore)
    seed_plot(plot)


@pytest.mark.asyncio
async def test_derive_one_cold_start_skips_llm_and_uses_lore_baseline(monkeypatch, tmp_path):
    """This character's first plotted appearance (no prior chapter delta) must not call the
    LLM at all -- the resolved archive should just be the lore/cast card as-is."""
    from engine.setup_chat import timeline_auto
    lore = [{"name": "甲", "given_name": "甲", "role": "同质堕落型",
             "causal_anchors": {}, "sliders": {"侵蚀度": 0}}]
    plot = [{"chapter": 1, "title": "一", "core_xp": [], "stages": [
        {"stage_num": 1, "location": "屋内", "description": "事件", "characters": {"甲": {}}}]}]
    _seed_lore_and_plot(tmp_path, monkeypatch, lore, plot)

    async def fail_if_called(system: str, user: str) -> str:
        raise AssertionError("cold_start must not call the LLM")
    monkeypatch.setattr(timeline_auto, "_call_llm", fail_if_called)

    archive = await timeline_auto._derive_one(1, "甲")

    assert archive is not None
    assert archive["role"] == "同质堕落型"
    assert "personality" not in archive  # lore never declared one, LLM never ran to invent one

    from context import character_timeline
    snaps = character_timeline.load_timeline("甲")["snapshots"]
    assert snaps and snaps[0]["delta"] == {}  # recorded so missing_timeline_targets stops flagging it


@pytest.mark.asyncio
async def test_call_llm_routes_through_timeline_derive_node(monkeypatch):
    """_call_llm previously called get_cloud_llm() with no per-node override at all -- there
    was nothing for a 对话 tab node panel to configure. It must now resolve the
    "timeline_derive" node id (not some other node's id) through the same import_llm_params
    sidecar its sibling capability nodes (image_recognition/text_recognition/chat_identity/
    review/auto_build_setup) already use."""
    from engine.setup_chat import timeline_auto

    class _FakeResp:
        content = "derived"

    class _FakeLLM:
        async def ainvoke(self, _messages):
            return _FakeResp()

    bind_calls: list[tuple[str, dict]] = []

    def fake_bind_node_llm(llm, agent, params):
        bind_calls.append((agent, params))
        return _FakeLLM()

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: object())
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {"timeline_derive": {"model_ref": "custom-1"}}},
    )
    monkeypatch.setattr("engine.modes.author_loop_skill_prefs.bind_node_llm", fake_bind_node_llm)

    out = await timeline_auto._call_llm("sys", "user")

    assert out == "derived"
    assert bind_calls == [("timeline_derive", {"timeline_derive": {"model_ref": "custom-1"}})]


@pytest.mark.asyncio
async def test_derive_one_rolling_calls_llm_and_writes_returned_delta(monkeypatch, tmp_path):
    from engine.setup_chat import timeline_auto
    lore = [{"name": "甲", "given_name": "甲", "role": "同质堕落型",
             "causal_anchors": {}, "sliders": {"侵蚀度": 0}}]
    plot = [
        {"chapter": 1, "title": "一", "core_xp": [], "stages": [
            {"stage_num": 1, "location": "屋内", "description": "事件", "characters": {"甲": {}}}]},
        {"chapter": 2, "title": "二", "core_xp": [], "stages": [
            {"stage_num": 1, "location": "屋外", "description": "续", "characters": {"甲": {}}}]},
    ]
    _seed_lore_and_plot(tmp_path, monkeypatch, lore, plot)
    from context import character_timeline
    character_timeline.append_stage("甲", 1, 1, {})  # chapter 1 already resolved (cold_start done)

    async def fake_call(system: str, user: str) -> str:
        return '{"personality": "自由撰写的性格描述"}'
    monkeypatch.setattr(timeline_auto, "_call_llm", fake_call)

    archive = await timeline_auto._derive_one(2, "甲")
    assert archive is not None
    assert archive["personality"] == "自由撰写的性格描述"


@pytest.mark.asyncio
async def test_derive_one_rolling_retries_twice_then_gives_up(monkeypatch, tmp_path):
    from engine.setup_chat import timeline_auto
    lore = [{"name": "甲", "given_name": "甲", "role": "同质堕落型", "causal_anchors": {}}]
    plot = [
        {"chapter": 1, "title": "一", "core_xp": [], "stages": [
            {"stage_num": 1, "location": "屋内", "description": "事件", "characters": {"甲": {}}}]},
        {"chapter": 2, "title": "二", "core_xp": [], "stages": [
            {"stage_num": 1, "location": "屋外", "description": "续", "characters": {"甲": {}}}]},
    ]
    _seed_lore_and_plot(tmp_path, monkeypatch, lore, plot)
    from context import character_timeline
    character_timeline.append_stage("甲", 1, 1, {})

    calls = 0

    async def failing_call(system: str, user: str) -> str:
        nonlocal calls
        calls += 1
        return "not json"
    monkeypatch.setattr(timeline_auto, "_call_llm", failing_call)

    result = await timeline_auto._derive_one(2, "甲")
    assert result is None
    assert calls == 3  #首次 + 2 次重试


@pytest.mark.asyncio
async def test_run_timeline_cascade_processes_one_characters_chapters_in_order_and_stops_on_failure(
    monkeypatch,
):
    from engine.setup_chat import timeline_auto

    monkeypatch.setattr(
        timeline_auto, "missing_timeline_targets",
        lambda min_chapter, names=None, max_chapter=None: [(1, "甲"), (2, "甲")],
    )
    calls: list[tuple[int, str]] = []

    async def fake_derive(chapter: int, name: str):
        calls.append((chapter, name))
        return None if chapter == 1 else {"ok": True}  #第1章就失败

    monkeypatch.setattr(timeline_auto, "_derive_one", fake_derive)

    await timeline_auto.run_timeline_cascade(1)

    assert calls == [(1, "甲")]  #甲第1章失败后，甲第2章不再处理


@pytest.mark.asyncio
async def test_run_timeline_cascade_fans_out_by_character(monkeypatch):
    from engine.setup_chat import timeline_auto

    monkeypatch.setattr(
        timeline_auto, "missing_timeline_targets",
        lambda min_chapter, names=None, max_chapter=None: [(1, "甲"), (1, "乙")],
    )
    calls: list[str] = []

    async def fake_derive(chapter: int, name: str):
        calls.append(name)
        return {"ok": True}

    monkeypatch.setattr(timeline_auto, "_derive_one", fake_derive)

    await timeline_auto.run_timeline_cascade(1)

    assert set(calls) == {"甲", "乙"}


@pytest.mark.asyncio
async def test_run_timeline_cascade_isolates_failure_to_that_character(monkeypatch):
    """甲失败不该拖累乙——两人没有数据依赖，乙的所有章节都该正常跑完。"""
    from engine.setup_chat import timeline_auto

    monkeypatch.setattr(
        timeline_auto, "missing_timeline_targets",
        lambda min_chapter, names=None, max_chapter=None: [
            (1, "甲"), (2, "甲"), (1, "乙"), (2, "乙"),
        ],
    )
    calls: list[tuple[int, str]] = []

    async def fake_derive(chapter: int, name: str):
        calls.append((chapter, name))
        if name == "甲":
            return None  # 甲第1章就失败
        return {"ok": True}

    monkeypatch.setattr(timeline_auto, "_derive_one", fake_derive)

    await timeline_auto.run_timeline_cascade(1)

    甲_calls = [c for c in calls if c[1] == "甲"]
    乙_calls = [c for c in calls if c[1] == "乙"]
    assert 甲_calls == [(1, "甲")]  # 甲在第1章失败后停止
    assert 乙_calls == [(1, "乙"), (2, "乙")]  # 乙不受甲失败影响，两章都跑完


@pytest.mark.asyncio
async def test_run_timeline_cascade_runs_characters_concurrently_not_serially(monkeypatch):
    """乙不该等甲跑完才开始——两人的推演应该并发发出，而不是排队等待彼此。"""
    from engine.setup_chat import timeline_auto

    monkeypatch.setattr(
        timeline_auto, "missing_timeline_targets",
        lambda min_chapter, names=None, max_chapter=None: [(1, "甲"), (1, "乙")],
    )

    甲_started = asyncio.Event()
    乙_can_finish = asyncio.Event()
    order: list[str] = []

    async def fake_derive(chapter: int, name: str):
        if name == "甲":
            甲_started.set()
            await 乙_can_finish.wait()  # 甲卡住，等乙先跑完再放行
            order.append("甲_done")
            return {"ok": True}
        await 甲_started.wait()  # 确保甲已经开始（而非乙抢跑），再验证乙不会被甲卡住
        order.append("乙_done")
        乙_can_finish.set()
        return {"ok": True}

    monkeypatch.setattr(timeline_auto, "_derive_one", fake_derive)

    await asyncio.wait_for(timeline_auto.run_timeline_cascade(1), timeout=1.0)

    assert order == ["乙_done", "甲_done"]  # 乙先完成，证明甲没有卡住乙


@pytest.mark.asyncio
async def test_run_timeline_cascade_calls_on_progress_per_character(monkeypatch):
    from engine.setup_chat import timeline_auto

    monkeypatch.setattr(
        timeline_auto, "missing_timeline_targets",
        lambda min_chapter, names=None, max_chapter=None: [(1, "甲")],
    )

    async def _ok():
        return {"ok": True}

    monkeypatch.setattr(timeline_auto, "_derive_one", lambda chapter, name: _ok())

    progress_calls = []

    async def on_progress(name, ok, error):
        progress_calls.append((name, ok, error))

    await timeline_auto.run_timeline_cascade(1, on_progress=on_progress)

    assert progress_calls == [("甲", True, None)]


@pytest.mark.asyncio
async def test_run_timeline_cascade_forwards_max_chapter_and_names(monkeypatch):
    from engine.setup_chat import timeline_auto

    captured = {}

    def fake_missing(min_chapter, names=None, max_chapter=None):
        captured["args"] = (min_chapter, names, max_chapter)
        return []

    monkeypatch.setattr(timeline_auto, "missing_timeline_targets", fake_missing)
    await timeline_auto.run_timeline_cascade(3, names="甲", max_chapter=5)
    assert captured["args"] == (3, "甲", 5)


def test_missing_timeline_targets_accepts_a_list_of_names(monkeypatch, tmp_path):
    from engine.setup_chat.timeline_auto import missing_timeline_targets
    plot = [{"chapter": 1, "title": "一", "core_xp": [], "stages": [
        {"stage_num": 1, "location": "屋内", "description": "甲乙丙登场"}]}]
    _seed(tmp_path, monkeypatch, plot, scan_names=("甲", "乙", "丙"))
    out = missing_timeline_targets(1, names=["甲", "丙"])
    assert out == [(1, "甲"), (1, "丙")]


# ── cascade scope merging ────────────────────────────────────────────────────


def test_merge_cascade_scope_absorbs_single_name(monkeypatch):
    from engine.setup_chat import timeline_auto

    timeline_auto._CASCADE_PENDING.clear()
    timeline_auto._merge_cascade_scope("n", 3, ["甲"])
    scope = timeline_auto._CASCADE_PENDING["n"]
    assert scope.names == {"甲"}
    assert scope.min_chapter == 3


def test_merge_cascade_scope_none_absorbs_everything(monkeypatch):
    from engine.setup_chat import timeline_auto

    timeline_auto._CASCADE_PENDING.clear()
    timeline_auto._merge_cascade_scope("n", 3, ["甲"])
    timeline_auto._merge_cascade_scope("n", 1, None)
    scope = timeline_auto._CASCADE_PENDING["n"]
    assert scope.names is None  # None (all) absorbs the earlier narrower request
    assert scope.min_chapter == 1  # takes the smaller of the two


def test_merge_cascade_scope_unions_multiple_narrow_requests(monkeypatch):
    from engine.setup_chat import timeline_auto

    timeline_auto._CASCADE_PENDING.clear()
    timeline_auto._merge_cascade_scope("n", 5, ["甲"])
    timeline_auto._merge_cascade_scope("n", 2, ["乙"])
    scope = timeline_auto._CASCADE_PENDING["n"]
    assert scope.names == {"甲", "乙"}
    assert scope.min_chapter == 2


def test_merge_cascade_scope_defaults_notify_chat_true(monkeypatch):
    from engine.setup_chat import timeline_auto

    timeline_auto._CASCADE_PENDING.clear()
    timeline_auto._merge_cascade_scope("n", 3, ["甲"])
    assert timeline_auto._CASCADE_PENDING["n"].notify_chat is True


def test_merge_cascade_scope_all_silent_calls_stay_silent(monkeypatch):
    from engine.setup_chat import timeline_auto

    timeline_auto._CASCADE_PENDING.clear()
    timeline_auto._merge_cascade_scope("n", 3, ["甲"], notify_chat=False)
    timeline_auto._merge_cascade_scope("n", 1, ["乙"], notify_chat=False)
    assert timeline_auto._CASCADE_PENDING["n"].notify_chat is False


def test_merge_cascade_scope_or_merges_notify_chat_when_batches_combine(monkeypatch):
    """A manual-edit call (notify_chat=False) coalescing with a chat-triggered call
    (notify_chat=True, the default) must still notify -- the chat side has something to
    report even though the manual side doesn't."""
    from engine.setup_chat import timeline_auto

    timeline_auto._CASCADE_PENDING.clear()
    timeline_auto._merge_cascade_scope("n", 3, ["甲"], notify_chat=False)
    timeline_auto._merge_cascade_scope("n", 1, ["乙"])
    assert timeline_auto._CASCADE_PENDING["n"].notify_chat is True


def test_merge_cascade_scope_is_isolated_per_novel(monkeypatch):
    from engine.setup_chat import timeline_auto

    timeline_auto._CASCADE_PENDING.clear()
    timeline_auto._merge_cascade_scope("novel-A", 3, ["甲"])
    assert "novel-B" not in timeline_auto._CASCADE_PENDING


# ── _settle_cascade ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_settle_cascade_broadcasts_started_when_nothing_was_running(monkeypatch):
    from engine.setup_chat import timeline_auto

    timeline_auto._CASCADE_PENDING.clear()
    timeline_auto._merge_cascade_scope("n", 1, ["甲"])

    import api.services.scheduler as sched
    monkeypatch.setattr(sched.SCHEDULER, "cancel_once", lambda name: None)

    run_calls = []

    def fake_schedule_once(name, delay_s, coro, *, dedup=False, on_timeout=None):
        run_calls.append((name, coro))
        captured["on_timeout"] = on_timeout

    captured = {}
    monkeypatch.setattr(sched.SCHEDULER, "schedule_once", fake_schedule_once)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    await timeline_auto._settle_cascade("n")

    assert hub.broadcasts == [{"type": "timeline_cascade_started", "novel_id": "n"}]
    assert run_calls[0][0] == "timeline-cascade-run:n"
    assert "n" not in timeline_auto._CASCADE_PENDING  # consumed
    assert captured["on_timeout"] is not None


@pytest.mark.asyncio
async def test_settle_cascade_cancels_and_broadcasts_restarted_when_one_is_running(monkeypatch):
    from engine.setup_chat import timeline_auto

    timeline_auto._CASCADE_PENDING.clear()
    timeline_auto._merge_cascade_scope("n", 1, ["甲"])

    async def already_running():
        await asyncio.sleep(3600)

    task = asyncio.create_task(already_running())

    import api.services.scheduler as sched

    def fake_cancel_once(name):
        task.cancel()
        return task

    monkeypatch.setattr(sched.SCHEDULER, "cancel_once", fake_cancel_once)
    monkeypatch.setattr(sched.SCHEDULER, "schedule_once", lambda *a, **k: None)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    await timeline_auto._settle_cascade("n")

    assert hub.broadcasts == [{"type": "timeline_cascade_restarted", "novel_id": "n"}]


@pytest.mark.asyncio
async def test_settle_cascade_passes_merged_scope_to_the_new_run(monkeypatch):
    from engine.setup_chat import timeline_auto

    timeline_auto._CASCADE_PENDING.clear()
    timeline_auto._merge_cascade_scope("n", 5, ["甲"])
    timeline_auto._merge_cascade_scope("n", 2, ["乙"])

    import api.services.scheduler as sched
    monkeypatch.setattr(sched.SCHEDULER, "cancel_once", lambda name: None)

    captured = {}

    def fake_schedule_once(name, delay_s, coro, *, dedup=False, on_timeout=None):
        captured["coro"] = coro

    monkeypatch.setattr(sched.SCHEDULER, "schedule_once", fake_schedule_once)
    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    run_args = []

    async def fake_run(min_chapter, names, novel_id, *, notify_chat=True):
        run_args.append((min_chapter, names, novel_id, notify_chat))

    monkeypatch.setattr(timeline_auto, "_run_cascade_and_notify", fake_run)

    await timeline_auto._settle_cascade("n")
    await captured["coro"]()

    assert run_args == [(2, ["乙", "甲"], "n", True)]


def test_schedule_timeline_cascade_merges_before_dedup_settle(monkeypatch):
    """Two rapid calls with different scopes both merge into _CASCADE_PENDING even though the
    second schedule_once for the settle job gets deduped away."""
    from engine.setup_chat import timeline_auto

    timeline_auto._CASCADE_PENDING.clear()
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")

    settle_calls = []

    def fake_schedule_once(name, delay_s, coro, *, dedup=False):
        settle_calls.append(name)

    import api.services.scheduler as sched
    monkeypatch.setattr(sched.SCHEDULER, "schedule_once", fake_schedule_once)

    timeline_auto.schedule_timeline_cascade(5, names=["甲"])
    timeline_auto.schedule_timeline_cascade(2, names=["乙"])

    assert settle_calls == ["timeline-cascade-settle:n", "timeline-cascade-settle:n"]
    scope = timeline_auto._CASCADE_PENDING["n"]
    assert scope.names == {"甲", "乙"}
    assert scope.min_chapter == 2


# ── _run_cascade_and_notify + buffer tests ─────────────────────────────────────


@pytest.mark.asyncio
async def test_cascade_notify_records_per_character_entries(monkeypatch):
    from engine.setup_chat import timeline_auto as ta

    async def fake_run_timeline_cascade(min_chapter, names, *, on_progress=None):
        await on_progress("甲", True, None)
        await on_progress("乙", False, "乙 第4章推演失败")

    monkeypatch.setattr(ta, "run_timeline_cascade", fake_run_timeline_cascade)
    monkeypatch.setattr(ta, "_broadcast_cascade_event", AsyncMock())

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("timeline",))
    await ta._run_cascade_and_notify(1, ["甲", "乙"], "n", notify_chat=True)

    assert len(hub.notices) == 1
    body = hub.notices[0][1]
    assert "角色「甲」时间线" in body and "重新推演" in body
    assert "角色「乙」时间线" in body and "第4章推演失败" in body


@pytest.mark.asyncio
async def test_cascade_no_results_releases_barrier(monkeypatch):
    from engine.setup_chat import timeline_auto as ta

    async def fake_run_timeline_cascade(min_chapter, names, *, on_progress=None):
        return  # nothing to derive

    monkeypatch.setattr(ta, "run_timeline_cascade", fake_run_timeline_cascade)
    monkeypatch.setattr(ta, "_broadcast_cascade_event", AsyncMock())
    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    REVIEW_FEEDBACK.mark_pending("n", ("timeline",))
    await ta._run_cascade_and_notify(1, None, "n", notify_chat=True)

    assert hub.notices == []
    assert REVIEW_FEEDBACK.has_pending("n") is False


@pytest.mark.asyncio
async def test_cascade_notify_chat_false_never_touches_buffer(monkeypatch):
    from engine.setup_chat import timeline_auto as ta

    async def fake_run_timeline_cascade(min_chapter, names, *, on_progress=None):
        await on_progress("甲", True, None)

    monkeypatch.setattr(ta, "run_timeline_cascade", fake_run_timeline_cascade)
    monkeypatch.setattr(ta, "_broadcast_cascade_event", AsyncMock())
    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    await ta._run_cascade_and_notify(1, ["甲"], "n", notify_chat=False)
    assert hub.notices == [] and REVIEW_FEEDBACK.snapshot("n") == []


@pytest.mark.asyncio
async def test_second_cascade_replaces_same_character_keeps_others(monkeypatch):
    from engine.setup_chat import timeline_auto as ta

    monkeypatch.setattr(ta, "_broadcast_cascade_event", AsyncMock())
    hub = _FakeHub(busy=True)  # hold batch
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    async def cascade_AB(min_chapter, names, *, on_progress=None):
        await on_progress("甲", True, None)
        await on_progress("乙", True, None)

    monkeypatch.setattr(ta, "run_timeline_cascade", cascade_AB)
    REVIEW_FEEDBACK.mark_pending("n", ("timeline",))
    await ta._run_cascade_and_notify(1, ["甲", "乙"], "n", notify_chat=True)
    assert {e.label for e in REVIEW_FEEDBACK.snapshot("n")} == {"角色「甲」时间线", "角色「乙」时间线"}

    async def cascade_BC(min_chapter, names, *, on_progress=None):
        await on_progress("乙", False, "乙 重推失败")
        await on_progress("丙", True, None)

    monkeypatch.setattr(ta, "run_timeline_cascade", cascade_BC)
    REVIEW_FEEDBACK.mark_pending("n", ("timeline",))
    await ta._run_cascade_and_notify(1, ["乙", "丙"], "n", notify_chat=True)

    snap = {e.label: e for e in REVIEW_FEEDBACK.snapshot("n")}
    assert set(snap) == {"角色「甲」时间线", "角色「乙」时间线", "角色「丙」时间线"}
    assert "重推失败" in snap["角色「乙」时间线"].body  # 乙 replaced in place


def test_settle_cascade_marks_pending_only_when_notify_chat(monkeypatch):
    import api.services.scheduler as sched
    from engine.setup_chat import timeline_auto as ta
    monkeypatch.setattr(sched.SCHEDULER, "schedule_once", lambda *a, **k: None)
    monkeypatch.setattr(sched.SCHEDULER, "cancel_once", lambda name: None)
    monkeypatch.setattr(ta, "_broadcast_cascade_event", AsyncMock())

    ta._CASCADE_PENDING["n"] = ta._CascadePendingScope(names={"甲"}, min_chapter=1, notify_chat=False)
    asyncio.run(ta._settle_cascade("n"))
    assert REVIEW_FEEDBACK.has_pending("n") is False

    ta._CASCADE_PENDING["n"] = ta._CascadePendingScope(names={"甲"}, min_chapter=1, notify_chat=True)
    asyncio.run(ta._settle_cascade("n"))
    assert REVIEW_FEEDBACK.has_pending("n") is True


@pytest.mark.asyncio
async def test_timeline_cascade_timeout_retries_once_then_reports(monkeypatch):
    from engine.setup_chat import timeline_auto as ta

    REVIEW_FEEDBACK.clear_all("n")
    scheduled: list = []
    import api.services.scheduler as sched
    monkeypatch.setattr(sched.SCHEDULER, "schedule_once", lambda *a, **k: scheduled.append(a))
    monkeypatch.setattr(ta, "_broadcast_cascade_event", AsyncMock())

    reported: list = []

    class _Hub:
        async def report_review_done(self, nid, pkey, entries):
            reported.append((pkey, entries))

    monkeypatch.setattr("api.routes._hub_instance", lambda: _Hub())

    await ta._on_cascade_timeout("n", min_chapter=1, names=["甲"], notify_chat=True)
    assert scheduled and not reported

    await ta._on_cascade_timeout("n", min_chapter=1, names=["甲"], notify_chat=True)
    assert reported and reported[0][1][0][1].status.value == "timeout"


def test_schedule_timeline_cascade_captures_novel_id_at_schedule_time(monkeypatch):
    """The dispatched settle coroutine must close over the novel that was active when
    schedule_timeline_cascade was CALLED, not whatever's active when it later fires."""
    from engine.setup_chat import timeline_auto

    timeline_auto._CASCADE_PENDING.clear()
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")
    settle_calls = []

    async def fake_settle(novel_id):
        settle_calls.append(novel_id)

    monkeypatch.setattr(timeline_auto, "_settle_cascade", fake_settle)

    captured = {}

    def fake_schedule_once(name, delay_s, coro, *, dedup=False):
        captured["coro"] = coro

    import api.services.scheduler as sched
    monkeypatch.setattr(sched.SCHEDULER, "schedule_once", fake_schedule_once)

    timeline_auto.schedule_timeline_cascade(3)

    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "some-other-novel")
    asyncio.run(captured["coro"]())

    assert settle_calls == ["n"]
