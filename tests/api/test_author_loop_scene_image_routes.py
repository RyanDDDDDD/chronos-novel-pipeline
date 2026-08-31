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
