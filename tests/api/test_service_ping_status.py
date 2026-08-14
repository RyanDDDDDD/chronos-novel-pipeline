import pytest


@pytest.mark.asyncio
async def test_run_startup_pings_checks_both_via_free_search(monkeypatch):
    from api.services import service_ping_status as sps

    calls: list[str] = []

    async def _fake_llm(cfg):
        calls.append("llm")
        return {"ok": True, "error": None}

    async def _fake_search_free(cfg):
        calls.append("search_free")
        return {"ok": True, "error": None}

    monkeypatch.setattr("api.services.service_ping.ping_llm", _fake_llm)
    monkeypatch.setattr("api.services.service_ping.ping_search_free", _fake_search_free)
    sps._state["llm"] = {"status": "unknown", "error": None}
    sps._state["search"] = {"status": "unknown", "error": None}

    await sps.run_startup_pings({})
    assert calls == ["llm", "search_free"]
    assert sps.get_service_status()["llm"]["status"] == "ok"
    assert sps.get_service_status()["search"]["status"] == "ok"


@pytest.mark.asyncio
async def test_run_startup_pings_search_free_none_reports_disabled(monkeypatch):
    """ping_search_free returning None (no free endpoint for the configured
    provider, e.g. baidu_qianfan) must render as "disabled", not a false "ok"
    and not a real quota-spending fallback."""
    from api.services import service_ping_status as sps

    async def _fake_llm(cfg):
        return {"ok": True, "error": None}

    async def _fake_search_free(cfg):
        return None

    monkeypatch.setattr("api.services.service_ping.ping_llm", _fake_llm)
    monkeypatch.setattr("api.services.service_ping.ping_search_free", _fake_search_free)

    await sps.run_startup_pings({})
    status = sps.get_service_status()["search"]
    assert status["status"] == "disabled"
    assert status["error"]


@pytest.mark.asyncio
async def test_run_config_save_pings_always_both_via_free_search(monkeypatch):
    from api.services import service_ping_status as sps

    calls: list[str] = []

    async def _fake_llm(cfg):
        calls.append("llm")
        return {"ok": False, "error": "bad key"}

    async def _fake_search_free(cfg):
        calls.append("search_free")
        return {"ok": True, "error": None}

    monkeypatch.setattr("api.services.service_ping.ping_llm", _fake_llm)
    monkeypatch.setattr("api.services.service_ping.ping_search_free", _fake_search_free)

    await sps.run_config_save_pings({})
    assert calls == ["llm", "search_free"]
    status = sps.get_service_status()
    assert status["llm"] == {"status": "error", "error": "bad key"}
    assert status["search"] == {"status": "ok", "error": None}
