"""Connectivity checks for the novel-rail status icons (LLM + search provider)."""
import httpx
import pytest


def _fake_async_client(handler):
    class _FakeAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, timeout=None, headers=None):
            return handler(url, timeout=timeout, headers=headers)

    return _FakeAsyncClient


class _FakeResp:
    def __init__(self, status_code=200):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=self)  # type: ignore[arg-type]

    def json(self):
        return {"data": []}


@pytest.mark.asyncio
async def test_ping_llm_openai_compatible_catalog_entry_success(monkeypatch):
    from api.services.service_ping import ping_llm

    monkeypatch.setattr(
        "domain.model_catalog.catalog_entry",
        lambda mid: {"id": "deepseek-v4-flash", "provider": "openai_compatible", "base_url": "https://api.deepseek.com/v1"} if mid == "deepseek-v4-flash" else None,
    )
    seen_urls = []

    def handler(url, timeout=None, headers=None):
        seen_urls.append(url)
        return _FakeResp()

    monkeypatch.setattr("httpx.AsyncClient", _fake_async_client(handler))
    cfg = {
        "llm": {"cloud_model_id": "deepseek-v4-flash"},
        "api": {"model_api_keys": {"deepseek-v4-flash": "sk-x"}},
    }
    result = await ping_llm(cfg)
    assert result == {"ok": True, "error": None}
    assert seen_urls == ["https://api.deepseek.com/v1/models"]


@pytest.mark.asyncio
async def test_ping_llm_openai_compatible_connection_error(monkeypatch):
    from api.services.service_ping import ping_llm

    monkeypatch.setattr(
        "domain.model_catalog.catalog_entry",
        lambda mid: {"id": "deepseek-v4-flash", "provider": "openai_compatible", "base_url": "https://api.deepseek.com/v1"},
    )

    def handler(url, timeout=None, headers=None):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr("httpx.AsyncClient", _fake_async_client(handler))
    cfg = {"llm": {"cloud_model_id": "deepseek-v4-flash"}, "api": {"model_api_keys": {}}}
    result = await ping_llm(cfg)
    assert result["ok"] is False
    assert result["error"]


@pytest.mark.asyncio
async def test_ping_llm_custom_model_with_embedded_api_key(monkeypatch):
    from api.services.service_ping import ping_llm

    monkeypatch.setattr("domain.model_catalog.catalog_entry", lambda mid: None)
    seen = []

    def handler(url, timeout=None, headers=None):
        seen.append((url, headers))
        return _FakeResp()

    monkeypatch.setattr("httpx.AsyncClient", _fake_async_client(handler))
    cfg = {
        "llm": {
            "cloud_model_id": "custom-1",
            "custom_models": [{
                "id": "custom-1", "base_url": "https://proxy.example/v1",
                "provider": "openai_compatible", "api_key": "sk-custom",
            }],
        },
        "api": {"model_api_keys": {}},
    }
    result = await ping_llm(cfg)
    assert result == {"ok": True, "error": None}
    assert seen == [("https://proxy.example/v1/models", {"Authorization": "Bearer sk-custom"})]


@pytest.mark.asyncio
async def test_ping_llm_custom_model_falls_back_to_model_api_keys(monkeypatch):
    from api.services.service_ping import ping_llm

    monkeypatch.setattr("domain.model_catalog.catalog_entry", lambda mid: None)
    seen = []

    def handler(url, timeout=None, headers=None):
        seen.append((url, headers))
        return _FakeResp()

    monkeypatch.setattr("httpx.AsyncClient", _fake_async_client(handler))
    cfg = {
        "llm": {
            "cloud_model_id": "custom-1",
            "custom_models": [{
                "id": "custom-1", "base_url": "https://proxy.example/v1", "provider": "openai_compatible",
            }],
        },
        "api": {"model_api_keys": {"custom-1": "sk-fallback"}},
    }
    result = await ping_llm(cfg)
    assert result == {"ok": True, "error": None}
    assert seen == [("https://proxy.example/v1/models", {"Authorization": "Bearer sk-fallback"})]


