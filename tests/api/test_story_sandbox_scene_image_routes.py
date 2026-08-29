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
        "media.scene.generation.schedule_sandbox_scene_image",
        lambda chapter, branch_id, round_id: seen.update(
            chapter=chapter, branch_id=branch_id, round_id=round_id,
        ),
    )
    r = client.post("/api/story-sandbox/scene-image",
                    json={"chapter": 3, "branch_id": "b1", "round_id": "r1"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert seen == {"chapter": 3, "branch_id": "b1", "round_id": "r1"}


def test_get_images_map(client):
    from media.scene import store
    store.store_sandbox_scene_image(3, "b1", "r1", b"PNG")
    r = client.get("/api/story-sandbox/scene-images", params={"chapter": 3, "branch_id": "b1"})
    assert r.status_code == 200
    url = r.json()["images"]["r1"]
    assert url.startswith("/api/story-sandbox/scene-image/3/b1/r1/file")


def test_get_file(client):
    from media.scene import store
    store.store_sandbox_scene_image(3, "b1", "r1", b"PNGBYTES")
    r = client.get("/api/story-sandbox/scene-image/3/b1/r1/file")
    assert r.status_code == 200 and r.content == b"PNGBYTES"
    assert client.get("/api/story-sandbox/scene-image/3/b1/nope/file").status_code == 404
