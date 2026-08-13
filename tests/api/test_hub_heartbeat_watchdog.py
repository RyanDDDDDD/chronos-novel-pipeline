import pytest
from api.services import heartbeat_watchdog as hw
from api.services.scheduler import SCHEDULER
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_last_heartbeat():
    # D4 revised: the watchdog always registers now (no CHRONOS_ROOT gate). A real
    # _last_heartbeat value leaking past this module would arm every later test file's
    # TestClient(app) too, and once it's stale enough that periodic check fires a REAL
    # SIGTERM (trigger_graceful_shutdown), silently killing the whole pytest run.
    hw._last_heartbeat = None
    yield
    hw._last_heartbeat = None


@pytest.mark.asyncio
async def test_lifespan_registers_heartbeat_watchdog_dormant_regardless_of_launch_mode():
    # D4 revised: the watchdog always registers during _lifespan startup -- release sidecar
    # and dev (`tauri dev` debug build via the sequenced launcher) both eventually send
    # heartbeats now, so there's no more CHRONOS_ROOT gate to distinguish them. It stays
    # dormant (_last_heartbeat None) until a real /api/heartbeat POST lands.
    hw._last_heartbeat = None
    from api.hub import app
    from engine.story_sandbox import graph as sandbox_graph

    with TestClient(app):
        assert hw._last_heartbeat is None  # not seeded -- dormant until first real heartbeat
        assert any(ev.name == "heartbeat_watchdog" for ev in SCHEDULER._heap)

    # Lifespan schedules fire-and-forget checkpointer warm-up; exiting TestClient can
    # cancel that task mid-flight and leave CancelledError on `_checkpointer_building`,
    # which would poison later story-sandbox tests in the same process.
    sandbox_graph._checkpointer_building = None
    await sandbox_graph.close_checkpointer()


@pytest.mark.asyncio
async def test_heartbeat_endpoint_arms_the_watchdog():
    hw._last_heartbeat = None
    from api.hub import app
    from engine.story_sandbox import graph as sandbox_graph

    with TestClient(app) as client:
        resp = client.post("/api/heartbeat")
        assert resp.status_code == 200
        assert hw._last_heartbeat is not None

    sandbox_graph._checkpointer_building = None
    await sandbox_graph.close_checkpointer()