@pytest.mark.asyncio
async def test_ping_llm_unresolvable_model_id_returns_error_without_network_call(monkeypatch):
    from api.services.service_ping import ping_llm

    monkeypatch.setattr("domain.model_catalog.catalog_entry", lambda mid: None)

    def handler(url, timeout=None, headers=None):
        raise AssertionError("should not call network for an unresolvable model id")

    monkeypatch.setattr("httpx.AsyncClient", _fake_async_client(handler))
    cfg = {"llm": {"cloud_model_id": "deleted-custom-model", "custom_models": []}, "api": {"model_api_keys": {}}}
    result = await ping_llm(cfg)
    assert result["ok"] is False
    assert result["error"]


@pytest.mark.asyncio
async def test_ping_llm_anthropic_missing_key_no_network_call(monkeypatch):
    from api.services.service_ping import ping_llm

    monkeypatch.setattr(
        "domain.model_catalog.catalog_entry",
        lambda mid: {"id": "claude-opus-4-7", "provider": "anthropic", "base_url": ""},
    )

    def handler(url, timeout=None, headers=None):
        raise AssertionError("should not call network when key is missing")

    monkeypatch.setattr("httpx.AsyncClient", _fake_async_client(handler))
    cfg = {"llm": {"cloud_model_id": "claude-opus-4-7"}, "api": {"model_api_keys": {}}}
    result = await ping_llm(cfg)
    assert result == {"ok": False, "error": "未配置 API key"}


@pytest.mark.asyncio
async def test_ping_llm_anthropic_success(monkeypatch):
    from api.services.service_ping import ping_llm

    monkeypatch.setattr(
        "domain.model_catalog.catalog_entry",
        lambda mid: {"id": "claude-opus-4-7", "provider": "anthropic", "base_url": ""},
    )
    seen = []

    def handler(url, timeout=None, headers=None):
        seen.append((url, headers))
        return _FakeResp()

    monkeypatch.setattr("httpx.AsyncClient", _fake_async_client(handler))
    cfg = {"llm": {"cloud_model_id": "claude-opus-4-7"}, "api": {"model_api_keys": {"claude-opus-4-7": "sk-ant-x"}}}
    result = await ping_llm(cfg)
    assert result == {"ok": True, "error": None}
    assert seen[0][0] == "https://api.anthropic.com/v1/models"
    assert seen[0][1]["x-api-key"] == "sk-ant-x"


@pytest.mark.asyncio
async def test_ping_llm_anthropic_http_error(monkeypatch):
    from api.services.service_ping import ping_llm

    monkeypatch.setattr(
        "domain.model_catalog.catalog_entry",
        lambda mid: {"id": "claude-opus-4-7", "provider": "anthropic", "base_url": ""},
    )

    def handler(url, timeout=None, headers=None):
        return _FakeResp(status_code=401)

    monkeypatch.setattr("httpx.AsyncClient", _fake_async_client(handler))
    cfg = {"llm": {"cloud_model_id": "claude-opus-4-7"}, "api": {"model_api_keys": {"claude-opus-4-7": "bad-key"}}}
    result = await ping_llm(cfg)
    assert result["ok"] is False
    assert result["error"]


@pytest.mark.asyncio
async def test_ping_search_missing_key_returns_error(monkeypatch):
    from api.services.service_ping import ping_search

    cfg = {"api": {"search_provider": "tavily"}}
    result = await ping_search(cfg)
    assert result["ok"] is False
    assert "Tavily" in result["error"]


@pytest.mark.asyncio
async def test_ping_search_success(monkeypatch):
    from api.services.service_ping import ping_search
    from domain.search_provider import SearchResult

    class _FakeProvider:
        async def search(self, topic):
            assert topic == "连通性检测"
            return SearchResult(answer="ok", hits=[])

    monkeypatch.setattr(
        "domain.search_provider.build_search_provider", lambda cfg: _FakeProvider(),
    )
    result = await ping_search({"api": {"tavily_api_key": "k"}})
    assert result == {"ok": True, "error": None}


@pytest.mark.asyncio
async def test_ping_search_provider_raises(monkeypatch):
    from api.services.service_ping import ping_search

    class _FakeProvider:
        async def search(self, topic):
            raise RuntimeError("超时")

    monkeypatch.setattr(
        "domain.search_provider.build_search_provider", lambda cfg: _FakeProvider(),
    )
    result = await ping_search({"api": {"tavily_api_key": "k"}})
    assert result["ok"] is False
    assert "超时" in result["error"]
