from fastapi.testclient import TestClient


def app_under_test():
    from api.hub import app
    return app


def test_service_status_endpoint_returns_backend_state(monkeypatch):
    from api.services import service_ping_status as sps

    sps._state["llm"] = {"status": "ok", "error": None}
    sps._state["search"] = {"status": "disabled", "error": None}
    client = TestClient(app_under_test())
    r = client.get("/api/health/service-status")
    assert r.status_code == 200
    assert r.json() == {
        "llm": {"status": "ok", "error": None},
        "search": {"status": "disabled", "error": None},
    }


def test_put_config_triggers_save_pings(monkeypatch):
    calls: list[str] = []

    async def _fake_save_pings(cfg):
        calls.append("save_pings")

    monkeypatch.setattr("utils.config.save_config", lambda raw: {"saved": True, **raw})
    monkeypatch.setattr("api.services.service_ping_status.run_config_save_pings", _fake_save_pings)

    class _Hub:
        async def reset_setup_chat(self):
            return None

    monkeypatch.setattr("api.routes._hub_instance", lambda: _Hub())

    client = TestClient(app_under_test())
    r = client.put("/api/config", json={"config": {"api": {"tavily_api_key": "k"}}})
    assert r.status_code == 200
    assert calls == ["save_pings"]
