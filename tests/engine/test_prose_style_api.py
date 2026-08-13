"""API: style preset list and per-novel reading and writing."""
import os
import sys

import pytest
from fastapi.testclient import TestClient

from tests.conftest import seed_registry_novel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "backend"))


@pytest.fixture
def prose_api_client(tmp_path, monkeypatch):
    import api.hub as hub
    from api.services.message_hub import MessageHub

    skills = tmp_path / "skills" / "prose-styles"
    skills.mkdir(parents=True)
    (skills / "plain-explicit.md").write_text("# 语感调色：大白话露骨\n", encoding="utf-8")
    (skills / "cold-restrained.md").write_text("# 语感调色：冷硬克制\n", encoding="utf-8")
    monkeypatch.setattr("engine.execution.prose_style.SKILLS_DIR", str(tmp_path / "skills"))

    novels = tmp_path / "novels"
    # api.hub's module-level ensure_novels_initialized() may have already bootstrapped this
    # same tmp_path/novels scaffold via CHRONOS_NOVELS_DIR, set by the autouse
    # _isolate_novels_dir fixture before this import ran -- exist_ok=True tolerates that.
    novels.mkdir(exist_ok=True)
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(novels))
    seed_registry_novel(
        novels, "default", "默认", active=True,
        prose_style={"preset": "plain-explicit", "custom_addendum": ""},
    )

    hub.HUB = MessageHub()
    return TestClient(hub.app)


def test_list_prose_styles(prose_api_client):
    r = prose_api_client.get("/api/prose-styles")
    assert r.status_code == 200
    styles = r.json()["styles"]
    ids = {s["id"] for s in styles}
    assert "plain-explicit" in ids and "cold-restrained" in ids
    titles = {s["title"] for s in styles}
    assert "语感调色：大白话露骨" in titles


def test_get_prose_style(prose_api_client):
    r = prose_api_client.get("/api/novels/default/prose-style")
    assert r.status_code == 200
    assert r.json() == {"preset": "plain-explicit", "custom_addendum": ""}


def test_set_prose_style_roundtrip(prose_api_client):
    import api.services.novels as nv

    r = prose_api_client.put(
        "/api/novels/default/prose-style",
        json={"preset": "cold-restrained", "custom_addendum": "更冷"},
    )
    assert r.status_code == 200 and r.json()["ok"] is True
    assert nv.get_prose_style("default") == {"preset": "cold-restrained", "custom_addendum": "更冷"}


def test_set_prose_style_unknown_preset_rejected(prose_api_client):
    r = prose_api_client.put(
        "/api/novels/default/prose-style",
        json={"preset": "no-such", "custom_addendum": ""},
    )
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_get_prose_style_content(prose_api_client):
    r = prose_api_client.get("/api/prose-styles/plain-explicit")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "plain-explicit"
    assert body["content"] == "# 语感调色：大白话露骨"


def test_get_prose_style_content_unknown_preset(prose_api_client):
    r = prose_api_client.get("/api/prose-styles/no-such")
    assert r.status_code == 404
    assert r.json()["ok"] is False
