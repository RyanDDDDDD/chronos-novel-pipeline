import io
import time

import pytest
from PIL import Image

from api.hub import app
from fastapi.testclient import TestClient
from engine.setup_chat import attachments as attachments_mod
from engine.setup_chat import image_upload_async as image_upload_async_mod
from engine.setup_chat.attachments import pop_attachment_bytes


def _make_png_bytes(width: int = 800, height: int = 600) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "blue").save(buf, "PNG")
    return buf.getvalue()


def _wait_for_attachment_status(client: TestClient, attachment_id: str, *, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = client.get(f"/api/setup-chat/attachments/{attachment_id}/status")
        if res.status_code == 200:
            body = res.json()
            if body.get("status") in ("ready", "error"):
                return body
        time.sleep(0.05)
    raise TimeoutError(f"attachment {attachment_id} did not finish within {timeout}s")


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _clear_attachment_store():
    attachments_mod._ATTACHMENTS.clear()
    image_upload_async_mod._jobs.clear()
    yield
    attachments_mod._ATTACHMENTS.clear()
    image_upload_async_mod._jobs.clear()


def test_upload_txt_attachment_returns_id(client):
    r = client.post(
        "/api/setup-chat/attachments",
        files={"file": ("novel.txt", io.BytesIO("第一章 起源".encode("utf-8")), "text/plain")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["filename"] == "novel.txt"
    assert isinstance(body["attachment_id"], str) and body["attachment_id"]


def test_upload_md_attachment_returns_id(client):
    r = client.post(
        "/api/setup-chat/attachments",
        files={"file": ("novel.md", io.BytesIO("# 标题".encode("utf-8")), "text/markdown")},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_upload_rejects_unsupported_extension(client):
    r = client.post(
        "/api/setup-chat/attachments",
        files={"file": ("novel.pdf", io.BytesIO(b"not really a pdf"), "application/pdf")},
    )
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_upload_png_attachment_returns_id(client):
    r = client.post(
        "/api/setup-chat/attachments",
        files={"file": ("page.png", io.BytesIO(_make_png_bytes()), "image/png")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["filename"] == "page.png"
    assert body["status"] == "processing"


def test_upload_png_stores_preprocessed_jpeg_bytes(client):
    r = client.post(
        "/api/setup-chat/attachments",
        files={"file": ("page.png", io.BytesIO(_make_png_bytes(3000, 2000)), "image/png")},
    )
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "processing"
    status = _wait_for_attachment_status(client, body["attachment_id"])
    assert status["status"] == "ready"
    stored = pop_attachment_bytes(body["attachment_id"])
    assert stored is not None
    filename, raw = stored
    assert filename == "page.png"
    assert raw.startswith(b"\xff\xd8")


def test_upload_persists_attachment_to_active_novel_disk(client, monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path / "novels"))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "n1")
    from engine.setup_chat.attachment_persistence import load_persisted_attachment_bytes

    r = client.post(
        "/api/setup-chat/attachments",
        files={"file": ("notes.txt", io.BytesIO("设定参考".encode("utf-8")), "text/plain")},
    )
    body = r.json()
    assert body["ok"] is True
    loaded = load_persisted_attachment_bytes("n1", body["attachment_id"])
    assert loaded == ("notes.txt", "设定参考".encode("utf-8"))


def test_upload_rejects_corrupt_image(client):
    r = client.post(
        "/api/setup-chat/attachments",
        files={"file": ("page.png", io.BytesIO(b"\x89PNG\r\n\x1a\n fake png bytes"), "image/png")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    status = _wait_for_attachment_status(client, body["attachment_id"])
    assert status["status"] == "error"


def test_upload_image_never_warns_regardless_of_byte_count(client, monkeypatch):
    from utils import config as config_mod

    base = config_mod.get_config()
    monkeypatch.setattr(
        config_mod,
        "get_config",
        lambda: {**base, "novel_import": {"chunk_size": 10000, "concurrency": None, "warn_threshold_chars": 1}},
    )
    r = client.post(
        "/api/setup-chat/attachments",
        files={"file": ("page.jpg", io.BytesIO(_make_png_bytes()), "image/jpeg")},
    )
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "processing"
    assert "warning" not in body


def test_delete_attachment_returns_ok(client):
    upload = client.post(
        "/api/setup-chat/attachments",
        files={"file": ("novel.md", io.BytesIO("# 标题".encode("utf-8")), "text/markdown")},
    )
    attachment_id = upload.json()["attachment_id"]
    r = client.delete(f"/api/setup-chat/attachments/{attachment_id}")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_delete_unknown_attachment_still_returns_ok(client):
    r = client.delete("/api/setup-chat/attachments/does-not-exist")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_upload_attachment_warns_when_exceeding_threshold(client, monkeypatch):
    from utils import config as config_mod

    base = config_mod.get_config()
    monkeypatch.setattr(
        config_mod,
        "get_config",
        lambda: {
            **base,
            "novel_import": {
                "chunk_size": 10000,
                "concurrency": None,
                "warn_threshold_chars": 5,
            },
        },
    )
    res = client.post(
        "/api/setup-chat/attachments",
        files={"file": ("a.txt", io.BytesIO(b"123456"), "text/plain")},
    )
    body = res.json()
    assert body["ok"] is True
    assert "warning" in body


def test_upload_attachment_no_warning_under_threshold(client):
    res = client.post(
        "/api/setup-chat/attachments",
        files={"file": ("a.txt", io.BytesIO(b"short"), "text/plain")},
    )
    body = res.json()
    assert body["ok"] is True
    assert body["status"] == "ready"
    assert "warning" not in body


def test_message_endpoint_accepts_attachment_ids(client, monkeypatch):
    import api.hub as hub_mod

    captured = {}

    async def fake_start(text, attachment_ids=None):
        captured["text"] = text
        captured["attachment_ids"] = attachment_ids

    monkeypatch.setattr(hub_mod.HUB, "start_setup_chat_turn", fake_start)
    r = client.post(
        "/api/setup-chat/message",
        json={"text": "解析一下", "attachment_ids": ["att-1", "att-2"]},
    )
    assert r.status_code == 200
    assert captured["text"] == "解析一下"
    assert captured["attachment_ids"] == ["att-1", "att-2"]


def test_message_endpoint_defaults_attachment_ids_to_empty_list(client, monkeypatch):
    import api.hub as hub_mod

    captured = {}

    async def fake_start(text, attachment_ids=None):
        captured["attachment_ids"] = attachment_ids

    monkeypatch.setattr(hub_mod.HUB, "start_setup_chat_turn", fake_start)
    r = client.post("/api/setup-chat/message", json={"text": "你好"})
    assert r.status_code == 200
    assert captured["attachment_ids"] == []
