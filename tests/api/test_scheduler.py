import asyncio
import contextlib

import pytest
from api.services.scheduler import EventScheduler


@pytest.mark.asyncio
async def test_periodic_fires_repeatedly_and_stops():
    calls = 0

    async def job():
        nonlocal calls
        calls += 1

    s = EventScheduler()
    s.register_periodic("tick", 0.01, job)
    s.start()
    await asyncio.sleep(0.1)
    await s.stop()
    fired = calls
    assert fired >= 3  #0.1s / 0.01s ran at least a few times
    await asyncio.sleep(0.03)
    assert calls == fired  #No more growth after stopping


@pytest.mark.asyncio
async def test_once_fires_exactly_once_then_discarded():
    calls = 0

    async def job():
        nonlocal calls
        calls += 1

    s = EventScheduler()
    s.schedule_once("one", 0.01, job)
    s.start()
    await asyncio.sleep(0.05)
    assert calls == 1
    # Once jobs are discarded after firing; only the internal watchdog periodic may remain.
    assert all(ev.kind != "once" for ev in s._heap)
    await s.stop()


@pytest.mark.asyncio
async def test_periodic_no_overlap_when_callback_slow():
    """Callback is slower than interval: it is rearranged after execution → only one is flying at the same time."""
    concurrent = 0
    max_concurrent = 0

    async def slow():
        nonlocal concurrent, max_concurrent
        concurrent += 1
        max_concurrent = max(max_concurrent, concurrent)
        await asyncio.sleep(0.03)
        concurrent -= 1

    s = EventScheduler()
    s.register_periodic("slow", 0.01, slow, fire_immediately=True)
    s.start()
    await asyncio.sleep(0.1)
    await s.stop()
    assert max_concurrent == 1


@pytest.mark.asyncio
async def test_callback_exception_does_not_kill_loop():
    boom = 0
    other = 0

    async def bad():
        nonlocal boom
        boom += 1
        raise ValueError("boom")

    async def good():
        nonlocal other
        other += 1

    s = EventScheduler()
    s.register_periodic("bad", 0.01, bad, fire_immediately=True)
    s.register_periodic("good", 0.01, good, fire_immediately=True)
    s.start()
    # 0.06s (6x the 0.01s interval) was too tight a margin under a loaded test suite --
    # sibling test_periodic_fires_repeatedly_and_stops already uses 0.1s (10x) for a single
    # job; this one runs two jobs per tick, so give it even more slack.
    await asyncio.sleep(0.15)
    await s.stop()
    assert boom >= 2  #If an exception is thrown, it will still be rescheduled as scheduled.
    assert other >= 2  #Other events are not affected and the loop survives


@pytest.mark.asyncio
async def test_urgent_event_wakes_loop_before_far_event():
    order: list[str] = []

    async def far():
        order.append("far")

    async def soon():
        order.append("soon")

    s = EventScheduler()
    s.schedule_once("far", 10.0, far)  #forward
    s.start()
    await asyncio.sleep(0)  #Let the loop enter a long sleep on far first
    s.schedule_once("soon", 0.01, soon)  #emergency
    await asyncio.sleep(0.05)
    await s.stop()
    assert order == ["soon"]  #Soon triggers first, before waiting for far


@pytest.mark.asyncio
async def test_on_stop_hooks_run_in_reverse_and_isolated():
    order: list[str] = []

    async def a():
        order.append("a")

    async def b():
        raise RuntimeError("b failed")

    async def c():
        order.append("c")

    s = EventScheduler()
    s.on_stop("a", a)
    s.on_stop("b", b)  #The exception thrown in the middle should not block a/c
    s.on_stop("c", c)
    s.start()
    await s.stop()
    assert order == ["c", "a"]  #Reverse order; b throws an exception and is isolated


@pytest.mark.asyncio
async def test_schedule_once_dedup_skips_queued_duplicate():
    s = EventScheduler()
    calls = 0

    async def job():
        nonlocal calls
        calls += 1

    s.start()
    #The same name did not run twice (give a little delay) → dedup skipped the second time
    s.schedule_once("dup", 0.05, job, dedup=True)
    s.schedule_once("dup", 0.05, job, dedup=True)
    await asyncio.sleep(0.12)
    await s.stop()
    assert calls == 1  #only run once


@pytest.mark.asyncio
async def test_schedule_once_dedup_skips_while_inflight():
    s = EventScheduler()
    started = 0

    async def slow():
        nonlocal started
        started += 1
        await asyncio.sleep(0.05)

    s.start()
    s.schedule_once("dup", 0.0, slow, dedup=True)
    await asyncio.sleep(0.01)                       #Let the first one start (inflight)
    s.schedule_once("dup", 0.0, slow, dedup=True)   #inflight same as name → skip
    await asyncio.sleep(0.1)
    await s.stop()
    assert started == 1


@pytest.mark.asyncio
async def test_schedule_once_dedup_allows_after_done():
    s = EventScheduler()
    calls = 0

    async def job():
        nonlocal calls
        calls += 1

    s.start()
    s.schedule_once("dup", 0.0, job, dedup=True)
    await asyncio.sleep(0.05)                       #After running, name clears the inflight set
    s.schedule_once("dup", 0.0, job, dedup=True)    #Can be rearranged
    await asyncio.sleep(0.05)
    await s.stop()
    assert calls == 2


