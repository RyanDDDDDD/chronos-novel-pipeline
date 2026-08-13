import json

import pytest
from fastapi.testclient import TestClient

from api.hub import app
from engine.setup_chat.attachment_persistence import (
    persist_attachment,
    persist_image_description,
)


def _seed_novel(tmp_path, monkeypatch):
    novels_root = tmp_path / "novels"
    d = novels_root / "default"
    d.mkdir(parents=True, exist_ok=True)
    (d / "novel.json").write_text(json.dumps({"name": "默认"}), encoding="utf-8")
    (novels_root / "active.json").write_text(json.dumps({"active": "default"}), encoding="utf-8")
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(novels_root))
    import repositories
    repositories.init_repositories()
    return "default"


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_attachment_library_lists_persisted_items(client, tmp_path, monkeypatch):
    novel_id = _seed_novel(tmp_path, monkeypatch)
    persist_attachment(novel_id, "img1", "page.jpg", b"jpeg")
    persist_image_description(novel_id, "img1", "城门口的剑士")
    persist_attachment(novel_id, "txt1", "notes.txt", b"hello world")

    res = client.get("/api/setup-chat/attachments/library")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    by_id = {item["attachment_id"]: item for item in body["attachments"]}
    assert by_id["img1"]["kind"] == "image"
    assert by_id["img1"]["has_description"] is True
    assert by_id["txt1"]["kind"] == "text"


def test_attachment_parsed_returns_image_description(client, tmp_path, monkeypatch):
    novel_id = _seed_novel(tmp_path, monkeypatch)
    persist_attachment(novel_id, "img1", "page.jpg", b"jpeg")
    persist_image_description(novel_id, "img1", "城门口的剑士")

    res = client.get("/api/setup-chat/attachments/img1/parsed")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["content"] == "城门口的剑士"
    assert body["has_content"] is True


def test_attachment_parsed_returns_text_body(client, tmp_path, monkeypatch):
    novel_id = _seed_novel(tmp_path, monkeypatch)
    persist_attachment(novel_id, "txt1", "notes.txt", "你好，世界".encode("utf-8"))

    res = client.get("/api/setup-chat/attachments/txt1/parsed")
    assert res.status_code == 200
    assert res.json()["content"] == "你好，世界"


def test_attachment_file_serves_bytes(client, tmp_path, monkeypatch):
    novel_id = _seed_novel(tmp_path, monkeypatch)
    persist_attachment(novel_id, "img1", "page.jpg", b"jpeg-bytes")

    res = client.get("/api/setup-chat/attachments/img1/file")
    assert res.status_code == 200
    assert res.content == b"jpeg-bytes"
    assert "image/jpeg" in res.headers.get("content-type", "")
