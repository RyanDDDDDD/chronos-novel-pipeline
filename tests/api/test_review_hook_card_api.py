"""API: review hook markdown card read-only endpoint."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def review_hook_api_client(monkeypatch):
    import utils.config as config_mod

    _fake_cfg = {"llm": {}, "api": {}, "server": {}, "paths": {}}
    _cache = config_mod.LazyCache(lambda: _fake_cfg)
    _cache.get()
    monkeypatch.setattr(config_mod, "_config_cache", _cache)
    import api.hub as hub
    from api.services.message_hub import MessageHub

    hub.HUB = MessageHub()
    return TestClient(hub.app)


def test_get_review_hook_card_known_hook(review_hook_api_client):
    r = review_hook_api_client.get("/api/author-loop/review-hooks/style")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["content"], str)
    assert len(body["content"]) > 0


def test_get_review_hook_card_code_only_hook(review_hook_api_client):
    r = review_hook_api_client.get("/api/author-loop/review-hooks/expansion_ratio")
    assert r.status_code == 200
    assert r.json()["content"] is None


def test_get_review_hook_card_unknown_hook(review_hook_api_client):
    r = review_hook_api_client.get("/api/author-loop/review-hooks/no-such-hook")
    assert r.status_code == 404
    assert r.json()["ok"] is False