@pytest.mark.asyncio
async def test_stop_is_idempotent_and_clears_state():
    s = EventScheduler()
    s.register_periodic("t", 0.01, lambda: asyncio.sleep(0))
    s.start()
    await asyncio.sleep(0.02)
    await s.stop()
    assert s._loop_task is None
    assert s._inflight == set()
    await s.stop()  #Call again without error


@pytest.mark.asyncio
async def test_cancel_once_cancels_an_inflight_task():
    sched = EventScheduler()
    sched.start()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def long_job():
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    sched.schedule_once("job-a", 0.0, long_job)
    await asyncio.wait_for(started.wait(), timeout=1)

    task = sched.cancel_once("job-a")
    assert task is not None
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)
    assert cancelled.is_set()

    await sched.stop()


@pytest.mark.asyncio
async def test_cancel_once_removes_a_not_yet_fired_entry():
    sched = EventScheduler()
    called = False

    async def job():
        nonlocal called
        called = True

    sched.schedule_once("job-b", 60.0, job)  # far enough out it won't fire during the test
    result = sched.cancel_once("job-b")

    assert result is None  # nothing was inflight -- it was still queued
    assert not sched._has_active_once("job-b")  # removed from the heap
    assert not called


def test_cancel_once_returns_none_for_unknown_name():
    sched = EventScheduler()
    assert sched.cancel_once("does-not-exist") is None


@pytest.mark.asyncio
async def test_cancel_once_is_a_noop_when_job_cancels_itself():
    """A job's coroutine calling cancel_once on its own name happens for real:
    character_background_review's fix agent re-invokes edit_character on the
    character it's already fixing, and edit_character unconditionally calls
    cancel_active_character_fix before writing -- which resolves to this same
    scheduler job. Cancelling (and the caller then awaiting) yourself is always
    wrong, so cancel_once must recognize and no-op it rather than hand back a
    task the job would then deadlock/crash awaiting."""
    sched = EventScheduler()
    sched.start()
    completed = asyncio.Event()
    self_cancel_result = "not-run"

    async def self_cancelling_job():
        nonlocal self_cancel_result
        self_cancel_result = sched.cancel_once("job-self")
        completed.set()

    sched.schedule_once("job-self", 0.0, self_cancelling_job)
    await asyncio.wait_for(completed.wait(), timeout=1)

    assert self_cancel_result is None
    await sched.stop()


@pytest.mark.asyncio
async def test_has_active_once_reflects_inflight_state():
    sched = EventScheduler()
    sched.start()
    started = asyncio.Event()

    async def long_job():
        started.set()
        await asyncio.sleep(3600)

    assert sched.has_active_once("job-c") is False
    sched.schedule_once("job-c", 0.0, long_job)
    await asyncio.wait_for(started.wait(), timeout=1)
    assert sched.has_active_once("job-c") is True

    sched.cancel_once("job-c")
    await sched.stop()


@pytest.mark.asyncio
async def test_watchdog_force_clears_stuck_inflight_job():
    s = EventScheduler(watchdog_timeout_s=0.05, watchdog_interval_s=0.02)

    async def stuck():
        await asyncio.sleep(3600)

    s.schedule_once("stuck-job", 0.0, stuck)
    s.start()
    await asyncio.sleep(0.15)
    assert s.has_active_once("stuck-job") is False
    await s.stop()


@pytest.mark.asyncio
async def test_watchdog_triggers_on_timeout_callback():
    s = EventScheduler(watchdog_timeout_s=0.05, watchdog_interval_s=0.02)
    fired = False

    async def stuck():
        await asyncio.sleep(3600)

    async def on_timeout():
        nonlocal fired
        fired = True

    s.schedule_once("stuck-cb", 0.0, stuck, on_timeout=on_timeout)
    s.start()
    await asyncio.sleep(0.15)
    assert fired is True
    await s.stop()


@pytest.mark.asyncio
async def test_watchdog_identity_guard_survives_late_orphan_completion():
    """Orphan finally after watchdog clear must not wipe a same-named new job."""
    s = EventScheduler(watchdog_timeout_s=0.05, watchdog_interval_s=0.02)
    orphan_started = asyncio.Event()
    ran_new_job = False

    async def orphan_coro():
        orphan_started.set()
        await asyncio.sleep(3600)

    async def new_job_coro():
        nonlocal ran_new_job
        await asyncio.sleep(0.01)
        ran_new_job = True

    s.schedule_once("job-x", 0.0, orphan_coro)
    s.start()
    await asyncio.wait_for(orphan_started.wait(), timeout=1)
    await asyncio.sleep(0.15)
    assert s.has_active_once("job-x") is False

    s.schedule_once("job-x", 0.0, new_job_coro)
    await asyncio.sleep(0.1)
    assert ran_new_job is True
    assert s.has_active_once("job-x") is False
    await s.stop()
