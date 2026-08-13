"""Mainly authored REST: list and single chapter reading."""

from fastapi.testclient import TestClient


def _make_client():
    import api.hub as mh
    from api.services.message_hub import MessageHub

    mh.HUB = MessageHub()
    from api.hub import app

    return TestClient(app, raise_server_exceptions=False)


def test_list_manuscripts_empty(tmp_path, monkeypatch):
    import api.services.pipeline_catalog as pc

    monkeypatch.setattr(pc, "chapters_dir", lambda: tmp_path)
    client = _make_client()
    resp = client.get("/api/chapters/manuscripts")
    assert resp.status_code == 200
    assert resp.json()["chapters"] == []


def test_list_and_read_manuscript(tmp_path, monkeypatch):
    import api.services.pipeline_catalog as pc

    monkeypatch.setattr(pc, "chapters_dir", lambda: tmp_path)
    ch_dir = tmp_path / "第3章"
    ch_dir.mkdir()
    path = ch_dir / "第3章_主笔.md"
    path.write_text("## 正文\n\n甲进门。", encoding="utf-8")

    client = _make_client()
    listed = client.get("/api/chapters/manuscripts").json()["chapters"]
    assert listed == [{"chapter": 3, "path": str(path)}]

    got = client.get("/api/chapters/3/manuscript")
    assert got.status_code == 200
    body = got.json()
    assert body["ok"] is True
    assert body["content"] == "## 正文\n\n甲进门。"
    assert body["path"] == str(path)


def test_read_manuscript_missing_returns_404(tmp_path, monkeypatch):
    import api.services.pipeline_catalog as pc

    monkeypatch.setattr(pc, "chapters_dir", lambda: tmp_path)
    client = _make_client()
    resp = client.get("/api/chapters/2/manuscript")
    assert resp.status_code == 404
    assert resp.json()["ok"] is False


def test_read_manuscript_invalid_chapter_returns_400(tmp_path, monkeypatch):
    import api.services.pipeline_catalog as pc

    monkeypatch.setattr(pc, "chapters_dir", lambda: tmp_path)
    client = _make_client()
    resp = client.get("/api/chapters/0/manuscript")
    assert resp.status_code == 400
