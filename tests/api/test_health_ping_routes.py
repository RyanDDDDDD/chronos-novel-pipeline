from fastapi.testclient import TestClient


def app_under_test():
    from api.hub import app
    return app


def test_ping_llm_endpoint_returns_service_ping_result(monkeypatch):
    async def _fake_run_ping_llm(cfg):
        assert cfg == {"fake": True}
        return {"ok": True, "error": None}

    monkeypatch.setattr("utils.config.get_config", lambda: {"fake": True})
    monkeypatch.setattr("api.services.service_ping_status.run_ping_llm", _fake_run_ping_llm)
    client = TestClient(app_under_test())
    r = client.post("/api/health/ping-llm")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "error": None}


def test_ping_search_endpoint_returns_service_ping_result(monkeypatch):
    async def _fake_run_ping_search(cfg):
        return {"ok": False, "error": "未配置百度千帆 key"}

    monkeypatch.setattr("utils.config.get_config", lambda: {})
    monkeypatch.setattr("api.services.service_ping_status.run_ping_search", _fake_run_ping_search)
    client = TestClient(app_under_test())
    r = client.post("/api/health/ping-search")
    assert r.status_code == 200
    assert r.json() == {"ok": False, "error": "未配置百度千帆 key"}
