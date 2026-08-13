from __future__ import annotations

import httpx
import pytest


def _page_response(url, models, next_cursor=None):
    body = {"models": models}
    if next_cursor:
        body["pagination"] = {"next_cursor": next_cursor}
    return httpx.Response(200, json=body, request=httpx.Request("GET", url))


@pytest.mark.asyncio
async def test_refresh_paginates_until_cursor_exhausted(monkeypatch):
    from domain import novita_model_catalog as nmc

    pages = [
        [{"sd_name": "a.safetensors"}, {"sd_name": "b.safetensors"}],
        [{"sd_name": "c.safetensors"}],
    ]
    calls = []

    async def fake_get(self, url, *, headers, params):
        calls.append(dict(params))
        if len(calls) == 1:
            return _page_response(url, pages[0], next_cursor="c_20")
        return _page_response(url, pages[1])

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    result = await nmc.refresh_novita_model_catalog("test-key")

    assert result == ["a.safetensors", "b.safetensors", "c.safetensors"]
    assert calls[0]["filter.types"] == "checkpoint"
    assert "pagination.cursor" not in calls[0]
    assert calls[1]["pagination.cursor"] == "c_20"


@pytest.mark.asyncio
async def test_get_cached_models_reflects_last_refresh(monkeypatch):
    from domain import novita_model_catalog as nmc

    async def fake_get(self, url, *, headers, params):
        return _page_response(url, [{"sd_name": "x.safetensors"}])

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    await nmc.refresh_novita_model_catalog("test-key")

    assert nmc.get_cached_novita_models() == ["x.safetensors"]
    # read-only: no network call
    monkeypatch.setattr(
        httpx.AsyncClient, "get",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not call network")),
    )
    assert nmc.get_cached_novita_models() == ["x.safetensors"]


@pytest.mark.asyncio
async def test_refresh_raises_on_http_error(monkeypatch):
    from domain import novita_model_catalog as nmc

    async def fake_get(self, url, *, headers, params):
        return httpx.Response(401, json={"error": "unauthorized"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    with pytest.raises(httpx.HTTPStatusError):
        await nmc.refresh_novita_model_catalog("bad-key")


@pytest.mark.asyncio
async def test_refresh_stops_on_empty_page_even_if_cursor_present(monkeypatch):
    """Regression: Novita's API keeps returning a non-empty next_cursor past the real end
    of data, paired with an empty `models` list -- treating cursor-presence as the sole
    stop condition spins forever. An empty page must stop pagination regardless of what
    next_cursor claims (reproduced live against a real account 2026-08-10: real data ends
    at page 11/1084 models, but next_cursor keeps incrementing indefinitely afterward)."""
    from domain import novita_model_catalog as nmc

    calls = []

    async def fake_get(self, url, *, headers, params):
        calls.append(dict(params))
        if len(calls) == 1:
            return _page_response(url, [{"sd_name": "a.safetensors"}], next_cursor="c_100")
        # Novita quirk: still claims a next_cursor, but no more real data
        return _page_response(url, [], next_cursor="c_200")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    result = await nmc.refresh_novita_model_catalog("test-key")

    assert result == ["a.safetensors"]
    assert len(calls) == 2  # must not keep looping past the empty page


@pytest.mark.asyncio
async def test_refresh_skips_entries_without_sd_name(monkeypatch):
    from domain import novita_model_catalog as nmc

    async def fake_get(self, url, *, headers, params):
        return _page_response(url, [{"sd_name": "keep.safetensors"}, {"id": 1}, {"sd_name": None}])

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    result = await nmc.refresh_novita_model_catalog("test-key")

    assert result == ["keep.safetensors"]


@pytest.mark.asyncio
async def test_refresh_populates_base_model_cache(monkeypatch):
    from domain import novita_model_catalog as nmc

    async def fake_get(self, url, *, headers, params):
        return _page_response(
            url,
            [
                {"sd_name": "pony-v6.safetensors", "base_model": "Pony"},
                {"sd_name": "no-base-model.safetensors"},
            ],
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    await nmc.refresh_novita_model_catalog("test-key")

    assert nmc.get_cached_base_models() == {"pony-v6.safetensors": "Pony"}


@pytest.mark.asyncio
async def test_get_cached_base_models_returns_a_copy(monkeypatch):
    from domain import novita_model_catalog as nmc

    async def fake_get(self, url, *, headers, params):
        return _page_response(url, [{"sd_name": "x.safetensors", "base_model": "SDXL 1.0"}])

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    await nmc.refresh_novita_model_catalog("test-key")

    snapshot = nmc.get_cached_base_models()
    snapshot["x.safetensors"] = "tampered"

    assert nmc.get_cached_base_models() == {"x.safetensors": "SDXL 1.0"}
