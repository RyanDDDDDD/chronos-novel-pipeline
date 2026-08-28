import asyncio

import pytest
from api.hub import register_startup_warmup
from api.services.scheduler import EventScheduler


class _FakeHub:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def _ensure_setup_chat_agent(self, novel_id: str):
        self.calls.append("setup_chat_agent")

    async def _ensure_story_sandbox_checkpointer(self) -> None:
        self.calls.append("story_sandbox_checkpointer")


@pytest.mark.asyncio
async def test_register_startup_warmup_runs_both_jobs():
    s = EventScheduler()
    hub = _FakeHub()
    register_startup_warmup(s, hub)
    s.start()
    await asyncio.sleep(0.05)  # let the scheduler's background dispatch loop actually fire the once-jobs
    await s.stop()
    assert set(hub.calls) == {"setup_chat_agent", "story_sandbox_checkpointer"}


@pytest.mark.asyncio
async def test_register_startup_warmup_schedules_trash_purge():
    s = EventScheduler()
    hub = _FakeHub()
    register_startup_warmup(s, hub)
    names = {ev.name for ev in s._heap if ev.kind == "once"}  # noqa: SLF001 - startup wiring test
    assert "trash_purge" in names


@pytest.mark.asyncio
async def test_register_startup_warmup_pulls_novita_catalog_when_key_configured(monkeypatch):
    import domain.model_catalog as model_catalog_mod
    import domain.novita_model_catalog as nmc_mod

    monkeypatch.setattr(
        model_catalog_mod, "load_custom_models",
        lambda: [{"id": "img-1", "provider": "image_gen", "api_key": "sk-real"}],
    )
    refresh_calls = []

    async def fake_refresh(api_key):
        refresh_calls.append(api_key)
        return []

    monkeypatch.setattr(nmc_mod, "refresh_novita_model_catalog", fake_refresh)

    s = EventScheduler()
    hub = _FakeHub()
    register_startup_warmup(s, hub)
    s.start()
    await asyncio.sleep(0.05)
    await s.stop()

    assert refresh_calls == ["sk-real"]


@pytest.mark.asyncio
async def test_register_startup_warmup_skips_novita_pull_without_key(monkeypatch):
    import domain.model_catalog as model_catalog_mod
    import domain.novita_model_catalog as nmc_mod

    monkeypatch.setattr(model_catalog_mod, "load_custom_models", lambda: [])
    refresh_calls = []

    async def fake_refresh(api_key):
        refresh_calls.append(api_key)
        return []

    monkeypatch.setattr(nmc_mod, "refresh_novita_model_catalog", fake_refresh)

    s = EventScheduler()
    hub = _FakeHub()
    register_startup_warmup(s, hub)
    s.start()
    await asyncio.sleep(0.05)
    await s.stop()

    assert refresh_calls == []


@pytest.mark.asyncio
async def test_register_startup_warmup_skips_novita_pull_for_novelai_entry(monkeypatch):
    """A NovelAI image_gen entry must not trigger the Novita catalog pull -- NovelAI has
    no equivalent catalog to warm."""
    import domain.model_catalog as model_catalog_mod
    import domain.novita_model_catalog as nmc_mod

    monkeypatch.setattr(
        model_catalog_mod, "load_custom_models",
        lambda: [{"id": "img-1", "provider": "image_gen", "api_key": "sk-real", "service": "novelai"}],
    )
    refresh_calls = []

    async def fake_refresh(api_key):
        refresh_calls.append(api_key)
        return []

    monkeypatch.setattr(nmc_mod, "refresh_novita_model_catalog", fake_refresh)

    s = EventScheduler()
    hub = _FakeHub()
    register_startup_warmup(s, hub)
    s.start()
    await asyncio.sleep(0.05)
    await s.stop()

    assert refresh_calls == []


@pytest.mark.asyncio
async def test_register_startup_warmup_pulls_novita_catalog_for_explicit_novita_entry(monkeypatch):
    """An explicit service="novita" entry keeps triggering the warm-up pull, same as a
    legacy entry with no `service` field."""
    import domain.model_catalog as model_catalog_mod
    import domain.novita_model_catalog as nmc_mod

    monkeypatch.setattr(
        model_catalog_mod, "load_custom_models",
        lambda: [{"id": "img-1", "provider": "image_gen", "api_key": "sk-real", "service": "novita"}],
    )
    refresh_calls = []

    async def fake_refresh(api_key):
        refresh_calls.append(api_key)
        return []

    monkeypatch.setattr(nmc_mod, "refresh_novita_model_catalog", fake_refresh)

    s = EventScheduler()
    hub = _FakeHub()
    register_startup_warmup(s, hub)
    s.start()
    await asyncio.sleep(0.05)
    await s.stop()

    assert refresh_calls == ["sk-real"]
