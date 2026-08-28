import pytest

from tests.conftest import seed_registry_novel
from utils.paths import active_novel_id
from api.services.message_hub import MessageHub
from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_delete_active_resets_setup_chat_before_move(monkeypatch, tmp_path):
    """Delete the active novel: reset setup-chat in the asynchronous callback first, and then move it to trash."""
    import api.hub as hub_mod
    import api.services.novels as nv
    from api.hub import app

    novels_root = tmp_path / "novels"
    novels_root.mkdir()
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(novels_root))
    seed_registry_novel(novels_root, "default", "默认")
    seed_registry_novel(novels_root, "novel-9", "九", active=True)

    hub = MessageHub()
    reset_called = {"n": 0}
    order: list[str] = []
    pending: list[tuple[str, object]] = []
    invalidate_called = {"n": 0}

    async def fake_reset(novel_id: str | None = None) -> None:
        reset_called["n"] += 1
        order.append("reset")

    def fake_invalidate(novel_id: str | None = None) -> None:
        invalidate_called["n"] += 1

    hub._setup_chat_agents["novel-9"] = object()
    monkeypatch.setattr(hub_mod, "HUB", hub)
    monkeypatch.setattr(hub, "reset_setup_chat", fake_reset)
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.invalidate_entity_vocab_cache", fake_invalidate,
    )

    orig_move = nv.move_novel_to_trash

    def track_move(nid: str) -> None:
        order.append("move")
        orig_move(nid)

    monkeypatch.setattr(nv, "move_novel_to_trash", track_move)

    def capture_schedule(nid: str, release) -> None:
        pending.append((nid, release))

    monkeypatch.setattr(nv, "_schedule_trash_move", capture_schedule)

    client = TestClient(app)
    r = client.delete("/api/novels/novel-9")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert len(pending) == 1
    nid, release = pending[0]
    await release()
    track_move(nid)
    assert reset_called["n"] == 1
    assert invalidate_called["n"] == 1
    assert order == ["reset", "move"]
    assert not (novels_root / "novel-9").exists()
    assert (novels_root / ".trash" / "novel-9").is_dir()
    assert active_novel_id() == "default"


def test_delete_blocked_while_setup_chat_busy(monkeypatch, tmp_path):
    import api.hub as hub_mod
    from api.hub import app
    from api.services import novels as nv

    novels_root = tmp_path / "novels"
    novels_root.mkdir()
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(novels_root))
    seed_registry_novel(novels_root, "default", "default")
    seed_registry_novel(novels_root, "novel-9", "九", active=True)

    hub = MessageHub()
    hub._setup_chat_tasks["novel-9"] = type("_T", (), {"done": lambda self: False})()
    monkeypatch.setattr(hub_mod, "HUB", hub)

    client = TestClient(app)
    r = client.delete("/api/novels/novel-9")
    assert r.status_code == 409
    assert (novels_root / "novel-9").is_dir()
    assert nv._is_deleted("novel-9") is False


def test_delete_blocked_while_sandbox_busy(monkeypatch, tmp_path):
    import api.hub as hub_mod
    from api.hub import app

    novels_root = tmp_path / "novels"
    novels_root.mkdir()
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(novels_root))
    seed_registry_novel(novels_root, "default", "default")
    seed_registry_novel(novels_root, "novel-9", "九", active=True)

    hub = MessageHub()
    hub._story_sandbox_tasks["novel-9"] = type("_T", (), {"done": lambda self: False})()
    monkeypatch.setattr(hub_mod, "HUB", hub)

    client = TestClient(app)
    r = client.delete("/api/novels/novel-9")
    assert r.status_code == 409
    assert (novels_root / "novel-9").is_dir()


