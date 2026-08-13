import signal

import pytest
from api.services import heartbeat_watchdog as hw
from api.services.scheduler import EventScheduler


@pytest.fixture(autouse=True)
def _reset_last_heartbeat():
    # D4 revised: the watchdog now always registers (no CHRONOS_ROOT gate), so a real
    # _last_heartbeat value leaking out of this module would arm it for every other test
    # file's TestClient(app) too -- and a stale enough timestamp triggers a REAL SIGTERM
    # via trigger_graceful_shutdown(), killing the whole pytest run. Reset on both sides.
    hw._last_heartbeat = None
    yield
    hw._last_heartbeat = None


def _reset():
    hw._last_heartbeat = None


def test_record_heartbeat_sets_timestamp(monkeypatch):
    _reset()
    monkeypatch.setattr(hw.time, "monotonic", lambda: 100.0)
    hw.record_heartbeat()
    assert hw._last_heartbeat == 100.0


def test_trigger_graceful_shutdown_raises_sigterm(monkeypatch):
    calls = []
    monkeypatch.setattr(signal, "raise_signal", lambda sig: calls.append(sig))
    hw.trigger_graceful_shutdown("test reason")
    assert calls == [signal.SIGTERM]


@pytest.mark.asyncio
async def test_check_heartbeat_no_op_when_fresh(monkeypatch):
    _reset()
    hw._last_heartbeat = 100.0
    monkeypatch.setattr(hw.time, "monotonic", lambda: 105.0)  # 5s elapsed, well under timeout
    triggered = []
    monkeypatch.setattr(hw, "trigger_graceful_shutdown", lambda reason: triggered.append(reason))
    await hw._check_heartbeat()
    assert triggered == []


@pytest.mark.asyncio
async def test_check_heartbeat_triggers_shutdown_when_stale(monkeypatch):
    _reset()
    hw._last_heartbeat = 100.0
    monkeypatch.setattr(hw.time, "monotonic", lambda: 100.0 + hw.HEARTBEAT_TIMEOUT_S + 1)
    triggered = []
    monkeypatch.setattr(hw, "trigger_graceful_shutdown", lambda reason: triggered.append(reason))
    await hw._check_heartbeat()
    assert len(triggered) == 1
    assert "no heartbeat" in triggered[0]


@pytest.mark.asyncio
async def test_check_heartbeat_no_op_before_first_heartbeat_recorded(monkeypatch):
    _reset()  # _last_heartbeat is None -- register_heartbeat_watchdog no longer seeds it
              # (D4 revised): dormant until the first real heartbeat lands.
    triggered = []
    monkeypatch.setattr(hw, "trigger_graceful_shutdown", lambda reason: triggered.append(reason))
    await hw._check_heartbeat()
    assert triggered == []


@pytest.mark.asyncio
async def test_register_heartbeat_watchdog_schedules_check_without_seeding(monkeypatch):
    # D4 revised: registration no longer treats "now" as a free grace period -- that assumed
    # the sidecar and its heartbeat sender start together, which dev mode's sequenced launcher
    # (backend first, `tauri dev`'s cargo build may take a while) doesn't guarantee.
    _reset()
    s = EventScheduler()
    hw.register_heartbeat_watchdog(s)
    assert hw._last_heartbeat is None  # dormant until a real /api/heartbeat POST arrives
    s.start()
    try:
        assert any(ev.name == "heartbeat_watchdog" for ev in s._heap)
    finally:
        await s.stop()


@pytest.mark.asyncio
async def test_register_heartbeat_watchdog_arms_after_first_recorded_heartbeat(monkeypatch):
    _reset()
    s = EventScheduler()
    hw.register_heartbeat_watchdog(s)
    hw.record_heartbeat()
    assert hw._last_heartbeat is not None
    s.start()
    try:
        assert any(ev.name == "heartbeat_watchdog" for ev in s._heap)
    finally:
        await s.stop()
