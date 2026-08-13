import asyncio

import pytest
from api.services.message_hub import MessageHub
import api.services.message_hub as mh_mod


class _FakeAgentState:
    """Minimal stand-in for LangGraph's StateSnapshot -- start_setup_chat_turn now calls
    agent.aget_state(config) unconditionally (turn-cancel pre-state capture), so every test
    that stubs build_agent needs an object supporting that call, not a bare object()."""

    values: dict = {"messages": []}


class _FakeAgent:
    async def aget_state(self, config):
        return _FakeAgentState()


def test_setup_chat_not_in_busy(monkeypatch):
    hub = MessageHub()
    hub._setup_chat_tasks[mh_mod.active_novel_id()] = object()  #type: ignore[assignment] # Simulation is running
    assert hub.is_pipeline_busy() is False  #Chat lanes do not count towards build locks


@pytest.mark.asyncio
async def test_start_setup_chat_turn_runs(monkeypatch):
    hub = MessageHub()
    seen = []

    async def fake_run_turn(agent, novel_id, text, emit, accountant):
        await emit({"type": "setup_chat_token", "delta": text})
        await emit({"type": "setup_chat_done"})

    async def fake_broadcast(ev):
        seen.append(ev)

    async def fake_build():
        return _FakeAgent()

    monkeypatch.setattr("engine.setup_chat.agent.build_agent", fake_build)
    monkeypatch.setattr("api.services.message_hub.run_turn", fake_run_turn)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    #Isolated session placement: append_user in start_setup_chat_turn will write the [true] of the currently active novel
    #Session directory - "Hello" will be accumulated into the user's real conversation record without blocking (+1 for each test run).
    monkeypatch.setattr(
        "engine.setup_chat.session_record.append_user",
        lambda session_dir, content: {"id": "u-test", "role": "user", "content": content, "seq": 0, "ts": 0},
    )
    monkeypatch.setattr("engine.setup_chat.session_record.append_assistant", lambda *a, **k: None)

    await hub.start_setup_chat_turn("你好")
    if (_t := hub._setup_chat_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    assert {"type": "setup_chat_token", "delta": "你好"} in seen


@pytest.mark.asyncio
async def test_start_setup_chat_turn_folds_attachment_manifest_into_agent_text(monkeypatch):
    hub = MessageHub()
    seen_text = {}

    async def fake_run_turn(agent, novel_id, text, emit, accountant):
        seen_text["value"] = text
        await emit({"type": "setup_chat_done"})

    async def fake_broadcast(ev):
        pass

    async def fake_build():
        return _FakeAgent()

    monkeypatch.setattr("engine.setup_chat.agent.build_agent", fake_build)
    monkeypatch.setattr("api.services.message_hub.run_turn", fake_run_turn)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    monkeypatch.setattr(
        "engine.setup_chat.session_record.append_user",
        lambda session_dir, content: {"id": "u-test", "role": "user", "content": content, "seq": 0, "ts": 0},
    )
    monkeypatch.setattr("engine.setup_chat.session_record.append_assistant", lambda *a, **k: None)

    from engine.setup_chat.attachments import store_attachment
    aid = store_attachment("novel.txt", "正文".encode("utf-8"))

    await hub.start_setup_chat_turn("解析总结小说内容并生成设定", [aid])
    if (_t := hub._setup_chat_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t

    assert aid in seen_text["value"]
    assert "novel.txt" in seen_text["value"]
    assert "解析总结小说内容并生成设定" in seen_text["value"]


@pytest.mark.asyncio
async def test_start_setup_chat_turn_without_attachments_unchanged(monkeypatch):
    hub = MessageHub()
    seen_text = {}

    async def fake_run_turn(agent, novel_id, text, emit, accountant):
        seen_text["value"] = text
        await emit({"type": "setup_chat_done"})

    async def fake_broadcast(ev):
        pass

    async def fake_build():
        return _FakeAgent()

    monkeypatch.setattr("engine.setup_chat.agent.build_agent", fake_build)
    monkeypatch.setattr("api.services.message_hub.run_turn", fake_run_turn)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    monkeypatch.setattr(
        "engine.setup_chat.session_record.append_user",
        lambda session_dir, content: {"id": "u-test", "role": "user", "content": content, "seq": 0, "ts": 0},
    )
    monkeypatch.setattr("engine.setup_chat.session_record.append_assistant", lambda *a, **k: None)

    await hub.start_setup_chat_turn("你好")
    if (_t := hub._setup_chat_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t

    assert seen_text["value"] == "你好"


@pytest.mark.asyncio
async def test_stop_setup_chat_turn_cancels_and_restores(monkeypatch):
    hub = MessageHub()
    seen = []
    started = asyncio.Event()

    class FakeAgentState:
        def __init__(self, values):
            self.values = values

    class FakeAgent:
        async def aget_state(self, config):
            return FakeAgentState({"messages": [{"role": "user", "content": "轮前消息"}]})

        async def aupdate_state(self, config, values, as_node=None):
            restored["values"] = values

    restored = {}

    async def fake_run_turn(agent, novel_id, text, emit, accountant):
        started.set()
        await asyncio.sleep(3600)

    async def fake_broadcast(ev):
        seen.append(ev)

    async def fake_build():
        return FakeAgent()

    snapshot_calls = []
    restore_calls = []

    def fake_snapshot_turn_start():
        snapshot_calls.append(1)
        return True

    def fake_restore_turn_start():
        restore_calls.append(1)
        return True

    removed = []

    def fake_remove_message(session_dir, msg_id):
        removed.append(msg_id)
        return True

    monkeypatch.setattr("engine.setup_chat.agent.build_agent", fake_build)
    monkeypatch.setattr("api.services.message_hub.run_turn", fake_run_turn)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    monkeypatch.setattr(
        "engine.setup_chat.session_record.append_user",
        lambda session_dir, content: {"id": "u-cancel-test", "role": "user", "content": content, "seq": 0, "ts": 0},
    )
    monkeypatch.setattr("engine.setup_chat.turn_snapshot.snapshot_turn_start", fake_snapshot_turn_start)
    monkeypatch.setattr("engine.setup_chat.turn_snapshot.restore_turn_start", fake_restore_turn_start)
    monkeypatch.setattr("engine.setup_chat.session_record.remove_message", fake_remove_message)

    await hub.start_setup_chat_turn("会被取消的一轮")
    await asyncio.wait_for(started.wait(), timeout=1)
    await hub.stop_setup_chat_turn()

    from langchain_core.messages import RemoveMessage
    from langgraph.graph.message import REMOVE_ALL_MESSAGES

    assert isinstance(restored["values"]["messages"][0], RemoveMessage)
    assert restored["values"]["messages"][0].id == REMOVE_ALL_MESSAGES
    assert restored["values"]["messages"][1:] == [{"role": "user", "content": "轮前消息"}]
    assert snapshot_calls == [1]
    assert restore_calls == [1]
    assert removed == ["u-cancel-test"]
    assert {
        "type": "setup_chat_turn_cancelled", "rollback_failed": False,
        "novel_id": mh_mod.active_novel_id(),
    } in seen
    assert mh_mod.active_novel_id() not in hub._setup_chat_tasks


@pytest.mark.asyncio
async def test_stop_setup_chat_turn_with_no_running_task_is_a_noop(monkeypatch):
    hub = MessageHub()
    seen = []

    async def fake_broadcast(ev):
        seen.append(ev)

    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    await hub.stop_setup_chat_turn()
    assert seen == []


def test_post_message_empty_rejected(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    r = client.post("/api/setup-chat/message", json={"text": "  "})
    assert r.status_code == 400


def test_post_regenerate_empty_rejected(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    r = client.post("/api/setup-chat/regenerate", json={"text": "  "})
    assert r.status_code == 400


def test_post_regenerate_delegates_to_hub(monkeypatch):
    import api.hub as hub_mod
    from api.hub import app
    from fastapi.testclient import TestClient

    captured = {}

    async def fake_regenerate(text):
        captured["text"] = text

    monkeypatch.setattr(hub_mod.HUB, "regenerate_setup_chat_turn", fake_regenerate)
    client = TestClient(app)
    r = client.post("/api/setup-chat/regenerate", json={"text": "继续"})
    assert r.status_code == 200
    assert captured["text"] == "继续"


def test_post_message_empty_text_accepted_when_attachments_present(monkeypatch):
    import api.hub as hub_mod
    from api.hub import app
    from fastapi.testclient import TestClient

    captured = {}

    async def fake_start(text, attachment_ids=None):
        captured["text"] = text
        captured["attachment_ids"] = attachment_ids

    monkeypatch.setattr(hub_mod.HUB, "start_setup_chat_turn", fake_start)
    client = TestClient(app)
    r = client.post("/api/setup-chat/message", json={"text": "  ", "attachment_ids": ["att-1"]})
    assert r.status_code == 200
    assert captured["text"] == ""
    assert captured["attachment_ids"] == ["att-1"]


def test_get_history_shape(monkeypatch):
    import api.hub as hub_mod
    from api.hub import app
    from fastapi.testclient import TestClient

    async def fake_history(novel_id=None):
        return [{"id": "m1", "role": "user", "content": "hi"}]

    monkeypatch.setattr(hub_mod.HUB, "setup_chat_history", fake_history)
    client = TestClient(app)
    r = client.get("/api/setup-chat/history")
    assert r.status_code == 200
    assert r.json()["messages"][0] == {"id": "m1", "role": "user", "content": "hi"}


def test_get_history_includes_live_round_none_when_idle(monkeypatch):
    import api.hub as hub_mod
    from api.hub import app
    from fastapi.testclient import TestClient

    async def fake_history(novel_id=None):
        return []

    monkeypatch.setattr(hub_mod.HUB, "setup_chat_history", fake_history)
    monkeypatch.setattr(hub_mod.HUB, "setup_chat_live_round", lambda novel_id=None: None)
    client = TestClient(app)
    r = client.get("/api/setup-chat/history")
    assert r.status_code == 200
    assert r.json()["live_round"] is None


def test_get_history_includes_live_round_when_in_flight(monkeypatch):
    import api.hub as hub_mod
    from api.hub import app
    from fastapi.testclient import TestClient

    async def fake_history(novel_id=None):
        return []

    live = {"instruction": "继续", "events": [{"type": "setup_chat_token", "delta": "甲"}]}
    monkeypatch.setattr(hub_mod.HUB, "setup_chat_history", fake_history)
    monkeypatch.setattr(hub_mod.HUB, "setup_chat_live_round", lambda novel_id=None: live)
    client = TestClient(app)
    r = client.get("/api/setup-chat/history")
    assert r.status_code == 200
    assert r.json()["live_round"] == live


def test_get_history_novel_id_overrides_active_novel(monkeypatch):
    """Hydrate during a novel switch races the backend's active-novel pointer flip -- passing
    novel_id explicitly must return that novel's live round regardless of what's active."""
    import api.hub as hub_mod
    from api.hub import app
    from fastapi.testclient import TestClient

    async def fake_history(novel_id=None):
        return [{"id": "m1", "role": "user", "content": novel_id or "active"}]

    def fake_live_round(novel_id=None):
        if novel_id == "novel-b":
            return {"instruction": "b", "events": [{"type": "setup_chat_token", "delta": "乙"}]}
        return None

    monkeypatch.setattr(hub_mod.HUB, "setup_chat_history", fake_history)
    monkeypatch.setattr(hub_mod.HUB, "setup_chat_live_round", fake_live_round)
    client = TestClient(app)
    r = client.get("/api/setup-chat/history?novel_id=novel-b")
    assert r.status_code == 200
    body = r.json()
    assert body["messages"][0]["content"] == "novel-b"
    assert body["live_round"]["events"][0]["delta"] == "乙"


def test_get_status_reflects_hub_busy(monkeypatch):
    import api.hub as hub_mod
    from api.hub import app
    from fastapi.testclient import TestClient

    class _FakeTask:
        def done(self) -> bool:
            return False

    import api.services.message_hub as mh_mod

    hub_mod.HUB._setup_chat_tasks[mh_mod.active_novel_id()] = _FakeTask()  # type: ignore[assignment]
    monkeypatch.setattr(hub_mod.HUB, "is_image_recognition_configured", lambda: False)
    client = TestClient(app)
    assert client.get("/api/setup-chat/status").json() == {
        "busy": True, "novel_import": None, "image_recognition_configured": False,
    }
    hub_mod.HUB._setup_chat_tasks.pop(mh_mod.active_novel_id(), None)
    assert client.get("/api/setup-chat/status").json() == {
        "busy": False, "novel_import": None, "image_recognition_configured": False,
    }


def test_get_status_novel_id_overrides_active_novel(monkeypatch):
    """A caller resyncing right after a novel switch races the backend's active-novel pointer
    flip -- passing novel_id explicitly must report on that novel regardless of what's currently
    active, mirroring author_loop_status_endpoint."""
    import api.hub as hub_mod
    from api.hub import app
    from fastapi.testclient import TestClient

    class _FakeTask:
        def done(self) -> bool:
            return False

    hub_mod.HUB._setup_chat_tasks["novel-a"] = _FakeTask()  # type: ignore[assignment]
    monkeypatch.setattr(hub_mod.HUB, "is_image_recognition_configured", lambda: False)
    client = TestClient(app)
    try:
        assert client.get("/api/setup-chat/status?novel_id=novel-a").json() == {
            "busy": True, "novel_import": None, "image_recognition_configured": False,
        }
        assert client.get("/api/setup-chat/status?novel_id=novel-b").json() == {
            "busy": False, "novel_import": None, "image_recognition_configured": False,
        }
    finally:
        hub_mod.HUB._setup_chat_tasks.pop("novel-a", None)


def test_get_status_includes_running_novel_import_progress(monkeypatch):
    import api.hub as hub_mod
    from api.hub import app
    from fastapi.testclient import TestClient

    hub_mod.HUB._setup_chat_image_progress["novel-a"] = {"done": 1, "total": 4}
    monkeypatch.setattr(hub_mod.HUB, "is_image_recognition_configured", lambda: True)
    client = TestClient(app)
    try:
        assert client.get("/api/setup-chat/status?novel_id=novel-a").json() == {
            "busy": False,
            "novel_import": {"status": "running", "kind": "image", "index": 1, "total": 4},
            "image_recognition_configured": True,
        }
    finally:
        hub_mod.HUB._setup_chat_image_progress.pop("novel-a", None)


def test_setup_chat_reset_endpoint_returns_ok(monkeypatch):
    import api.hub as hub_mod
    from api.hub import app
    from fastapi.testclient import TestClient

    async def fake_clear():
        return None

    monkeypatch.setattr(hub_mod.HUB, "clear_setup_chat_conversation", fake_clear)
    client = TestClient(app)
    r = client.post("/api/setup-chat/reset")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_setup_chat_reset_endpoint_rejects_when_busy(monkeypatch):
    import api.hub as hub_mod
    from api.hub import app
    from fastapi.testclient import TestClient

    async def fake_clear():
        raise RuntimeError("对话进行中，无法清空")

    monkeypatch.setattr(hub_mod.HUB, "clear_setup_chat_conversation", fake_clear)
    client = TestClient(app)
    r = client.post("/api/setup-chat/reset")
    assert r.status_code == 409
    body = r.json()
    assert body["ok"] is False
    assert "对话进行中" in body["error"]


def test_get_skills_index_shape(monkeypatch, tmp_path):
    from api.hub import app
    from fastapi.testclient import TestClient

    (tmp_path / "demo-skill.md").write_text(
        "---\ndescription: 演示技能\nmetadata:\n  kind: plot-extension\n---\n正文",
        encoding="utf-8",
    )
    monkeypatch.setattr("engine.setup_chat.skills.setup_chat_skill_dirs", lambda: [str(tmp_path)])
    r = TestClient(app).get("/api/setup-chat/skills")
    assert r.status_code == 200
    items = r.json()["skills"]
    entry = next(i for i in items if i["name"] == "demo-skill")
    #菜单列全量：plot-extension 也在（显式点名没理由拦），且只回四个展示字段
    assert entry == {"name": "demo-skill", "description": "演示技能",
                     "kind": "plot-extension", "source": "builtin"}


def test_get_mode_defaults_to_manual(monkeypatch):
    from api.hub import app
    from engine.setup_chat.mode import set_auto_mode
    from fastapi.testclient import TestClient

    set_auto_mode(False)
    client = TestClient(app)
    r = client.get("/api/setup-chat/mode")
    assert r.status_code == 200
    assert r.json() == {"auto": False}


def test_post_mode_turns_auto_on_and_off():
    from api.hub import app
    from engine.setup_chat.mode import is_auto_mode, set_auto_mode
    from fastapi.testclient import TestClient

    client = TestClient(app)
    try:
        r = client.post("/api/setup-chat/mode", json={"auto": True})
        assert r.status_code == 200
        assert r.json() == {"auto": True}
        assert is_auto_mode() is True

        r = client.post("/api/setup-chat/mode", json={"auto": False})
        assert r.json() == {"auto": False}
        assert is_auto_mode() is False
    finally:
        set_auto_mode(False)


def test_setup_chat_stop_endpoint_calls_hub(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient

    calls = []

    async def fake_stop():
        calls.append(1)

    from api import routes

    monkeypatch.setattr(routes._hub_instance(), "stop_setup_chat_turn", fake_stop)
    client = TestClient(app)
    res = client.post("/api/setup-chat/stop")
    assert res.status_code == 200
    assert calls == [1]
