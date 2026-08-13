"""Event queue timing scheduler: Redis ae.c-style time-ordered timer, thinly layered on asyncio.

Declare periodic / once when registering an event: periodic will re-enter the queue according to interval after completion of execution (naturally preventing overlap,
Events in the same cycle will not be queued again if they have not been run out), and they will be discarded after running once. There is also on_stop shutdown hook (run once in reverse order during shutdown,
used to release resources). Single process single event loop, all running on the same loop, not thread safe."""
from __future__ import annotations

import asyncio
import contextlib
import heapq
import itertools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from loguru import logger

CoroFactory = Callable[[], Awaitable[None]]


@dataclass(order=True)
class _Event:
    #Sort only by (when, seq): seq breaks when to tie, ensuring stability and dequeuing; other fields do not participate in comparison.
    when: float
    seq: int
    name: str = field(compare=False)
    kind: str = field(compare=False)  # "periodic" | "once"
    interval: float | None = field(compare=False)
    coro: CoroFactory = field(compare=False)
    on_timeout: CoroFactory | None = field(default=None, compare=False)


def _now() -> float:
    return asyncio.get_running_loop().time()


class EventScheduler:
    """
Time-ordered event queue + shutdown hook. Only used on the app's asyncio loop (not thread-safe)."""

    def __init__(
        self,
        *,
        watchdog_timeout_s: float = 180.0,
        watchdog_interval_s: float = 30.0,
    ) -> None:
        self._heap: list[_Event] = []
        self._seq = itertools.count()
        self._wake = asyncio.Event()
        self._loop_task: asyncio.Task | None = None
        self._inflight: set[asyncio.Task] = set()
        self._inflight_once_names: set[str] = set()
        self._inflight_once_tasks: dict[str, asyncio.Task] = {}
        # name -> (started_at, on_timeout); used by watchdog when a once-job never resumes
        # (e.g. RecursionError in Handle._run) so its coroutine finally never runs.
        self._inflight_once_meta: dict[str, tuple[float, CoroFactory | None]] = {}
        self._stop_hooks: list[tuple[str, CoroFactory]] = []
        self._running = False
        self._watchdog_timeout_s = watchdog_timeout_s
        self._watchdog_interval_s = watchdog_interval_s

    #---- register ----
    def register_periodic(
        self, name: str, interval_s: float, coro: CoroFactory, *, fire_immediately: bool = False
    ) -> None:
        delay = 0.0 if fire_immediately else interval_s
        self._push(_Event(_now() + delay, next(self._seq), name, "periodic", interval_s, coro))

    def schedule_once(
        self,
        name: str,
        delay_s: float,
        coro: CoroFactory,
        *,
        dedup: bool = False,
        on_timeout: CoroFactory | None = None,
    ) -> None:
        if dedup and self._has_active_once(name):
            return  #The same name is already in the queue/running, skip (B-level anti-shake)
        self._push(
            _Event(
                _now() + delay_s,
                next(self._seq),
                name,
                "once",
                None,
                coro,
                on_timeout=on_timeout,
            )
        )

    def _has_active_once(self, name: str) -> bool:
        if name in self._inflight_once_names:
            return True
        return any(ev.name == name and ev.kind == "once" for ev in self._heap)

    def has_active_once(self, name: str) -> bool:
        """True iff a "once" job with this name is currently inflight (running). Doesn't
        count queued-but-not-yet-fired entries -- callers of this (is_cascade_active) treat
        a delay=0.0 job that hasn't fired yet as "not yet active", a vanishingly small and
        harmless window."""
        return name in self._inflight_once_tasks

    def cancel_once(self, name: str) -> asyncio.Task | None:
        """Cancels a currently-running "once" job by name; if it's still sitting in the heap
        unfired, removes it there instead. Returns the cancelled Task (caller may await it,
        suppressing CancelledError, to confirm it actually stopped before proceeding) or None
        when there was nothing to cancel."""
        task = self._inflight_once_tasks.get(name)
        if task is not None and not task.done():
            task.cancel()
            return task
        self._heap = [ev for ev in self._heap if not (ev.name == name and ev.kind == "once")]
        heapq.heapify(self._heap)
        return None

    def on_stop(self, name: str, coro: CoroFactory) -> None:
        self._stop_hooks.append((name, coro))

    #---- life cycle ----
    def start(self) -> None:
        if self._loop_task is not None:
            return
        self._running = True
        # Recreate _wake fresh on every start(): an asyncio.Event binds to whichever event loop
        # first calls .wait()/.set() on it, and a process-level EventScheduler singleton (like
        # api.hub.SCHEDULER) can legitimately be started/stopped across multiple different event
        # loops in the same process -- e.g. successive test runs each spinning up their own loop
        # via TestClient's lifespan context. Reusing a stale Event bound to an already-closed
        # loop raises "bound to a different event loop" the next time start() runs on a new one.
        self._wake = asyncio.Event()
        self._loop_task = asyncio.create_task(self._run(), name="event-scheduler")
        # Internal periodic: force-clear once-jobs whose coroutine never resumed (see
        # docs/superpowers/specs/2026-08-13-scheduler-watchdog-timeout-design.md). A slow-but-
        # legitimate job past this timeout loses only its "done" notification; data is fine.
        self.register_periodic(
            "scheduler-watchdog", self._watchdog_interval_s, self._check_watchdog
        )

    async def stop(self, *, drain_timeout: float = 5.0) -> None:
        self._running = False
        if self._loop_task is not None:
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
            self._loop_task = None
        for t in list(self._inflight):
            t.cancel()
        if self._inflight:
            await asyncio.wait(set(self._inflight), timeout=drain_timeout)
        self._inflight.clear()
        self._inflight_once_meta.clear()
        #Running shutdown hooks in reverse order: isolation + timeout one by one, single failure does not block other releases
        for name, coro in reversed(self._stop_hooks):
            try:
                await asyncio.wait_for(coro(), timeout=drain_timeout)
            except Exception:  #noqa: BLE001 - Do your best when releasing during shutdown. Failure of a single hook will not affect the rest.
                logger.exception("[scheduler] stop hook '{}' failed", name)

    #---- Internal ----
    def _push(self, ev: _Event) -> None:
        heapq.heappush(self._heap, ev)
        self._wake.set()  #Wake up the main loop: Newly queued more urgent events do not have to wait for the old sleep to wake up

    async def _run(self) -> None:
        while self._running:
            self._wake.clear()  #Before reading the top of the heap, avoid missing wake-up
            if not self._heap:
                await self._wake.wait()
                continue
            delay = self._heap[0].when - _now()
            if delay > 0:
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=delay)
                continue
            ev = heapq.heappop(self._heap)
            self._dispatch(ev)

    async def _check_watchdog(self) -> None:
        now = _now()
        stuck = [
            name
            for name, (started, _cb) in self._inflight_once_meta.items()
            if now - started > self._watchdog_timeout_s
        ]
        for name in stuck:
            task = self._inflight_once_tasks.get(name)
            _started, on_timeout = self._inflight_once_meta.get(name, (0.0, None))
            logger.warning(
                "[scheduler] job '{}' exceeded watchdog timeout ({}s), forcing done",
                name,
                self._watchdog_timeout_s,
            )
            self._inflight_once_names.discard(name)
            self._inflight_once_tasks.pop(name, None)
            self._inflight_once_meta.pop(name, None)
            # Best-effort: orphan tasks that never resumed often ignore cancel too.
            if task is not None and not task.done():
                task.cancel()
            if on_timeout is not None:
                asyncio.create_task(self._run_timeout_hook(name, on_timeout))

    async def _run_timeout_hook(self, name: str, on_timeout: CoroFactory) -> None:
        try:
            await on_timeout()
        except Exception:  # noqa: BLE001 - watchdog hook must never kill the loop
            logger.exception("[scheduler] on_timeout hook for '{}' failed", name)

    def _dispatch(self, ev: _Event) -> None:
        async def _runner() -> None:
            try:
                await ev.coro()
            except asyncio.CancelledError:
                raise
            except Exception:  #noqa: BLE001 — Only log callback exceptions, never kill the loop
                logger.exception("[scheduler] job '{}' failed", ev.name)
            finally:
                if ev.kind == "once":
                    # Identity guard: only clear if we are still the registered task.
                    # Watchdog may have already cleared us and a same-named new job may be
                    # registered; a late orphan finally must not wipe the new registration.
                    current = asyncio.current_task()
                    if self._inflight_once_tasks.get(ev.name) is current:
                        self._inflight_once_names.discard(ev.name)
                        self._inflight_once_tasks.pop(ev.name, None)
                        self._inflight_once_meta.pop(ev.name, None)
                #periodic is re-arranged after execution → naturally prevents overlap; no re-arrangement is performed during shutdown (_running=False)
                if ev.kind == "periodic" and self._running:
                    ev.when = _now() + (ev.interval or 0.0)
                    self._push(ev)

        if ev.kind == "once":
            started = _now()  # stamp before create_task: dispatch moment, not first resume
            self._inflight_once_names.add(ev.name)
        task = asyncio.create_task(_runner(), name=f"sched:{ev.name}")
        if ev.kind == "once":
            self._inflight_once_tasks[ev.name] = task
            self._inflight_once_meta[ev.name] = (started, ev.on_timeout)
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)


SCHEDULER = EventScheduler()
