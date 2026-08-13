from fastapi.testclient import TestClient


def app_under_test():
    from api.hub import app
    return app


def test_get_image_gen_catalog_only_returns_image_gen_entries(monkeypatch):
    monkeypatch.setattr(
        "domain.model_catalog.load_custom_models",
        lambda: [
            {"id": "text-1", "label": "文本模型", "provider": "openai_compatible",
             "base_url": "https://x.example.com/v1", "model": "m1", "api_key": "k1"},
            {"id": "img-1", "label": "生图模型", "provider": "image_gen",
             "base_url": "", "model": "flux-1", "api_key": "sk-should-not-leak"},
        ],
    )
    client = TestClient(app_under_test())
    r = client.get("/api/image-gen/catalog")
    assert r.status_code == 200
    assert r.json()["custom_models"] == [{"id": "img-1", "label": "生图模型", "model": "flux-1"}]
    assert "sk-should-not-leak" not in r.text


def test_get_novita_models_returns_cached_list_and_base_models(monkeypatch):
    monkeypatch.setattr(
        "domain.novita_model_catalog.get_cached_novita_models",
        lambda: ["a.safetensors", "b.safetensors"],
    )
    monkeypatch.setattr(
        "domain.novita_model_catalog.get_cached_base_models",
        lambda: {"a.safetensors": "Pony"},
    )
    client = TestClient(app_under_test())
    r = client.get("/api/image-gen/novita-models")
    assert r.status_code == 200
    assert r.json() == {
        "models": ["a.safetensors", "b.safetensors"],
        "base_models": {"a.safetensors": "Pony"},
    }


def test_get_style_presets_returns_five_entries_with_expected_fields():
    client = TestClient(app_under_test())
    r = client.get("/api/image-gen/style-presets")
    assert r.status_code == 200
    presets = r.json()["presets"]
    assert len(presets) == 5
    assert {"id", "label", "preview_url"} <= set(presets[0].keys())
    ids = [p["id"] for p in presets]
    assert "anime" in ids
    anime = next(p for p in presets if p["id"] == "anime")
    assert anime["preview_url"] == "/art-style-presets/anime.jpg"


def test_post_novita_models_refresh_schedules_job_when_key_configured(monkeypatch):
    from api.services.scheduler import SCHEDULER

    monkeypatch.setattr(
        "domain.model_catalog.load_custom_models",
        lambda: [{"id": "img-1", "provider": "image_gen", "api_key": "sk-real"}],
    )
    scheduled = []
    monkeypatch.setattr(
        SCHEDULER, "schedule_once",
        lambda name, delay_s, coro, **kw: scheduled.append((name, kw.get("dedup", False))),
    )

    client = TestClient(app_under_test())
    r = client.post("/api/image-gen/novita-models/refresh")

    assert r.status_code == 200
    assert r.json() == {"scheduled": True}
    assert scheduled == [("novita_model_catalog_refresh", True)]


def test_post_novita_models_refresh_errors_without_key(monkeypatch):
    monkeypatch.setattr("domain.model_catalog.load_custom_models", lambda: [])

    client = TestClient(app_under_test())
    r = client.post("/api/image-gen/novita-models/refresh")

    assert r.status_code == 200
    body = r.json()
    assert body["scheduled"] is False
    assert "API Key" in body["error"]
