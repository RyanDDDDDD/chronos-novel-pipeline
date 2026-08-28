from api.services.message_hub import MessageHub
from fastapi.testclient import TestClient


def test_put_config_resets_cloud_llm_cache_and_setup_chat_agent(monkeypatch):
    """PUT /api/config bakes into both the cloud LLM singleton (llm.factory) and the
    setup-chat agent singleton (build_agent() captures get_cloud_llm() once at build
    time) -- saving a changed model/key must invalidate both, otherwise a running
    process keeps serving the stale client until something else (e.g. novel switch)
    happens to call reset_setup_chat() as a side effect."""
    import api.hub as hub_mod
    import llm.factory as factory
    import utils.config as config_mod
    from api.hub import app

    hub = MessageHub()
    hub._setup_chat_agents["default"] = object()
    monkeypatch.setattr(hub_mod, "HUB", hub)

    reset_setup_chat_calls = {"n": 0}

    async def fake_reset_setup_chat():
        reset_setup_chat_calls["n"] += 1

    monkeypatch.setattr(hub, "reset_setup_chat", fake_reset_setup_chat)

    reset_cloud_llm_calls = {"n": 0}

    def fake_reset_cloud_llm_cache():
        reset_cloud_llm_calls["n"] += 1

    monkeypatch.setattr(factory, "reset_cloud_llm_cache", fake_reset_cloud_llm_cache)
    monkeypatch.setattr(config_mod, "save_config", lambda raw: {"llm": {}, "api": {}})

    client = TestClient(app)
    r = client.put("/api/config", json={"config": {"llm": {}, "api": {}}})

    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert reset_cloud_llm_calls["n"] == 1
    assert reset_setup_chat_calls["n"] == 1


async def _noop_coro():
    return None


def test_put_config_schedules_novita_refresh_when_image_gen_key_changes(monkeypatch):
    import api.hub as hub_mod
    import api.services.service_ping_status as ping_mod
    import llm.factory as factory
    import utils.config as config_mod
    from api.hub import app
    from api.services.scheduler import SCHEDULER

    hub = MessageHub()
    monkeypatch.setattr(hub_mod, "HUB", hub)
    monkeypatch.setattr(hub, "reset_setup_chat", lambda: _noop_coro())
    monkeypatch.setattr(factory, "reset_cloud_llm_cache", lambda: None)
    monkeypatch.setattr(ping_mod, "run_config_save_pings", lambda cfg: _noop_coro())

    monkeypatch.setattr(
        config_mod, "get_config",
        lambda: {"llm": {"custom_models": [
            {"id": "img-1", "provider": "image_gen", "api_key": "old-key"},
        ]}},
    )
    new_cfg = {"llm": {"custom_models": [
        {"id": "img-1", "provider": "image_gen", "api_key": "new-key"},
    ]}, "api": {}}
    monkeypatch.setattr(config_mod, "save_config", lambda raw: new_cfg)

    scheduled = []
    monkeypatch.setattr(
        SCHEDULER, "schedule_once",
        lambda name, delay_s, coro, **kw: scheduled.append((name, kw.get("dedup", False))),
    )

    client = TestClient(app)
    r = client.put("/api/config", json={"config": {"llm": {}, "api": {}}})

    assert r.status_code == 200
    assert scheduled == [("novita_model_catalog_refresh", True)]


def test_put_config_skips_novita_refresh_when_image_gen_key_unchanged(monkeypatch):
    import api.hub as hub_mod
    import api.services.service_ping_status as ping_mod
    import llm.factory as factory
    import utils.config as config_mod
    from api.hub import app
    from api.services.scheduler import SCHEDULER

    hub = MessageHub()
    monkeypatch.setattr(hub_mod, "HUB", hub)
    monkeypatch.setattr(hub, "reset_setup_chat", lambda: _noop_coro())
    monkeypatch.setattr(factory, "reset_cloud_llm_cache", lambda: None)
    monkeypatch.setattr(ping_mod, "run_config_save_pings", lambda cfg: _noop_coro())

    same_cfg = {"llm": {"custom_models": [
        {"id": "img-1", "provider": "image_gen", "api_key": "same-key"},
    ]}, "api": {}}
    monkeypatch.setattr(config_mod, "get_config", lambda: same_cfg)
    monkeypatch.setattr(config_mod, "save_config", lambda raw: same_cfg)

    scheduled = []
    monkeypatch.setattr(
        SCHEDULER, "schedule_once",
        lambda name, delay_s, coro, **kw: scheduled.append(name),
    )

    client = TestClient(app)
    r = client.put("/api/config", json={"config": {"llm": {}, "api": {}}})

    assert r.status_code == 200
    assert "novita_model_catalog_refresh" not in scheduled


