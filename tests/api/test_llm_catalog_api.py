import httpx
from fastapi.testclient import TestClient


def app_under_test():
    from api.hub import app
    return app


def test_get_llm_catalog(monkeypatch):
    monkeypatch.setattr(
        "domain.model_catalog.load_model_catalog",
        lambda: [{"id": "claude-opus-4-7", "label": "Claude Opus 4.7", "provider": "anthropic"}],
    )
    client = TestClient(app_under_test())
    r = client.get("/api/llm/catalog")
    assert r.status_code == 200
    body = r.json()
    assert body["cloud_models"][0]["id"] == "claude-opus-4-7"


def test_get_llm_catalog_excludes_image_gen_entries(monkeypatch):
    monkeypatch.setattr("domain.model_catalog.load_model_catalog", lambda: [])
    monkeypatch.setattr(
        "domain.model_catalog.load_custom_models",
        lambda: [
            {"id": "text-1", "label": "文本模型", "provider": "openai_compatible",
             "base_url": "https://x.example.com/v1", "model": "m1", "api_key": "k1"},
            {"id": "img-1", "label": "生图模型", "provider": "image_gen",
             "base_url": "", "model": "flux-1", "api_key": "k2"},
        ],
    )
    client = TestClient(app_under_test())
    r = client.get("/api/llm/catalog")
    ids = [m["id"] for m in r.json()["custom_models"]]
    assert ids == ["text-1"]


def test_get_llm_catalog_includes_custom_models_without_api_key(monkeypatch):
    monkeypatch.setattr("domain.model_catalog.load_model_catalog", lambda: [])
    monkeypatch.setattr(
        "domain.model_catalog.load_custom_models",
        lambda: [{
            "id": "custom-1", "label": "我的模型", "provider": "openai_compatible",
            "base_url": "https://x.example.com/v1", "model": "m1",
            "api_key": "sk-should-not-leak", "client_kwargs": {"foo": "bar"},
        }],
    )
    client = TestClient(app_under_test())
    r = client.get("/api/llm/catalog")
    assert r.status_code == 200
    body = r.json()
    assert body["custom_models"] == [{
        "id": "custom-1", "label": "我的模型", "provider": "openai_compatible",
        "base_url": "https://x.example.com/v1", "model": "m1",
    }]
    assert "sk-should-not-leak" not in r.text


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


def test_get_local_models_success_uses_configured_base_url(monkeypatch):
    monkeypatch.setattr(
        "utils.config.get_config",
        lambda: {"llm": {"local_base_url": "http://localhost:1234/v1"}},
    )

    class _FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"id": "qwen2.5-32b-instruct"}, {"id": "deepseek-r1-distill"}]}

    seen_urls = []

    def handler(url, timeout=None, headers=None):
        seen_urls.append(url)
        return _FakeResp()

    monkeypatch.setattr("httpx.AsyncClient", _fake_async_client(handler))
    client = TestClient(app_under_test())
    r = client.get("/api/llm/local-models")
    assert r.status_code == 200
    assert r.json()["models"] == ["qwen2.5-32b-instruct", "deepseek-r1-distill"]
    assert seen_urls == ["http://localhost:1234/v1/models"]


def test_get_local_models_uses_query_override_instead_of_config(monkeypatch):
    monkeypatch.setattr(
        "utils.config.get_config",
        lambda: {"llm": {"local_base_url": "http://localhost:1234/v1"}},
    )

    class _FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"id": "draft-model"}]}

    seen_urls = []

    def handler(url, timeout=None, headers=None):
        seen_urls.append(url)
        return _FakeResp()

    monkeypatch.setattr("httpx.AsyncClient", _fake_async_client(handler))
    client = TestClient(app_under_test())
    r = client.get("/api/llm/local-models", params={"base_url": "http://localhost:9999/v1"})
    assert r.status_code == 200
    assert r.json()["models"] == ["draft-model"]
    assert seen_urls == ["http://localhost:9999/v1/models"]


def test_get_local_models_connection_error(monkeypatch):
    monkeypatch.setattr(
        "utils.config.get_config",
        lambda: {"llm": {"local_base_url": "http://localhost:1234/v1"}},
    )

    def handler(url, timeout=None, headers=None):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr("httpx.AsyncClient", _fake_async_client(handler))
    client = TestClient(app_under_test())
    r = client.get("/api/llm/local-models")
    assert r.status_code == 200
    body = r.json()
    assert body["models"] == []
    assert "error" in body


def test_post_compatible_models_success_sends_bearer_and_normalizes_url(monkeypatch):
    class _FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]}

    seen: list[tuple[str, dict | None]] = []

    def handler(url, timeout=None, headers=None):
        seen.append((url, headers))
        return _FakeResp()

    monkeypatch.setattr("httpx.AsyncClient", _fake_async_client(handler))
    client = TestClient(app_under_test())
    r = client.post(
        "/api/llm/compatible-models",
        json={"base_url": "https://proxy.example.com/v1/", "api_key": "sk-test"},
    )
    assert r.status_code == 200
    assert r.json()["models"] == ["gpt-4o", "gpt-4o-mini"]
    assert seen == [
        ("https://proxy.example.com/v1/models", {"Authorization": "Bearer sk-test"}),
    ]


def test_post_compatible_models_empty_base_url():
    client = TestClient(app_under_test())
    r = client.post("/api/llm/compatible-models", json={"base_url": "  "})
    assert r.status_code == 200
    body = r.json()
    assert body["models"] == []
    assert "base_url" in body["error"]
