import api.services.token_accountant as ta
import pytest


@pytest.fixture(autouse=True)
def _stub_ledger(monkeypatch):
    store = {}

    def reset_cell(subsystem, key, *, novel_id=None):
        store[(subsystem, key)] = {"tokens_in": 0, "tokens_out": 0, "tokens_cached": 0}

    def add_to_cell(subsystem, key, tin, tout, tc, model, *, novel_id=None):
        c = store.setdefault((subsystem, key), {"tokens_in": 0, "tokens_out": 0, "tokens_cached": 0})
        c["tokens_in"] += tin
        c["tokens_out"] += tout
        c["tokens_cached"] += tc
        return dict(c)

    monkeypatch.setattr(ta, "reset_cell", reset_cell)
    monkeypatch.setattr(ta, "add_to_cell", add_to_cell)
    return store


@pytest.mark.asyncio
async def test_record_accumulates_and_persists(_stub_ledger):
    acc = ta.TokenAccountant(novel_id="default", subsystem="author_loop", key="6", model="m")
    acc.begin()
    await acc.record(100, 40, 30)
    await acc.record(50, 20, 10)
    assert _stub_ledger[("author_loop", "6")]["tokens_in"] == 150


@pytest.mark.asyncio
async def test_record_exception_swallowed(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(ta, "add_to_cell", boom)
    monkeypatch.setattr(ta, "reset_cell", lambda *a, **k: None)
    acc = ta.TokenAccountant(novel_id="default", subsystem="author_loop", key="6", model="m")
    await acc.record(1, 1)


@pytest.mark.asyncio
async def test_record_model_override_used_for_ledger(monkeypatch):
    seen_models = []

    def add_to_cell(subsystem, key, tin, tout, tc, model, *, novel_id=None):
        seen_models.append(model)
        return {"tokens_in": tin, "tokens_out": tout, "tokens_cached": tc}

    monkeypatch.setattr(ta, "reset_cell", lambda *a, **k: None)
    monkeypatch.setattr(ta, "add_to_cell", add_to_cell)

    acc = ta.TokenAccountant(
        novel_id="default", subsystem="story_sandbox", key="6", model="cloud-model",
    )
    acc.begin()
    await acc.record(10, 5, model="local-model")

    assert seen_models == ["local-model"]


@pytest.mark.asyncio
async def test_record_without_override_uses_constructor_model(monkeypatch):
    seen_models = []

    def add_to_cell(subsystem, key, tin, tout, tc, model, *, novel_id=None):
        seen_models.append(model)
        return {"tokens_in": tin, "tokens_out": tout, "tokens_cached": tc}

    monkeypatch.setattr(ta, "reset_cell", lambda *a, **k: None)
    monkeypatch.setattr(ta, "add_to_cell", add_to_cell)

    acc = ta.TokenAccountant(novel_id="default", subsystem="story_sandbox", key="6", model="cloud-model")
    acc.begin()
    await acc.record(10, 5)

    assert seen_models == ["cloud-model"]
