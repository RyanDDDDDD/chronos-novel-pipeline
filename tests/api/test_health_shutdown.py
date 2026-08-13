import asyncio
import signal

from fastapi.testclient import TestClient


def _app():
    from api.hub import app

    return app


def test_health_endpoint_returns_ok():
    client = TestClient(_app())
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_shutdown_endpoint_raises_sigterm(monkeypatch):
    calls = []
    monkeypatch.setattr(signal, "raise_signal", lambda sig: calls.append(sig))
    client = TestClient(_app())
    res = client.post("/api/shutdown")
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert calls == [signal.SIGTERM]


def test_heartbeat_endpoint_records_heartbeat(monkeypatch):
    from api.services import heartbeat_watchdog as hw

    calls = []
    monkeypatch.setattr(hw, "record_heartbeat", lambda: calls.append(1))
    client = TestClient(_app())
    res = client.post("/api/heartbeat")
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert calls == [1]


def test_health_endpoint_responds_immediately_even_if_warmup_hangs(monkeypatch):
    from api.hub import HUB

    async def hanging_agent_build(self, novel_id: str):
        await asyncio.sleep(3600)

    async def hanging_checkpointer_build(self):
        await asyncio.sleep(3600)

    monkeypatch.setattr(type(HUB), "_ensure_setup_chat_agent", hanging_agent_build)
    monkeypatch.setattr(type(HUB), "_ensure_story_sandbox_checkpointer", hanging_checkpointer_build)

    with TestClient(_app()) as client:
        res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"ok": True}
