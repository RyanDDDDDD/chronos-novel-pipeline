from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    nid = "default"
    (tmp_path / nid / "chapters").mkdir(parents=True)
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", nid)
    from api.hub import app
    return TestClient(app)


def test_post_schedules_generation(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "media.scene.author.schedule_author_stage_scene_image",
        lambda chapter, stage_index: seen.update(chapter=chapter, stage_index=stage_index),
    )
    r = client.post("/api/author-loop/scene-image", json={"chapter": 6, "index": 2})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert seen == {"chapter": 6, "stage_index": 2}


@pytest.fixture
def no_schedule(monkeypatch):
    """Records every scheduling attempt so a rejected request can be proven to have scheduled
    nothing (an unvalidated body used to reach the scheduler as chapter 0)."""
    seen: list[tuple] = []
    monkeypatch.setattr(
        "media.scene.author.schedule_author_stage_scene_image",
        lambda chapter, stage_index: seen.append((chapter, stage_index)),
    )
    return seen


@pytest.mark.parametrize("body", [
    {"index": 0},
    {"chapter": 0, "index": 0},
    {"chapter": -1, "index": 0},
    {"chapter": "abc", "index": 0},
    {"chapter": None, "index": 0},
])
def test_post_rejects_bad_chapter(client, no_schedule, body):
    r = client.post("/api/author-loop/scene-image", json=body)
    assert r.status_code == 400
    assert r.json()["ok"] is False
    assert not no_schedule


@pytest.mark.parametrize("body", [{"chapter": 6, "index": -1}, {"chapter": 6, "index": "x"}])
def test_post_rejects_bad_index(client, no_schedule, body):
    r = client.post("/api/author-loop/scene-image", json=body)
    assert r.status_code == 400
    assert r.json()["ok"] is False
    assert not no_schedule


def test_post_defaults_a_missing_index_to_stage_zero(client, no_schedule):
    """Mirrors /api/author-loop/start's absent-value handling: an omitted field falls back to
    its default and is then range-checked, rather than being a coercion crash."""
    r = client.post("/api/author-loop/scene-image", json={"chapter": 6})
    assert r.status_code == 200
    assert no_schedule == [(6, 0)]


@pytest.mark.parametrize("payload", ["not json at all", "[1, 2]", '"a string"'])
def test_post_rejects_malformed_body(client, no_schedule, payload):
    r = client.post(
        "/api/author-loop/scene-image", content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert 400 <= r.status_code < 500
    assert not no_schedule


def test_get_images_map(client):
    from media.scene import author_store
    author_store.store_author_stage_scene_image(6, 2, b"PNG")
    r = client.get("/api/author-loop/scene-images", params={"chapter": 6})
    assert r.status_code == 200
    url = r.json()["images"]["2"]
    assert url.startswith("/api/author-loop/scene-image/6/2/file")


def test_get_file(client):
    from media.scene import author_store
    author_store.store_author_stage_scene_image(6, 2, b"PNGBYTES")
    r = client.get("/api/author-loop/scene-image/6/2/file")
    assert r.status_code == 200 and r.content == b"PNGBYTES"
    assert client.get("/api/author-loop/scene-image/6/99/file").status_code == 404