def test_switch_not_blocked_by_other_novel_busy(monkeypatch, tmp_path):
    """Switching focus no longer checks busy state at all -- a running background task on
    any novel must not block switching which novel the frontend is looking at."""
    import api.hub as hub_mod
    from api.hub import app

    novels_root = tmp_path / "novels"
    novels_root.mkdir()
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(novels_root))
    seed_registry_novel(novels_root, "default", "default", active=True)
    seed_registry_novel(novels_root, "novel-9", "九")

    hub = MessageHub()
    hub._story_sandbox_tasks["default"] = type("_T", (), {"done": lambda self: False})()
    monkeypatch.setattr(hub_mod, "HUB", hub)

    client = TestClient(app)
    r = client.post("/api/novels/active", json={"id": "novel-9"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert active_novel_id() == "novel-9"


def test_delete_not_blocked_by_other_novel_busy(monkeypatch, tmp_path):
    import api.hub as hub_mod
    from api.hub import app

    novels_root = tmp_path / "novels"
    novels_root.mkdir()
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(novels_root))
    seed_registry_novel(novels_root, "default", "default", active=True)
    seed_registry_novel(novels_root, "novel-9", "九")
    seed_registry_novel(novels_root, "novel-10", "十")

    hub = MessageHub()
    hub._story_sandbox_tasks["novel-9"] = type("_T", (), {"done": lambda self: False})()
    monkeypatch.setattr(hub_mod, "HUB", hub)

    client = TestClient(app)
    r = client.delete("/api/novels/novel-10")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_novels_status_includes_skeleton_review_and_timeline_cascade(monkeypatch, tmp_path):
    import api.hub as hub_mod
    from api.hub import app

    novels_root = tmp_path / "novels"
    novels_root.mkdir()
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(novels_root))
    seed_registry_novel(novels_root, "n1", "一", active=True)
    seed_registry_novel(novels_root, "n2", "二")

    hub = MessageHub()
    monkeypatch.setattr(hub_mod, "HUB", hub)
    monkeypatch.setattr(hub, "is_pipeline_busy", lambda nid: False)
    monkeypatch.setattr(hub, "is_setup_chat_busy", lambda nid: False)
    monkeypatch.setattr(hub, "is_story_sandbox_busy", lambda nid: False)
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_pipeline.any_review_active", lambda nid: nid == "n1",
    )
    monkeypatch.setattr(
        "engine.setup_chat.timeline_auto.is_cascade_active", lambda nid: nid == "n2",
    )

    client = TestClient(app)
    resp = client.get("/api/novels/status")
    body = resp.json()

    assert body["n1"]["skeleton_review"] is True
    assert body["n1"]["timeline_cascade"] is False
    assert body["n2"]["skeleton_review"] is False
    assert body["n2"]["timeline_cascade"] is True


def test_patch_novel_pinned_sorts_to_top(monkeypatch, tmp_path):
    from api.hub import app

    novels_root = tmp_path / "novels"
    novels_root.mkdir()
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(novels_root))
    seed_registry_novel(novels_root, "a", "A小说", active=False)
    seed_registry_novel(novels_root, "b", "B小说", active=True)

    client = TestClient(app)
    r = client.patch("/api/novels/a", json={"pinned": True})
    assert r.status_code == 200 and r.json()["ok"] is True

    body = client.get("/api/novels").json()
    assert [n["id"] for n in body["novels"]] == ["a", "b"]
    assert body["novels"][0]["pinned"] is True

    r = client.patch("/api/novels/a", json={"pinned": False})
    assert r.status_code == 200 and r.json()["ok"] is True
    body = client.get("/api/novels").json()
    assert [n["id"] for n in body["novels"]] == ["a", "b"]
    assert all(not n["pinned"] for n in body["novels"])


def test_patch_novel_pinned_unknown_returns_400(monkeypatch, tmp_path):
    from api.hub import app

    novels_root = tmp_path / "novels"
    novels_root.mkdir()
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(novels_root))
    seed_registry_novel(novels_root, "default", "默认", active=True)

    client = TestClient(app)
    r = client.patch("/api/novels/nope", json={"pinned": True})
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_novels_status_omits_character_review(monkeypatch, tmp_path):
    import api.hub as hub_mod
    from api.hub import app

    novels_root = tmp_path / "novels"
    novels_root.mkdir()
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(novels_root))
    seed_registry_novel(novels_root, "novel-A", "一", active=True)

    hub = MessageHub()
    monkeypatch.setattr(hub_mod, "HUB", hub)
    monkeypatch.setattr(hub, "is_pipeline_busy", lambda nid: False)
    monkeypatch.setattr(hub, "is_setup_chat_busy", lambda nid: False)
    monkeypatch.setattr(hub, "is_story_sandbox_busy", lambda nid: False)
    monkeypatch.setattr("engine.setup_chat.skeleton_pipeline.any_review_active", lambda nid: False)
    monkeypatch.setattr("engine.setup_chat.timeline_auto.is_cascade_active", lambda nid: False)
    monkeypatch.setattr(
        "engine.setup_chat.world_background_review.is_world_review_active",
        lambda nid: True,
    )

    client = TestClient(app)
    resp = client.get("/api/novels/status")
    status = resp.json()["novel-A"]
    assert "character_review" not in status
    assert status["world_review"] is True
    assert status["skeleton_review"] is False
    assert status["timeline_cascade"] is False
