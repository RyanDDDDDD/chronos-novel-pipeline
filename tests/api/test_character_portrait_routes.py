from __future__ import annotations

from fastapi.testclient import TestClient


def test_generate_endpoint_requires_character_name():
    from api.hub import app

    client = TestClient(app)
    resp = client.post("/api/character-portrait/generate", json={})
    assert resp.status_code == 400


def test_generate_endpoint_schedules_job(monkeypatch):
    from api.hub import app

    calls = []
    monkeypatch.setattr(
        "engine.setup_chat.character_portrait_generation.schedule_character_portrait_generation",
        lambda name: calls.append(name),
    )

    client = TestClient(app)
    resp = client.post("/api/character-portrait/generate", json={"character_name": "甲"})
    assert resp.status_code == 200
    assert calls == ["甲"]


def test_file_endpoint_404_when_character_missing(monkeypatch):
    from api.hub import app

    class _FakeRepo:
        def list_raw(self):
            return []

    monkeypatch.setattr("repositories.get_lore_repo", lambda: _FakeRepo())

    client = TestClient(app)
    resp = client.get("/api/character-portrait/不存在/file")
    assert resp.status_code == 404


def test_file_endpoint_returns_image_bytes(monkeypatch, tmp_path):
    from api.hub import app

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "portrait_path": "甲-123.png"}]

    monkeypatch.setattr("repositories.get_lore_repo", lambda: _FakeRepo())
    portrait_file = tmp_path / "甲-123.png"
    portrait_file.write_bytes(b"PNGDATA")
    monkeypatch.setattr("utils.paths.portrait_path", lambda filename: str(tmp_path / filename))

    client = TestClient(app)
    resp = client.get("/api/character-portrait/甲/file")
    assert resp.status_code == 200
    assert resp.content == b"PNGDATA"
    assert resp.headers["content-type"] == "image/png"
