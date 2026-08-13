import pytest


@pytest.mark.asyncio
async def test_run_startup_pings_llm_always_search_gated(monkeypatch):
    from api.services import service_ping_status as sps

    calls: list[str] = []

    async def _fake_llm(cfg):
        calls.append("llm")
        return {"ok": True, "error": None}

    async def _fake_search(cfg):
        calls.append("search")
        return {"ok": True, "error": None}

    monkeypatch.setattr("api.services.service_ping.ping_llm", _fake_llm)
    monkeypatch.setattr("api.services.service_ping.ping_search", _fake_search)
    sps._state["llm"] = {"status": "unknown", "error": None}
    sps._state["search"] = {"status": "unknown", "error": None}

    await sps.run_startup_pings({"api": {"search_ping_enabled": False}})
    assert calls == ["llm"]
    assert sps.get_service_status()["llm"]["status"] == "ok"
    assert sps.get_service_status()["search"]["status"] == "disabled"

    await sps.run_startup_pings({"api": {"search_ping_enabled": True}})
    assert calls == ["llm", "llm", "search"]
    assert sps.get_service_status()["search"]["status"] == "ok"


@pytest.mark.asyncio
async def test_run_config_save_pings_always_both(monkeypatch):
    from api.services import service_ping_status as sps

    calls: list[str] = []

    async def _fake_llm(cfg):
        calls.append("llm")
        return {"ok": False, "error": "bad key"}

    async def _fake_search(cfg):
        calls.append("search")
        return {"ok": True, "error": None}

    monkeypatch.setattr("api.services.service_ping.ping_llm", _fake_llm)
    monkeypatch.setattr("api.services.service_ping.ping_search", _fake_search)

    await sps.run_config_save_pings({"api": {"search_ping_enabled": False}})
    assert calls == ["llm", "search"]
    status = sps.get_service_status()
    assert status["llm"] == {"status": "error", "error": "bad key"}
    assert status["search"] == {"status": "ok", "error": None}