def test_put_config_skips_novita_refresh_for_novelai_image_gen_entry(monkeypatch):
    """Saving a new `service="novelai"` image_gen entry must not schedule a Novita catalog
    refresh -- NovelAI has no equivalent catalog to pull."""
    import api.hub as hub_mod
    import api.services.service_ping_status as ping_mod
    import llm.factory as factory
    import utils.config as config_mod
    from api.hub import app
    from api.services.scheduler import SCHEDULER

    hub = MessageHub()
    monkeypatch.setattr(hub_mod, "HUB", hub)
    monkeypatch.setattr(hub, "reset_setup_chat", lambda: _noop_coro())
    monkeypatch.setattr(factory, "reset_cloud_llm_cache", lambda: None)
    monkeypatch.setattr(ping_mod, "run_config_save_pings", lambda cfg: _noop_coro())

    monkeypatch.setattr(config_mod, "get_config", lambda: {"llm": {"custom_models": []}})
    new_cfg = {"llm": {"custom_models": [
        {"id": "img-1", "provider": "image_gen", "api_key": "novelai-key", "service": "novelai"},
    ]}, "api": {}}
    monkeypatch.setattr(config_mod, "save_config", lambda raw: new_cfg)

    scheduled = []
    monkeypatch.setattr(
        SCHEDULER, "schedule_once",
        lambda name, delay_s, coro, **kw: scheduled.append(name),
    )

    client = TestClient(app)
    r = client.put("/api/config", json={"config": {"llm": {}, "api": {}}})

    assert r.status_code == 200
    assert "novita_model_catalog_refresh" not in scheduled


def test_put_config_schedules_novita_refresh_for_explicit_novita_entry(monkeypatch):
    """An explicit `service="novita"` entry with a changed key keeps scheduling the
    refresh, same as a legacy entry with no `service` field."""
    import api.hub as hub_mod
    import api.services.service_ping_status as ping_mod
    import llm.factory as factory
    import utils.config as config_mod
    from api.hub import app
    from api.services.scheduler import SCHEDULER

    hub = MessageHub()
    monkeypatch.setattr(hub_mod, "HUB", hub)
    monkeypatch.setattr(hub, "reset_setup_chat", lambda: _noop_coro())
    monkeypatch.setattr(factory, "reset_cloud_llm_cache", lambda: None)
    monkeypatch.setattr(ping_mod, "run_config_save_pings", lambda cfg: _noop_coro())

    monkeypatch.setattr(
        config_mod, "get_config",
        lambda: {"llm": {"custom_models": [
            {"id": "img-1", "provider": "image_gen", "api_key": "old-key", "service": "novita"},
        ]}},
    )
    new_cfg = {"llm": {"custom_models": [
        {"id": "img-1", "provider": "image_gen", "api_key": "new-key", "service": "novita"},
    ]}, "api": {}}
    monkeypatch.setattr(config_mod, "save_config", lambda raw: new_cfg)

    scheduled = []
    monkeypatch.setattr(
        SCHEDULER, "schedule_once",
        lambda name, delay_s, coro, **kw: scheduled.append((name, kw.get("dedup", False))),
    )

    client = TestClient(app)
    r = client.put("/api/config", json={"config": {"llm": {}, "api": {}}})

    assert r.status_code == 200
    assert scheduled == [("novita_model_catalog_refresh", True)]
