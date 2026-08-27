"""Tests for MessageHub (Broadcast/Client/Master Interaction) with FastAPI endpoints."""
import asyncio
from unittest.mock import AsyncMock

import pytest


@pytest.fixture(autouse=True)
def _bypass_author_loop_preflight(monkeypatch):
    """This module tests the hub orchestration mechanism, and accidentally activates the front door - releasing preflight, eliminating the need to lay out the world view/character/skeleton.

    The aggregation behavior of the front door is specially tested by tests/engine/author_loop/test_preflight.py."""

    import engine.author_loop.preflight as pf
    monkeypatch.setattr(pf, "collect_author_loop_blockers", lambda chapter: [])


@pytest.fixture(autouse=True)
def _isolated_story_sandbox_checkpoint(monkeypatch, tmp_path):
    """start_story_sandbox_turn now calls snapshot_state for real on every call, whether or not
    a given test mocks it -- without this isolation, the tests below (start_story_sandbox_turn
    calls with run_story_sandbox_turn mocked but snapshot_state left real) would hit the real
    production checkpoint file, and leak the module-global checkpointer into
    tests/engine/story_sandbox/test_graph.py's own tmp_path-isolated tests running later in the
    same session (graph.ensure_checkpointer() only opens a new connection while it's still None)."""
    import asyncio

    monkeypatch.setattr(
        "utils.paths.story_sandbox_checkpoint_path", lambda: str(tmp_path / "sandbox.sqlite"),
    )
    yield
    from engine.story_sandbox.graph import close_checkpointer

    # asyncio.run() (not get_event_loop()) -- this file mixes sync and @pytest.mark.asyncio
    # tests, so by the time this autouse fixture's teardown runs, pytest-asyncio's own
    # function-scoped loop may already be gone, and get_event_loop() raises "no current event
    # loop" in that case. asyncio.run() always creates its own loop, sidestepping that entirely.
    asyncio.run(close_checkpointer())


@pytest.fixture(autouse=True)
def _isolated_sandbox_llm_routing(monkeypatch):
    """llm_params/sandbox_llm_params live in the live, gitignored
    config/pipelines/<id>/author_loop_skill_prefs.json. If a developer has a per-node local
    provider override configured there (e.g. routing the sandbox "prose" node to a local model),
    bind_node_llm swaps to that real client regardless of get_cloud_llm mocking (see
    bind_node_llm's provider=="local" branch) -- silently making guard/rewrite tests depend on
    whatever's on the machine. Stub load_dialogue_prefs to the defaults so they stay hermetic."""
    import engine.modes.author_loop_skill_prefs as prefs_mod

    monkeypatch.setattr(
        prefs_mod, "load_dialogue_prefs",
        lambda: {
            "target_words": prefs_mod.DEFAULT_TARGET_WORDS,
            "disabled_buildtime_review_hooks": [], "disabled_runtime_review_hooks": [],
            "llm_params": {}, "sandbox_llm_params": {},
        },
    )


# ── MessageHub ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hub_broadcast_appends_to_buffer():
    from api.services.message_hub import MessageHub
    hub = MessageHub()
    event = {"type": "step_start", "step": 1, "pipeline_id": "main"}
    await hub.broadcast(event)
    assert event in hub._gateway._buffer


@pytest.mark.asyncio
async def test_hub_broadcast_sends_to_ws_clients():
    from api.services.message_hub import MessageHub
    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    event = {"type": "step_done", "step": 1}
    await hub.broadcast(event)
    mock_ws.send_json.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_hub_broadcast_removes_dead_clients():
    from api.services.message_hub import MessageHub
    hub = MessageHub()
    mock_ws = AsyncMock()
    mock_ws.send_json.side_effect = Exception("connection closed")
    hub._gateway._ws_clients.append(mock_ws)
    await hub.broadcast({"type": "step_done", "step": 1})
    assert mock_ws not in hub._gateway._ws_clients


@pytest.mark.asyncio
async def test_hub_add_client_replays_buffer():
    from api.services.message_hub import MessageHub
    hub = MessageHub()
    hub._gateway._buffer = [
        {"type": "pipeline_start", "chapter": 5, "_seq": 1},
        {"type": "step_start", "step": 1, "_seq": 2},
    ]
    mock_ws = AsyncMock()
    await hub.add_client(mock_ws)
    assert mock_ws.send_json.call_count == 2


@pytest.mark.asyncio
async def test_hub_remove_client():
    from api.services.message_hub import MessageHub
    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    hub.remove_client(mock_ws)
    assert mock_ws not in hub._gateway._ws_clients


#──FastAPI endpoint testing────────────────────────────────────────────────────────

from fastapi.testclient import TestClient  # noqa: E402


def _make_client():
    """
Create a clean TestClient each time (isolating hub singleton state)."""
    import api.hub as mh
    from api.services.message_hub import MessageHub

    mh.HUB = MessageHub()
    from api.hub import app
    return TestClient(app, raise_server_exceptions=False)


def test_list_chapters_returns_plot_and_disk_union():
    client = _make_client()
    resp = client.get("/api/chapters")
    assert resp.status_code == 200
    chapters = resp.json()["chapters"]
    assert isinstance(chapters, list)
    assert len(chapters) >= 1
    assert all("chapter" in c for c in chapters)
    nums = [c["chapter"] for c in chapters]
    assert nums == sorted(nums)
    assert 999 not in nums


def test_list_chapters_includes_disk_only_when_progress_exists(tmp_path, monkeypatch):
    import api.services.pipeline_catalog as pc
    from api.services.pipeline_catalog import list_chapters
    from repo_test_helpers import seed_plot

    seed_plot([{"chapter": 1, "title": "A"}])

    ch_root = tmp_path / "chapters"
    orphan = ch_root / "第42章"
    orphan.mkdir(parents=True)
    (orphan / "temp").mkdir()
    (orphan / "temp" / ".pipeline_progress.json").write_text("{}", encoding="utf-8")
    (ch_root / "第999章").mkdir()

    monkeypatch.setattr(pc, "chapters_dir", lambda: ch_root)
    nums = [c["chapter"] for c in list_chapters()]
    assert 1 in nums
    assert 42 in nums
    assert 999 not in nums


def test_rest_start_author_loop_returns_200(monkeypatch):
    from api.services import message_hub as mh_mod

    monkeypatch.setattr(mh_mod.MessageHub, "start_author_loop", AsyncMock())
    client = _make_client()
    resp = client.post("/api/author-loop/start", json={"chapter": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["chapter"] == 2 and body["status"] == "running"


def test_rest_author_loop_journal_passes_novel_id(monkeypatch):
    from api.services import message_hub as mh_mod

    captured: dict = {}

    def fake_journal_events(self, chapter, novel_id=None):
        captured["chapter"] = chapter
        captured["novel_id"] = novel_id
        return []

    monkeypatch.setattr(mh_mod.MessageHub, "journal_events", fake_journal_events)
    client = _make_client()
    resp = client.get("/api/author-loop/journal?chapter=6&novel_id=abc")
    assert resp.status_code == 200
    assert captured == {"chapter": 6, "novel_id": "abc"}


def test_rest_author_loop_journal_novel_id_optional(monkeypatch):
    from api.services import message_hub as mh_mod

    captured: dict = {}

    def fake_journal_events(self, chapter, novel_id=None):
        captured["novel_id"] = novel_id
        return []

    monkeypatch.setattr(mh_mod.MessageHub, "journal_events", fake_journal_events)
    client = _make_client()
    resp = client.get("/api/author-loop/journal?chapter=6")
    assert resp.status_code == 200
    assert captured["novel_id"] is None


def test_rest_author_loop_status_returns_running_chapter(monkeypatch):
    from api.services import message_hub as mh_mod

    monkeypatch.setattr(mh_mod.MessageHub, "resumable_chapters", lambda self, novel_id=None: [3])
    monkeypatch.setattr(mh_mod.MessageHub, "running_author_loop_chapter", lambda self, novel_id=None: 5)
    client = _make_client()
    resp = client.get("/api/author-loop/status?novel_id=abc")
    assert resp.json() == {"resumable": [3], "running_chapter": 5}


def test_rest_author_loop_status_running_chapter_null_when_idle(monkeypatch):
    from api.services import message_hub as mh_mod

    monkeypatch.setattr(mh_mod.MessageHub, "resumable_chapters", lambda self, novel_id=None: [])
    monkeypatch.setattr(mh_mod.MessageHub, "running_author_loop_chapter", lambda self, novel_id=None: None)
    client = _make_client()
    resp = client.get("/api/author-loop/status")
    assert resp.json() == {"resumable": [], "running_chapter": None}


def test_rest_start_author_loop_rejects_bad_chapter():
    client = _make_client()
    resp = client.post("/api/author-loop/start", json={"chapter": 0})
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


@pytest.mark.asyncio
async def test_start_setup_chat_persists_user_msg_before_agent_build(monkeypatch, tmp_path):
    """The first message must be lazy to build persistence before the (slow) agent - otherwise the message will be lost during the build period refresh.

    Simulation agent build failure (slow/stuck): Even if the build throws an error, the user message should have been placed."""

    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub
    from engine.setup_chat.session_record import load_messages

    session_dir = str(tmp_path / "session")
    monkeypatch.setattr(mh_mod, "setup_chat_session_dir", lambda novel_id=None: session_dir)
    monkeypatch.setattr(mh_mod, "active_novel_id", lambda: "n")

    hub = MessageHub()

    async def boom_build(_novel_id: str):
        raise RuntimeError("agent 构建慢/失败")

    monkeypatch.setattr(hub, "_ensure_setup_chat_agent", boom_build)

    with pytest.raises(RuntimeError):
        await hub.start_setup_chat_turn("我的第一条消息")

    msgs = load_messages(session_dir)
    assert [m["content"] for m in msgs] == ["我的第一条消息"]  #Placed before construction


@pytest.mark.asyncio
async def test_start_setup_chat_turn_does_not_broadcast_image_start_at_turn_begin(monkeypatch, tmp_path):
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub
    from engine.setup_chat import attachments as attachments_mod

    session_dir = str(tmp_path / "session")
    monkeypatch.setattr(mh_mod, "setup_chat_session_dir", lambda novel_id=None: session_dir)
    monkeypatch.setattr(mh_mod, "active_novel_id", lambda: "n")

    attachments_mod._ATTACHMENTS.clear()
    attachments_mod._ATTACHMENTS["img-1"] = attachments_mod._Attachment(filename="page1.png", raw=b"x")
    attachments_mod._ATTACHMENTS["img-2"] = attachments_mod._Attachment(filename="page2.jpg", raw=b"x")
    attachments_mod._ATTACHMENTS["txt-1"] = attachments_mod._Attachment(filename="novel.txt", raw=b"x")

    hub = MessageHub()
    events = []

    async def fake_broadcast(ev):
        events.append(ev)

    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    async def boom_build(_novel_id: str):
        raise RuntimeError("stop before agent build")

    monkeypatch.setattr(hub, "_ensure_setup_chat_agent", boom_build)

    try:
        with pytest.raises(RuntimeError):
            await hub.start_setup_chat_turn("看看这些图", ["img-1", "img-2", "txt-1"])

        assert not any(e["type"] == "novel_import_image_start" for e in events)
        assert "n" not in hub._setup_chat_image_progress
    finally:
        attachments_mod._ATTACHMENTS.clear()


@pytest.mark.asyncio
async def test_start_setup_chat_turn_skips_image_start_without_images(monkeypatch, tmp_path):
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub

    session_dir = str(tmp_path / "session")
    monkeypatch.setattr(mh_mod, "setup_chat_session_dir", lambda novel_id=None: session_dir)
    monkeypatch.setattr(mh_mod, "active_novel_id", lambda: "n")

    hub = MessageHub()
    events = []

    async def fake_broadcast(ev):
        events.append(ev)

    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    async def boom_build(_novel_id: str):
        raise RuntimeError("stop before agent build")

    monkeypatch.setattr(hub, "_ensure_setup_chat_agent", boom_build)

    with pytest.raises(RuntimeError):
        await hub.start_setup_chat_turn("你好")

    assert not any(e["type"] == "novel_import_image_start" for e in events)
    assert "n" not in hub._setup_chat_image_progress


@pytest.mark.asyncio
async def test_advance_image_recognition_progress_broadcasts_and_marks_done(monkeypatch):
    from api.services.message_hub import MessageHub

    hub = MessageHub()
    events = []

    async def fake_broadcast(ev):
        events.append(ev)

    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    hub._setup_chat_image_progress["default"] = {"done": 0, "total": 2}

    await hub.advance_image_recognition_progress(ok=True)
    assert events == [
        {
            "type": "novel_import_image_progress",
            "index": 1,
            "total": 2,
            "ok": True,
            "error": None,
            "novel_id": "default",
        },
    ]

    await hub.advance_image_recognition_progress(ok=False, error="识别失败")
    assert events[1:] == [
        {
            "type": "novel_import_image_progress",
            "index": 2,
            "total": 2,
            "ok": False,
            "error": "识别失败",
            "novel_id": "default",
        },
        {"type": "novel_import_image_done", "novel_id": "default", "cancelled": False},
    ]
    assert "default" not in hub._setup_chat_image_progress


@pytest.mark.asyncio
async def test_begin_image_recognition_progress_broadcasts_start(monkeypatch):
    from api.services.message_hub import MessageHub

    hub = MessageHub()
    events = []

    async def fake_broadcast(ev):
        events.append(ev)

    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.begin_image_recognition_progress(3, novel_id="n1")
    assert hub._setup_chat_image_progress["n1"] == {"done": 0, "total": 3}
    assert events == [{"type": "novel_import_image_start", "total": 3, "novel_id": "n1"}]


@pytest.mark.asyncio
async def test_finish_incomplete_image_progress_broadcasts_cancelled_done(monkeypatch):
    from api.services.message_hub import MessageHub

    hub = MessageHub()
    events = []

    async def fake_broadcast(ev):
        events.append(ev)

    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    hub._setup_chat_image_progress["n1"] = {"done": 1, "total": 4}

    await hub._finish_incomplete_image_progress("n1")
    assert "n1" not in hub._setup_chat_image_progress
    assert events == [{"type": "novel_import_image_done", "novel_id": "n1", "cancelled": True}]


@pytest.mark.asyncio
async def test_advance_image_recognition_progress_noop_without_active_turn(monkeypatch):
    from api.services.message_hub import MessageHub

    hub = MessageHub()
    events = []

    async def fake_broadcast(ev):
        events.append(ev)

    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    assert "n" not in hub._setup_chat_image_progress

    await hub.advance_image_recognition_progress(ok=True)
    assert events == []


@pytest.mark.asyncio
async def test_clear_setup_chat_conversation_rejects_when_busy(monkeypatch):
    from api.services.message_hub import MessageHub

    class _FakeTask:
        def done(self) -> bool:
            return False

    hub = MessageHub()
    hub._setup_chat_tasks["default"] = _FakeTask()  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="对话进行中"):
        await hub.clear_setup_chat_conversation()


@pytest.mark.asyncio
async def test_clear_setup_chat_conversation_wipes_all_artifacts(monkeypatch, tmp_path):
    from api.services.message_hub import MessageHub

    chat_dir = tmp_path / "setup_chat"
    chat_dir.mkdir()
    (chat_dir / "checkpoint.sqlite").write_text("x")
    (chat_dir / "memory.json").write_text("{}")
    (chat_dir / "construction_plan.json").write_text("{}")
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    (session_dir / "messages.json").write_text("[]")

    monkeypatch.setattr("api.services.message_hub.setup_chat_dir", lambda: str(chat_dir))
    monkeypatch.setattr("api.services.message_hub.setup_chat_session_dir", lambda novel_id=None: str(session_dir))

    hub = MessageHub()
    await hub.clear_setup_chat_conversation()

    assert not chat_dir.exists()
    assert not (session_dir / "messages.json").exists()


@pytest.mark.asyncio
async def test_clear_setup_chat_conversation_empties_session_message_table(monkeypatch, tmp_path):
    """Root-cause regression test: session history now lives in the per-novel SQLite
    session_messages table (see engine.setup_chat.session_record), not messages.json --
    deleting only the legacy JSON file left old messages resurfacing after a page reload.
    See docs bug: "清空对话" appeared to work but a refresh brought the old messages back."""
    from api.services.message_hub import MessageHub
    from engine.setup_chat.session_record import append_assistant, append_user, load_messages

    chat_dir = tmp_path / "setup_chat"
    chat_dir.mkdir()
    (chat_dir / "checkpoint.sqlite").write_text("x")
    session_dir = tmp_path / "session"
    session_dir.mkdir()

    monkeypatch.setattr("api.services.message_hub.setup_chat_dir", lambda: str(chat_dir))
    monkeypatch.setattr("api.services.message_hub.setup_chat_session_dir", lambda novel_id=None: str(session_dir))

    append_user(str(session_dir), "你好")
    append_assistant(str(session_dir), "您好，请问设定方向？")
    assert load_messages(str(session_dir)) != []

    hub = MessageHub()
    await hub.clear_setup_chat_conversation()

    assert load_messages(str(session_dir)) == []


@pytest.mark.asyncio
async def test_clear_setup_chat_conversation_wipes_long_term_memory(monkeypatch, tmp_path):
    """Root-cause regression test: long-term memory (setup-chat's "decisions" distillation)
    now lives in the per-novel chronos.sqlite3 documents table (see engine.setup_chat.memory),
    not setup_chat/memory.json -- deleting only the setup_chat directory left old decisions
    resurfacing (re-injected into every new conversation's context) after "清空对话"."""
    from api.services.message_hub import MessageHub
    from engine.setup_chat.memory import load_memory, save_memory

    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    novel_dir = tmp_path / "n1"
    chat_dir = novel_dir / "setup_chat"
    chat_dir.mkdir(parents=True)
    (chat_dir / "checkpoint.sqlite").write_text("x")
    session_dir = novel_dir / "session"
    session_dir.mkdir()

    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "n1")
    monkeypatch.setattr("api.services.message_hub.setup_chat_dir", lambda: str(chat_dir))
    monkeypatch.setattr("api.services.message_hub.setup_chat_session_dir", lambda novel_id=None: str(session_dir))

    save_memory(str(chat_dir), {"decisions": ["用户定了主角叫阿三"]})
    assert load_memory(str(chat_dir))["decisions"] != []

    hub = MessageHub()
    await hub.clear_setup_chat_conversation()

    assert load_memory(str(chat_dir))["decisions"] == []


@pytest.mark.asyncio
async def test_clear_setup_chat_conversation_background_deletes_trash(monkeypatch, tmp_path):
    """After rename, background rmtree must remove the trash path so nothing under tmp_path
    remains with a setup_chat / .trash- prefix."""
    from api.services.message_hub import MessageHub

    chat_dir = tmp_path / "setup_chat"
    chat_dir.mkdir()
    (chat_dir / "checkpoint.sqlite").write_text("x")
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    (session_dir / "messages.json").write_text("[]")

    monkeypatch.setattr("api.services.message_hub.setup_chat_dir", lambda: str(chat_dir))
    monkeypatch.setattr("api.services.message_hub.setup_chat_session_dir", lambda novel_id=None: str(session_dir))

    hub = MessageHub()
    await hub.clear_setup_chat_conversation()
    await hub.wait_for_pending_background_tasks()

    leftovers = [
        p for p in tmp_path.iterdir()
        if p.name.startswith("setup_chat") or ".trash-" in p.name
    ]
    assert leftovers == []


@pytest.mark.asyncio
async def test_clear_setup_chat_conversation_noop_when_nothing_to_delete(monkeypatch, tmp_path):
    """Fresh novel that never had a setup-chat conversation → nothing on disk yet; must not raise."""
    from api.services.message_hub import MessageHub

    chat_dir = tmp_path / "setup_chat"        # never created
    session_dir = tmp_path / "session"        # never created
    monkeypatch.setattr("api.services.message_hub.setup_chat_dir", lambda: str(chat_dir))
    monkeypatch.setattr("api.services.message_hub.setup_chat_session_dir", lambda novel_id=None: str(session_dir))

    hub = MessageHub()
    await hub.clear_setup_chat_conversation()  # must not raise


@pytest.mark.asyncio
async def test_clear_setup_chat_conversation_retries_transient_rename_failure(monkeypatch, tmp_path):
    """os.rename can transiently fail right after closing an aiosqlite connection on Windows --
    the background worker thread's OS-level file handle release can lag a beat behind the
    awaited close() returning. Must retry instead of silently believing a clear succeeded."""
    import api.services.message_hub as hub_mod

    chat_dir = tmp_path / "setup_chat"
    chat_dir.mkdir()
    (chat_dir / "checkpoint.sqlite").write_text("x")
    session_dir = tmp_path / "session"
    session_dir.mkdir()

    monkeypatch.setattr(hub_mod, "setup_chat_dir", lambda: str(chat_dir))
    monkeypatch.setattr(hub_mod, "setup_chat_session_dir", lambda novel_id=None: str(session_dir))
    monkeypatch.setattr(hub_mod.asyncio, "sleep", AsyncMock())  # don't actually wait in tests

    calls = {"n": 0}
    real_rename = hub_mod.os.rename

    def _flaky_rename(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("file in use")
        real_rename(src, dst)

    monkeypatch.setattr(hub_mod.os, "rename", _flaky_rename)

    hub = hub_mod.MessageHub()
    await hub.clear_setup_chat_conversation()

    assert calls["n"] == 3
    assert not chat_dir.exists()

    await hub.wait_for_pending_background_tasks()
    trash_left = [
        p for p in chat_dir.parent.iterdir()
        if ".trash-" in p.name
    ]
    assert trash_left == []


@pytest.mark.asyncio
async def test_clear_setup_chat_conversation_raises_when_rename_never_succeeds(monkeypatch, tmp_path):
    """If the file handle never releases, surface a real error instead of a false-success."""
    import api.services.message_hub as hub_mod

    chat_dir = tmp_path / "setup_chat"
    chat_dir.mkdir()
    (chat_dir / "checkpoint.sqlite").write_text("x")
    session_dir = tmp_path / "session"
    session_dir.mkdir()

    monkeypatch.setattr(hub_mod, "setup_chat_dir", lambda: str(chat_dir))
    monkeypatch.setattr(hub_mod, "setup_chat_session_dir", lambda novel_id=None: str(session_dir))
    monkeypatch.setattr(hub_mod.asyncio, "sleep", AsyncMock())

    def _always_locked(src, dst):
        raise PermissionError("file in use")

    monkeypatch.setattr(hub_mod.os, "rename", _always_locked)

    hub = hub_mod.MessageHub()
    with pytest.raises(RuntimeError, match="清空失败"):
        await hub.clear_setup_chat_conversation()
    assert chat_dir.exists()  # untouched -- honest about the failure


@pytest.mark.asyncio
async def test_clear_setup_chat_conversation_closes_agent_connection(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock

    from api.services.message_hub import MessageHub

    chat_dir = tmp_path / "setup_chat"
    chat_dir.mkdir()
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    monkeypatch.setattr("api.services.message_hub.setup_chat_dir", lambda: str(chat_dir))
    monkeypatch.setattr("api.services.message_hub.setup_chat_session_dir", lambda novel_id=None: str(session_dir))

    class _FakeConn:
        def __init__(self) -> None:
            self.close = AsyncMock()

    class _FakeCheckpointer:
        def __init__(self, conn: _FakeConn) -> None:
            self.conn = conn

    class _FakeAgent:
        def __init__(self, conn: _FakeConn) -> None:
            self.checkpointer = _FakeCheckpointer(conn)

    conn = _FakeConn()
    hub = MessageHub()
    hub._setup_chat_agents["default"] = _FakeAgent(conn)  # type: ignore[assignment]

    await hub.clear_setup_chat_conversation()

    conn.close.assert_awaited_once()
    assert "default" not in hub._setup_chat_agents


@pytest.mark.asyncio
async def test_author_loop_done_auto_saves_manuscript(monkeypatch):
    """author_loop_done 一发出就应立即落盘成稿，不依赖任何前端会话——修复"主笔写完成稿 tab
    看不到"的根因：此前保存完全靠前端 listeners.ts 里的 liveRun 会话监听器触发一次 REST
    调用，页面刷新/关闭会让 liveRun 状态丢失，任务本身在服务端照常跑完但没人调用保存。"""
    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    from api.services.message_hub import MessageHub

    saved = []

    def fake_save(chapter):
        saved.append(chapter)
        return f"/fake/path/ch{chapter}.md"

    monkeypatch.setattr("engine.author_loop.build.save_author_loop_chapter", fake_save)

    async def fake_dialogue(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        pass  # 不自己 emit -> _run 的兜底逻辑会补发 author_loop_done

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", fake_dialogue)
    hub = MessageHub()
    await hub.start_author_loop(5)
    if (_t := hub._author_tasks.get("default")) is not None:
        await _t

    assert saved == [5]


@pytest.mark.asyncio
async def test_author_loop_done_auto_save_failure_does_not_break_completion(monkeypatch):
    """落盘失败（比如章节确实没产出）只记警告，不阻断 author_loop_done 正常发出。
    Checked via a live-connected client's send_json calls, not the replay buffer -- terminal
    events (done/error/stopped) are transient by design (see gateway.py's
    _TERMINAL_AUTHOR_LOOP_EVENT_TYPES), so they never sit in hub._gateway._buffer at all."""
    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    from api.services.message_hub import MessageHub

    def boom(chapter):
        raise ValueError("该章暂无主笔产出，无法保存")

    monkeypatch.setattr("engine.author_loop.build.save_author_loop_chapter", boom)

    async def fake_dialogue(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        pass

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", fake_dialogue)
    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_author_loop(5)
    if (_t := hub._author_tasks.get("default")) is not None:
        await _t

    sent = [c.args[0] for c in mock_ws.send_json.call_args_list]
    dones = [e for e in sent if e.get("type") == "author_loop_done"]
    assert len(dones) == 1


@pytest.mark.asyncio
async def test_hub_start_author_loop_creates_then_clears_task(monkeypatch):
    """
start_author_loop starts the background task and runs run_dialogue_chapter, and clears _author_task after completion."""
    from unittest.mock import AsyncMock as _AM

    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    from api.services.message_hub import MessageHub

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", _AM(return_value=None))
    hub = MessageHub()
    mock_ws = _AM()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_author_loop(3)
    assert "default" in hub._author_tasks
    if (_t := hub._author_tasks.get("default")) is not None:
        await _t  #Wait for the task to finish
    # 不读 hub._gateway._buffer -- author_loop_done 一发出就会把这轮自己的 author_loop_start
    # 等旧里程碑一起从缓冲区里修剪掉（见 gateway.py 的 _prune_novel_buffer），改从实际送达
    # 已连接客户端的事件里找。
    sent = [c.args[0] for c in mock_ws.send_json.call_args_list]
    starts = [e for e in sent if e.get("type") == "author_loop_start"]
    assert len(starts) == 1
    assert starts[0]["chapter"] == 3
    assert starts[0]["resume"] is False
    assert "default" not in hub._author_tasks  #finally self-cleaning


@pytest.mark.asyncio
async def test_hub_stop_author_loop_cancels_task_and_broadcasts(monkeypatch):
    """stop_author_loop cancels running background tasks, clears status, and broadcasts author_loop_stopped."""
    import asyncio as _aio

    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    from api.services.message_hub import MessageHub

    async def never_ends(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        await _aio.sleep(3600)  #simulate long distance running

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", never_ends)
    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_author_loop(2)
    assert "default" in hub._author_tasks
    await hub.stop_author_loop()
    assert "default" not in hub._author_tasks
    # author_loop_stopped is transient (see gateway.py's _TERMINAL_AUTHOR_LOOP_EVENT_TYPES) --
    # it's still broadcast live, just never sits in hub._gateway._buffer.
    sent = [c.args[0] for c in mock_ws.send_json.call_args_list]
    assert any(e.get("type") == "author_loop_stopped" for e in sent)


@pytest.mark.asyncio
async def test_hub_stop_author_loop_noop_when_idle():
    from api.services.message_hub import MessageHub
    hub = MessageHub()
    await hub.stop_author_loop()  #No running task → no crash, no broadcast
    assert not any(e.get("type") == "author_loop_stopped" for e in hub._gateway._buffer)


#── Interrupt/resume: journal drop + resumable + start remount ───────────────────────────


@pytest.mark.asyncio
async def test_emit_writes_journal(monkeypatch, tmp_path):
    """
Milestone _emit drops journal NDJSON."""
    import api.services.message_hub as mh_mod
    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    from api.services.message_hub import MessageHub

    jpath = str(tmp_path / "j.ndjson")
    monkeypatch.setattr(mh_mod, "author_loop_journal_path", lambda ch: jpath)

    async def fake_dialogue(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        await emit({"type": "author_loop_segment", "index": 0, "text": "x"})

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", fake_dialogue)
    hub = MessageHub()
    await hub.start_author_loop(6)
    if (_t := hub._author_tasks.get("default")) is not None:
        await _t

    from engine.author_loop.journal import load_events
    evs = load_events(jpath)
    types = [e["type"] for e in evs]
    assert "author_loop_segment" in types


def test_resumable_chapters_lists_chapters_with_checkpoint(monkeypatch, tmp_path):
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub

    monkeypatch.setattr(mh_mod, "_scan_resumable", lambda: [6])
    hub = MessageHub()
    assert hub.resumable_chapters() == [6]


def test_startup_does_not_flood_buffer(monkeypatch):
    """When the application starts, all chapters in progress are no longer filled into the buffer (the front end is changed to on-demand REST pull to avoid cross-client pollution/serialization)."""
    import api.hub as hub_mod
    from api.services.message_hub import MessageHub

    hub_mod.HUB = MessageHub()
    monkeypatch.setattr(hub_mod.HUB, "resumable_chapters", lambda: [6, 7])
    # register_startup_warmup (api/hub.py::_lifespan) now schedules real
    # build_agent()/ensure_checkpointer() calls at startup -- stub both out here so this test
    # doesn't pay that cost / doesn't leak a real sqlite connection (or, if SCHEDULER.stop()
    # cancels the build task on TestClient __exit__, a stale cancelled asyncio.Task) into
    # graph.py's module-level checkpointer-building guard, which would otherwise poison later
    # tests in this same pytest process that call the real ensure_checkpointer().
    monkeypatch.setattr(hub_mod.HUB, "_ensure_setup_chat_agent", AsyncMock())
    monkeypatch.setattr(hub_mod.HUB, "_ensure_story_sandbox_checkpointer", AsyncMock())

    with TestClient(hub_mod.app):  #trigger lifespan startup
        pass
    #The startup should not fill any primary events into the buffer.
    assert not any(e.get("type", "").startswith("author_loop_") for e in hub_mod.HUB._gateway._buffer)


def test_journal_events_ends_non_running(monkeypatch, tmp_path):
    """
On-demand journal: history of interruptions (with start but no final state). The stopped final state is added at the end to avoid the illusion of "writing" on the front end.
    And does not touch the global buffer."""
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub
    from engine.author_loop.journal import append_event

    jpath = str(tmp_path / "j.ndjson")
    append_event(jpath, {"type": "author_loop_start", "chapter": 6})
    append_event(jpath, {"type": "author_loop_skeleton", "total": 1})
    monkeypatch.setattr(mh_mod, "author_loop_journal_path", lambda ch: jpath)

    hub = MessageHub()
    evs = hub.journal_events(6)
    types = [e["type"] for e in evs]
    assert "author_loop_skeleton" in types
    assert types[-1] == "author_loop_stopped"   #The ending is not running → the front end falls into idle
    assert hub._gateway._buffer == []                     #Does not pollute the global buffer


def test_journal_events_empty_returns_empty(monkeypatch, tmp_path):
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub

    monkeypatch.setattr(mh_mod, "author_loop_journal_path", lambda ch: str(tmp_path / "none.ndjson"))
    hub = MessageHub()
    assert hub.journal_events(6) == []   #no journal → empty


@pytest.mark.asyncio
async def test_author_loop_journal_includes_live_tail_mid_run(monkeypatch, tmp_path):
    """journal_events() mid-run: the tail of events broadcast since the last milestone
    (token/progress, not yet journaled) is appended -- no synthetic author_loop_stopped."""
    import asyncio as _aio

    import api.services.message_hub as mh_mod
    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    from api.services.message_hub import MessageHub

    jpath = str(tmp_path / "j.ndjson")
    monkeypatch.setattr(mh_mod, "author_loop_journal_path", lambda ch: jpath)

    paused = _aio.Event()
    resume_gate = _aio.Event()

    async def fake_dialogue(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        await emit({"type": "author_loop_token", "agent": "director", "delta": "他抬起头"})
        await emit({"type": "author_loop_progress", "agent": "write", "attempt": 1, "attempts": 1})
        paused.set()
        await resume_gate.wait()

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", fake_dialogue)
    hub = MessageHub()
    await hub.start_author_loop(6)
    await paused.wait()

    events = hub.journal_events(6, novel_id="default")
    types = [e["type"] for e in events]
    assert types == ["author_loop_start", "author_loop_token", "author_loop_progress"]
    assert "author_loop_stopped" not in types

    resume_gate.set()
    await hub._author_tasks["default"]


@pytest.mark.asyncio
async def test_author_loop_journal_clears_live_tail_on_milestone(monkeypatch, tmp_path):
    """A milestone event (author_loop_segment etc.) flushes the live tail -- the milestone
    itself lives in the journal, not duplicated into the live cache."""
    import asyncio as _aio

    import api.services.message_hub as mh_mod
    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    from api.services.message_hub import MessageHub

    jpath = str(tmp_path / "j.ndjson")
    monkeypatch.setattr(mh_mod, "author_loop_journal_path", lambda ch: jpath)

    paused = _aio.Event()
    resume_gate = _aio.Event()

    async def fake_dialogue(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        await emit({"type": "author_loop_token", "agent": "director", "delta": "x"})
        await emit({"type": "author_loop_segment", "index": 0, "text": "final", "total": 1})
        paused.set()
        await resume_gate.wait()

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", fake_dialogue)
    hub = MessageHub()
    await hub.start_author_loop(6)
    await paused.wait()

    assert hub._author_loop_live["default"]["events"] == []
    events = hub.journal_events(6, novel_id="default")
    assert events[-1]["type"] == "author_loop_segment"

    resume_gate.set()
    await hub._author_tasks["default"]


@pytest.mark.asyncio
async def test_author_loop_live_cleared_after_run_completes(monkeypatch, tmp_path):
    import api.services.message_hub as mh_mod
    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    from api.services.message_hub import MessageHub

    jpath = str(tmp_path / "j.ndjson")
    monkeypatch.setattr(mh_mod, "author_loop_journal_path", lambda ch: jpath)

    async def fake_dialogue(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        await emit({"type": "author_loop_segment", "index": 0, "text": "x", "total": 1})

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", fake_dialogue)
    hub = MessageHub()
    await hub.start_author_loop(6)
    if (_t := hub._author_tasks.get("default")) is not None:
        await _t
    assert "default" not in hub._author_loop_live


@pytest.mark.asyncio
async def test_running_author_loop_chapter_reflects_active_task(monkeypatch):
    import asyncio as _aio

    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    from api.services.message_hub import MessageHub

    async def never_ends(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        await _aio.sleep(3600)

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", never_ends)
    hub = MessageHub()
    assert hub.running_author_loop_chapter("default") is None
    await hub.start_author_loop(4)
    assert hub.running_author_loop_chapter("default") == 4
    await hub.stop_author_loop()
    assert hub.running_author_loop_chapter("default") is None


def test_journal_events_novel_id_defaults_to_active(monkeypatch, tmp_path):
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub

    monkeypatch.setattr(mh_mod, "author_loop_journal_path", lambda ch: str(tmp_path / "none.ndjson"))
    hub = MessageHub()
    assert hub.journal_events(6, novel_id="default") == hub.journal_events(6)


def test_resumable_chapters_accepts_explicit_novel_id(monkeypatch, tmp_path):
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub

    monkeypatch.setattr(mh_mod, "_scan_resumable", lambda: [6])
    hub = MessageHub()
    assert hub.resumable_chapters("default") == [6]


def test_rest_resume_author_loop(monkeypatch):
    from api.services import message_hub as mh_mod

    called: dict = {}

    async def fake_start(self, chapter, resume=False):
        called["chapter"] = chapter
        called["resume"] = resume

    monkeypatch.setattr(mh_mod.MessageHub, "start_author_loop", fake_start)
    client = _make_client()
    resp = client.post("/api/author-loop/resume", json={"chapter": 6})
    assert resp.status_code == 200 and resp.json()["ok"] is True
    assert called == {"chapter": 6, "resume": True}


def test_rest_status_includes_resumable(monkeypatch):
    from api.services import message_hub as mh_mod

    monkeypatch.setattr(mh_mod.MessageHub, "resumable_chapters", lambda self, novel_id=None: [6])
    monkeypatch.setattr(mh_mod.MessageHub, "running_author_loop_chapter", lambda self, novel_id=None: None)
    client = _make_client()
    resp = client.get("/api/author-loop/status")
    assert resp.status_code == 200
    assert 6 in resp.json().get("resumable", [])

def test_rest_stop_author_loop_returns_ok(monkeypatch):
    from api.services import message_hub as mh_mod

    monkeypatch.setattr(mh_mod.MessageHub, "stop_author_loop", AsyncMock())
    client = _make_client()
    resp = client.post("/api/author-loop/stop")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "status": "stopped"}


def test_rest_save_author_loop_returns_path(monkeypatch):
    import engine.author_loop.build as build_mod

    monkeypatch.setattr(build_mod, "save_author_loop_chapter", lambda ch: f"/x/第{ch}章_主笔.md")
    client = _make_client()
    resp = client.post("/api/author-loop/save", json={"chapter": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["path"].endswith("第5章_主笔.md")


def test_rest_save_author_loop_empty_returns_400(monkeypatch):
    import engine.author_loop.build as build_mod

    def _boom(ch):
        raise ValueError("该章暂无主笔产出，无法保存")

    monkeypatch.setattr(build_mod, "save_author_loop_chapter", _boom)
    client = _make_client()
    resp = client.post("/api/author-loop/save", json={"chapter": 5})
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


def test_clear_chapter_disk_removes_all_md_including_legacy(tmp_path, monkeypatch):
    import api.services.pipeline_catalog as pc

    monkeypatch.setattr(pc, "chapters_dir", lambda: tmp_path / "chapters")
    ch_dir = tmp_path / "chapters" / "第6章"
    ch_dir.mkdir(parents=True)
    (ch_dir / "第6章_01_current.md").write_text("current", encoding="utf-8")
    (ch_dir / "第6章_99_legacy_pipeline.md").write_text("legacy", encoding="utf-8")
    (ch_dir / "temp").mkdir()
    (ch_dir / "temp" / ".pipeline_progress.json").write_text("{}", encoding="utf-8")
    (ch_dir / "characters").mkdir()
    archive = ch_dir / "characters" / "男主甲_ch06_archive.json"
    archive.write_text('{"name": "男主甲"}', encoding="utf-8")

    pc.clear_chapter_disk(6)

    assert list(ch_dir.rglob("*.md")) == []
    assert not (ch_dir / "temp").exists()
    assert archive.exists()
    assert archive.read_text(encoding="utf-8") == '{"name": "男主甲"}'


def test_reset_chapter_returns_ok(monkeypatch):
    import api.services.pipeline_catalog as pc
    from api.services import message_hub as mh_mod

    stop_mock = AsyncMock()
    monkeypatch.setattr(mh_mod.MessageHub, "stop_all_pipelines", stop_mock)
    monkeypatch.setattr(pc, "clear_chapter_disk", lambda _chapter: None)
    monkeypatch.setattr("domain.usage.clear_chapter_usage", lambda _chapter: None)
    client = _make_client()
    resp = client.post("/api/chapters/1/reset")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    stop_mock.assert_awaited_once()


def test_reset_chapter_disk_error_returns_structured_500(monkeypatch):
    import api.services.pipeline_catalog as pc
    from api.services import message_hub as mh_mod

    monkeypatch.setattr(mh_mod.MessageHub, "stop_all_pipelines", AsyncMock())

    def _boom(_chapter: int) -> None:
        raise OSError("file in use")

    monkeypatch.setattr(pc, "clear_chapter_disk", _boom)
    client = _make_client()
    resp = client.post("/api/chapters/2/reset")
    assert resp.status_code == 500
    body = resp.json()
    assert body["ok"] is False
    assert "file in use" in body["error"]


def test_ws_connect_and_receive_replay():
    import api.hub as mh
    from api.services.message_hub import MessageHub

    mh.HUB = MessageHub()
    # Pre-populate buffer with a fake event
    mh.HUB._gateway._buffer = [{"type": "step_done", "step": 1, "_seq": 1}]
    from api.hub import app
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        # Should immediately receive the buffered event as replay
        data = ws.receive_json()
        assert data["type"] == "step_done"
        assert data["step"] == 1



#──Final status: _run Any non-cancel exit will ensure that the UI will jump out of running ──────────────────────────


@pytest.mark.asyncio
async def test_hub_run_backstops_error_when_dialogue_emits_nothing(monkeypatch):
    """
dialogue throws an exception but does not emit the final state → _run finally reissues author_loop_error (to prevent silent stuck)."""
    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    from api.services.message_hub import MessageHub

    async def silent_boom(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        raise RuntimeError("内层炸了但没 emit")

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", silent_boom)
    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_author_loop(1)
    if (_t := hub._author_tasks.get("default")) is not None:
        await _t
    # author_loop_error is transient (see gateway.py) -- check live delivery, not the buffer.
    sent = [c.args[0] for c in mock_ws.send_json.call_args_list]
    errs = [e for e in sent if e.get("type") == "author_loop_error"]
    assert len(errs) == 1 and "异常退出" in errs[0]["error"]


@pytest.mark.asyncio
async def test_hub_run_no_double_error_when_dialogue_already_emitted(monkeypatch):
    """dialogue has been emitted author_loop_error → will not be reissued (it will only be triggered when it is not sent)."""
    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    from api.services.message_hub import MessageHub

    async def emit_then_raise(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        await emit({"type": "author_loop_error", "error": "真错误"})
        raise RuntimeError("已 emit")

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", emit_then_raise)
    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_author_loop(1)
    if (_t := hub._author_tasks.get("default")) is not None:
        await _t
    sent = [c.args[0] for c in mock_ws.send_json.call_args_list]
    errs = [e for e in sent if e.get("type") == "author_loop_error"]
    assert len(errs) == 1 and errs[0]["error"] == "真错误"


@pytest.mark.asyncio
async def test_hub_run_no_backstop_error_on_stop(monkeypatch):
    """
Actively stop (cancel) → only author_loop_stopped, no error will be reissued."""
    import asyncio as _aio

    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    from api.services.message_hub import MessageHub

    async def never_ends(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        await _aio.sleep(3600)

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", never_ends)
    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_author_loop(1)
    await hub.stop_author_loop()
    sent = [c.args[0] for c in mock_ws.send_json.call_args_list]
    assert not any(e.get("type") == "author_loop_error" for e in sent)
    assert any(e.get("type") == "author_loop_stopped" for e in sent)


def _style_rewrite_events(events: list[dict]) -> list[dict]:
    return [
        {k: v for k, v in e.items() if k != "_seq"}
        for e in events if e.get("type") == "author_loop_style_rewrite"
    ]


@pytest.mark.asyncio
async def test_message_hub_call_llm_style_rewrite_broadcasts_start_end(monkeypatch):
    """tagged _call_llm path: style-guard rewrite emits start/end WS events with agent."""
    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub

    patterns = style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`")
    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: patterns)

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            for ch in "他不是喜欢她，而是习惯了。":
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            return _Resp("他其实很在意她。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    async def fake_dialogue(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        await call_llm("system", "user", tag="synthesis", _log_step=0, _log_agent="director")

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", fake_dialogue)

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_author_loop(9)
    if (_t := hub._author_tasks.get("default")) is not None:
        await _t

    # author_loop_done (broadcast right after these) prunes this run's own buffered
    # author_loop_style_rewrite milestones too -- check what was actually delivered live to a
    # connected client, not the post-completion (now-pruned) buffer.
    sent = [c.args[0] for c in mock_ws.send_json.call_args_list]
    events = _style_rewrite_events(sent)
    assert events == [
        {"type": "author_loop_style_rewrite", "status": "start", "agent": "director", "role": None, "novel_id": "default"},
        {"type": "author_loop_style_rewrite", "status": "end", "agent": "director", "role": None, "novel_id": "default"},
    ]


@pytest.mark.asyncio
async def test_message_hub_prose_turn_style_rewrite_broadcasts_start_end(monkeypatch):
    """_HubAuthorTurns.prose_turn path: style-guard rewrite emits start/end with agent=synthesis."""
    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub

    patterns = style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`")
    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: patterns)

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _BoundLLM:
        def __init__(self, llm: "_FakeLLM") -> None:
            self._llm = llm

        async def astream(self, msgs, stream_usage=False):
            async for ch in self._llm.astream(msgs, stream_usage=stream_usage):
                yield ch

        async def ainvoke(self, msgs):
            return await self._llm.ainvoke(msgs)

    class _FakeLLM:
        model = "fake"

        def bind(self, **kwargs):
            return _BoundLLM(self)

        async def astream(self, msgs, stream_usage=False):
            for ch in "他不是喜欢她，而是习惯了。":
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            return _Resp("他其实很在意她。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"llm_params": {"director": {"temperature": 0.8}}},
    )

    async def fake_dialogue(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        class _Msg:
            def __init__(self, content: str) -> None:
                self.content = content

        await author_turns.prose_turn([_Msg("sys"), _Msg("user")], step=0)

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", fake_dialogue)

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_author_loop(9)
    if (_t := hub._author_tasks.get("default")) is not None:
        await _t

    sent = [c.args[0] for c in mock_ws.send_json.call_args_list]
    events = _style_rewrite_events(sent)
    assert events == [
        {"type": "author_loop_style_rewrite", "status": "start", "agent": "synthesis", "role": None, "novel_id": "default"},
        {"type": "author_loop_style_rewrite", "status": "end", "agent": "synthesis", "role": None, "novel_id": "default"},
    ]


@pytest.mark.asyncio
async def test_message_hub_prose_turn_skips_guard_when_disabled(monkeypatch):
    """director's disable_style_guard=True bypasses guarded_stream entirely -- banned-pattern
    text passes through unmodified and no style_rewrite events fire."""
    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub

    patterns = style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`")
    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: patterns)

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _BoundLLM:
        def __init__(self, llm: "_FakeLLM") -> None:
            self._llm = llm

        async def astream(self, msgs, stream_usage=False):
            async for ch in self._llm.astream(msgs, stream_usage=stream_usage):
                yield ch

        async def ainvoke(self, msgs):
            return await self._llm.ainvoke(msgs)

    class _FakeLLM:
        model = "fake"

        def bind(self, **kwargs):
            return _BoundLLM(self)

        async def astream(self, msgs, stream_usage=False):
            for ch in "他不是喜欢她，而是习惯了。":
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            raise AssertionError("rewrite must not be called when disable_style_guard is set")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"llm_params": {"director": {"disable_style_guard": True}}},
    )

    captured: dict = {}

    async def fake_dialogue(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        class _Msg:
            def __init__(self, content: str) -> None:
                self.content = content

        captured["text"] = await author_turns.prose_turn([_Msg("sys"), _Msg("user")], step=0)

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", fake_dialogue)

    hub = MessageHub()
    await hub.start_author_loop(9)
    if (_t := hub._author_tasks.get("default")) is not None:
        await _t

    assert captured["text"] == "他不是喜欢她，而是习惯了。"  # unrewritten -- guard bypassed
    events = _style_rewrite_events(hub._gateway._buffer)
    assert events == []


@pytest.mark.asyncio
async def test_message_hub_guards_director_stream_and_rewrites_violation(monkeypatch):
    """director 流式输出命中禁用句式 → guarded_stream 触发局部重写，
    最终广播的 delta 拼起来不再含被禁句式，且重写走真实 prompt_logger 记录。"""
    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub

    patterns = style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`")
    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: patterns)

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            for ch in "他不是喜欢她，而是习惯了。":
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            return _Resp("他其实很在意她。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    captured: dict = {}

    async def fake_dialogue(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        text, _, _ = await call_llm(
            "system", "user", tag="synthesis", _log_step=0, _log_agent="director",
        )
        captured["text"] = text

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", fake_dialogue)

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_author_loop(9)
    if (_t := hub._author_tasks.get("default")) is not None:
        await _t

    result_text = captured["text"]
    assert "不是" not in result_text
    assert "他其实很在意她。" in result_text

    deltas = "".join(
        call.args[0]["delta"]
        for call in mock_ws.send_json.call_args_list
        if call.args[0].get("type") == "author_loop_token"
    )
    assert deltas == result_text


@pytest.mark.asyncio
async def test_message_hub_style_rewrite_uses_style_guard_llm_not_stream_llm(monkeypatch):
    """Guard rewrites must not inherit the streaming node's thinking-enabled client."""
    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub

    patterns = style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`")
    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: patterns)

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _StreamLLM:
        model = "director-thinking"

        async def astream(self, msgs, stream_usage=False):
            for ch in "他不是喜欢她，而是习惯了。":
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            raise AssertionError("rewrite must use style_guard_llm, not the streaming node client")

    class _GuardLLM:
        model = "style-guard-fast"

        async def ainvoke(self, msgs):
            return _Resp("他其实很在意她。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _StreamLLM())
    monkeypatch.setattr("llm.factory.get_style_guard_llm", lambda: _GuardLLM())

    captured: dict = {}

    async def fake_dialogue(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        text, _, _ = await call_llm(
            "system", "user", tag="synthesis", _log_step=0, _log_agent="director",
        )
        captured["text"] = text

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", fake_dialogue)

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_author_loop(9)
    if (_t := hub._author_tasks.get("default")) is not None:
        await _t

    assert "他其实很在意她。" in captured["text"]


@pytest.mark.asyncio
async def test_message_hub_guard_exhausted_logs_and_passes_through(monkeypatch):
    """重写 2 次仍命中 → 耗尽不再回退，接受最后一次重写产出，且 prompt_logger 记一条 style_guard_exhausted。"""
    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub

    patterns = style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`")
    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: patterns)

    original = "他不是喜欢她，而是习惯了。"

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            for ch in original:
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            return _Resp("还是不是喜欢她，而是习惯了。")  #重写仍命中同款句式

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    logged_events: list[dict] = []
    import llm.prompt_logger as pl_mod
    original_log_event = pl_mod.PromptLogger.log_event

    def _capture_log_event(self, event_type, **kwargs):
        logged_events.append({"type": event_type, **kwargs})
        return original_log_event(self, event_type, **kwargs)

    monkeypatch.setattr(pl_mod.PromptLogger, "log_event", _capture_log_event)

    captured: dict = {}

    async def fake_dialogue(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        text, _, _ = await call_llm(
            "system", "user", tag="synthesis", _log_step=0, _log_agent="director",
        )
        captured["text"] = text

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", fake_dialogue)

    hub = MessageHub()
    await hub.start_author_loop(10)
    if (_t := hub._author_tasks.get("default")) is not None:
        await _t

    assert captured["text"] == "还是不是喜欢她，而是习惯了。"  # 耗尽不再回退，接受最后一次重写产出
    exhausted = [e for e in logged_events if e["type"] == "style_guard_exhausted"]
    assert len(exhausted) == 1
    assert exhausted[0]["sentence"] == original


@pytest.mark.asyncio
async def test_message_hub_word_density_guard_rewrites_on_violation(monkeypatch):
    """主笔正文流命中词密度超标 → guarded_stream 触发局部重写，最终广播不再含该词。"""
    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub

    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: [])
    monkeypatch.setattr(style_guard_mod, "WORD_THRESHOLDS", {"仿佛": 0})

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            for ch in "他仿佛笑了。":
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            return _Resp("他似乎笑了。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    captured: dict = {}

    async def fake_dialogue(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        text, _, _ = await call_llm(
            "system", "user", tag="synthesis", _log_step=0, _log_agent="director",
        )
        captured["text"] = text

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", fake_dialogue)

    hub = MessageHub()
    await hub.start_author_loop(12)
    if (_t := hub._author_tasks.get("default")) is not None:
        await _t

    assert "仿佛" not in captured["text"]
    assert "他似乎笑了。" in captured["text"]


@pytest.mark.asyncio
async def test_message_hub_rewrite_prompt_includes_trigger_word(monkeypatch):
    """词密度触发的 rewrite ainvoke 应在 user prompt 里带上命中的词。"""
    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub

    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: [])
    monkeypatch.setattr(style_guard_mod, "WORD_THRESHOLDS", {"仿佛": 0})

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    rewrite_users: list[str] = []

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            for ch in "他仿佛笑了。":
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            rewrite_users.append(msgs[1].content)
            return _Resp("他似乎笑了。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    async def fake_dialogue(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        await call_llm("system", "user", tag="synthesis", _log_step=0, _log_agent="director")

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", fake_dialogue)

    hub = MessageHub()
    await hub.start_author_loop(12)
    if (_t := hub._author_tasks.get("default")) is not None:
        await _t

    assert len(rewrite_users) == 1
    assert "「仿佛」" in rewrite_users[0]


@pytest.mark.asyncio
async def test_message_hub_word_density_guard_shares_window_across_calls(monkeypatch):
    """整章内多次 _call_llm(tag=...) 调用共享同一个 WordDensityGuard：单独一次"仿佛"
    不足以触发（阈值 1），但跨两次调用累计超过阈值后第二次调用命中并触发局部重写。"""
    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub

    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: [])
    monkeypatch.setattr(style_guard_mod, "WORD_THRESHOLDS", {"仿佛": 1})

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    call_n = {"n": 0}

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            call_n["n"] += 1
            text = "他仿佛笑了。" if call_n["n"] == 1 else "她仿佛也笑了。"
            for ch in text:
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            return _Resp("她似乎也笑了。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    captured: list[str] = []

    async def fake_dialogue(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        t1, _, _ = await call_llm("system", "user", tag="synthesis", _log_step=0, _log_agent="director")
        captured.append(t1)
        t2, _, _ = await call_llm("system", "user", tag="synthesis", _log_step=1, _log_agent="director")
        captured.append(t2)

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", fake_dialogue)

    hub = MessageHub()
    await hub.start_author_loop(13)
    if (_t := hub._author_tasks.get("default")) is not None:
        await _t

    assert "仿佛" in captured[0]       # 第一次单独出现，未过阈值(1)，未触发
    assert "仿佛" not in captured[1]   # 第二次累计到 2>1，触发改写
    assert "似乎" in captured[1]


# ── story_sandbox active_cast broadcasts ─────────────────────────────────────


@pytest.mark.asyncio
async def test_story_sandbox_turn_broadcasts_active_cast_on_final(monkeypatch):
    """PROSE step active_cast is forwarded on story_sandbox_final."""
    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    async def fake_run_turn(
        novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene,
        call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest,
        guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract,
        guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None,
        call_llm_dialogue_draft=None, branch_id=None,
    ):
        yield {"type": SandboxStepType.PROSE, "text": "正文", "active_cast": ["甲", "乙"]}

    import api.services.message_hub as mh_mod
    monkeypatch.setattr(mh_mod, "run_story_sandbox_turn", fake_run_turn)

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get("default")) is not None:
        await _t

    final_calls = [
        call.args[0] for call in mock_ws.send_json.call_args_list
        if call.args[0].get("type") == "story_sandbox_final"
    ]
    assert final_calls[0]["active_cast"] == ["甲", "乙"]


@pytest.mark.asyncio
async def test_story_sandbox_rewrite_done_includes_active_cast(monkeypatch):
    """Rewrite collects active_cast from the PROSE step into story_sandbox_rewrite_done."""
    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    async def fake_rewrite_last_round(
        novel_id, chapter, feedback, *, write_turn, call_llm_derive_char, call_llm_derive_scene,
        call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest,
        guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract,
        guard_text_profile_mutate, guard_text_suggest, call_llm_identify=None,
        call_llm_dialogue_draft=None, branch_id=None,
    ):
        async def _gen():
            yield {"type": SandboxStepType.PROSE, "text": "重写正文", "active_cast": ["乙"]}
        return _gen()

    import engine.story_sandbox.graph as graph_mod
    monkeypatch.setattr(graph_mod, "rewrite_last_round", fake_rewrite_last_round)

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_story_sandbox_rewrite(1, "重写反馈")
    if (_t := hub._story_sandbox_tasks.get("default")) is not None:
        await _t

    done_calls = [
        call.args[0] for call in mock_ws.send_json.call_args_list
        if call.args[0].get("type") == "story_sandbox_rewrite_done"
    ]
    assert done_calls[0]["active_cast"] == ["乙"]


@pytest.mark.asyncio
async def test_story_sandbox_selection_rewrite_broadcasts_start_then_done(monkeypatch):
    from api.services.message_hub import MessageHub

    async def fake_rewrite_selection(
        novel_id, chapter, original_text, anchor_offset, feedback,
        *, call_llm, guard_text, style_card="", round_id=None, branch_id=None,
    ):
        return "甲抬起头，望向远方。"

    import engine.story_sandbox.graph as graph_mod
    monkeypatch.setattr(graph_mod, "rewrite_selection", fake_rewrite_selection)

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_story_sandbox_selection_rewrite(1, "看向窗外", 3, "")
    if (_t := hub._story_sandbox_tasks.get("default")) is not None:
        await _t

    events = [call.args[0].get("type") for call in mock_ws.send_json.call_args_list]
    assert "story_sandbox_selection_rewrite_start" in events
    done_calls = [
        call.args[0] for call in mock_ws.send_json.call_args_list
        if call.args[0].get("type") == "story_sandbox_selection_rewrite_done"
    ]
    assert done_calls == [
        {
            "type": "story_sandbox_selection_rewrite_done", "content": "甲抬起头，望向远方。",
            "round_id": None, "novel_id": "default",
        },
    ]
    assert "default" not in hub._story_sandbox_live
    assert "default" not in hub._story_sandbox_tasks


@pytest.mark.asyncio
async def test_story_sandbox_selection_rewrite_broadcasts_error_on_value_error(monkeypatch):
    from api.services.message_hub import MessageHub

    async def fake_rewrite_selection(
        novel_id, chapter, original_text, anchor_offset, feedback,
        *, call_llm, guard_text, style_card="", round_id=None, branch_id=None,
    ):
        raise ValueError("选中的文字未能在正文中定位，请重新选择")

    import engine.story_sandbox.graph as graph_mod
    monkeypatch.setattr(graph_mod, "rewrite_selection", fake_rewrite_selection)

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_story_sandbox_selection_rewrite(1, "不存在的文字", 0, "")
    if (_t := hub._story_sandbox_tasks.get("default")) is not None:
        await _t

    error_calls = [
        call.args[0] for call in mock_ws.send_json.call_args_list
        if call.args[0].get("type") == "story_sandbox_selection_rewrite_error"
    ]
    assert error_calls == [{
        "type": "story_sandbox_selection_rewrite_error",
        "error": "选中的文字未能在正文中定位，请重新选择",
        "round_id": None, "novel_id": "default",
    }]


@pytest.mark.asyncio
async def test_story_sandbox_selection_rewrite_refuses_while_busy(monkeypatch):
    import asyncio

    from api.services.message_hub import MessageHub

    hub = MessageHub()
    hub._story_sandbox_tasks["default"] = asyncio.ensure_future(asyncio.sleep(10))
    with pytest.raises(RuntimeError):
        await hub.start_story_sandbox_selection_rewrite(1, "看向窗外", 0, "")
    hub._story_sandbox_tasks["default"].cancel()


@pytest.mark.asyncio
async def test_story_sandbox_selection_rewrite_sets_live_mode(monkeypatch):
    from api.services.message_hub import MessageHub

    hub = MessageHub()
    seen_live = {}

    async def fake_rewrite_selection(
        novel_id, chapter, original_text, anchor_offset, feedback,
        *, call_llm, guard_text, style_card="", round_id=None, branch_id=None,
    ):
        seen_live["mode"] = hub._story_sandbox_live["default"]["mode"]
        return "新正文"

    import engine.story_sandbox.graph as graph_mod
    monkeypatch.setattr(graph_mod, "rewrite_selection", fake_rewrite_selection)

    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_story_sandbox_selection_rewrite(1, "看向窗外", 0, "")
    if (_t := hub._story_sandbox_tasks.get("default")) is not None:
        await _t

    assert seen_live["mode"] == "selection_rewrite"


@pytest.mark.asyncio
async def test_story_sandbox_history_returns_active_cast(monkeypatch):
    """story_sandbox_history exposes sorted active_cast keys from peek_state."""
    from api.services.message_hub import MessageHub

    async def fake_peek_state(novel_id, chapter, branch_id=None):
        return {
            "turns": [{"prose": "x", "instruction": "y"}],
            "active_cast": {"乙": 0, "甲": 2},
        }

    import engine.story_sandbox.graph as graph_mod
    monkeypatch.setattr(graph_mod, "peek_state", fake_peek_state)

    hub = MessageHub()
    result = await hub.story_sandbox_history(1, novel_id="test-novel")
    assert result["rounds"] == [{"prose": "x", "instruction": "y"}]
    assert result["active_cast"] == sorted(["乙", "甲"])


# ── story_sandbox mid-stream guard ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_story_sandbox_turn_sandbox_style_rewrite_broadcasts_start_end(monkeypatch):
    """start_story_sandbox_turn _write_turn path: style-guard rewrite emits start/end WS events."""
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    patterns = style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`")
    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: patterns)

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            for ch in "他不是喜欢她，而是习惯了。":
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            return _Resp("他其实很在意她。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        result = await write_turn("system", "packet")
        yield {"type": SandboxStepType.PROSE, "text": result}

    import api.services.message_hub as mh_mod
    monkeypatch.setattr(mh_mod, "run_story_sandbox_turn", fake_run_turn)

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get("default")) is not None:
        await _t

    events = [
        call.args[0] for call in mock_ws.send_json.call_args_list
        if call.args[0].get("type") == "story_sandbox_style_rewrite"
    ]
    assert events == [
        {"type": "story_sandbox_style_rewrite", "status": "start", "novel_id": "default"},
        {"type": "story_sandbox_style_rewrite", "status": "end", "novel_id": "default"},
    ]


@pytest.mark.asyncio
async def test_story_sandbox_turn_short_field_style_rewrite_broadcasts_start_end(monkeypatch):
    """start_story_sandbox_turn's short-field guard (derive_char/derive_scene/event_log/
    profile_mutate/suggest, built by _make_guard_text) must also broadcast
    story_sandbox_style_rewrite start/end -- previously only the prose _write_turn path did,
    so the frontend's "检测到 AI 味文本，正在重写" indicator silently never appeared for hits
    in these 5 non-prose fields."""
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    patterns = style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`")
    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: patterns)

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def ainvoke(self, msgs):
            return _Resp("她其实很在意他。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        result = await guard_text_derive_char("她不是喜欢他，而是习惯了。")
        yield {"type": SandboxStepType.PROSE, "text": result}

    import api.services.message_hub as mh_mod
    monkeypatch.setattr(mh_mod, "run_story_sandbox_turn", fake_run_turn)

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get("default")) is not None:
        await _t

    events = [
        call.args[0] for call in mock_ws.send_json.call_args_list
        if call.args[0].get("type") == "story_sandbox_style_rewrite"
    ]
    assert events == [
        {"type": "story_sandbox_style_rewrite", "status": "start", "novel_id": "default"},
        {"type": "story_sandbox_style_rewrite", "status": "end", "novel_id": "default"},
    ]


@pytest.mark.asyncio
async def test_story_sandbox_rewrite_sandbox_style_rewrite_broadcasts_start_end(monkeypatch):
    """start_story_sandbox_rewrite _write_turn path: style-guard rewrite emits start/end WS events."""
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    patterns = style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`")
    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: patterns)

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            for ch in "他不是喜欢她，而是习惯了。":
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            return _Resp("他其实很在意她。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    async def fake_rewrite_last_round(novel_id, chapter, feedback, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        async def _gen():
            result = await write_turn("system", "packet")
            yield {"type": SandboxStepType.PROSE, "text": result}
        return _gen()

    import engine.story_sandbox.graph as graph_mod
    monkeypatch.setattr(graph_mod, "rewrite_last_round", fake_rewrite_last_round)

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_story_sandbox_rewrite(1, "重写反馈")
    if (_t := hub._story_sandbox_tasks.get("default")) is not None:
        await _t

    events = [
        call.args[0] for call in mock_ws.send_json.call_args_list
        if call.args[0].get("type") == "story_sandbox_style_rewrite"
    ]
    assert events == [
        {"type": "story_sandbox_style_rewrite", "status": "start", "novel_id": "default"},
        {"type": "story_sandbox_style_rewrite", "status": "end", "novel_id": "default"},
    ]


@pytest.mark.asyncio
async def test_story_sandbox_turn_guards_stream_and_rewrites_violation(monkeypatch):
    """sandbox 正常写入流式命中禁用句式 -> guarded_stream 触发局部重写，最终广播的
    story_sandbox_token delta 拼起来不再含被禁句式，且重写走真实 prompt_logger 记录。"""
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    patterns = style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`")
    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: patterns)

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            for ch in "他不是喜欢她，而是习惯了。":
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            return _Resp("他其实很在意她。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        result = await write_turn("system", "packet")
        yield {"type": SandboxStepType.PROSE, "text": result}

    import api.services.message_hub as mh_mod
    monkeypatch.setattr(mh_mod, "run_story_sandbox_turn", fake_run_turn)

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get("default")) is not None:
        await _t

    deltas = "".join(
        call.args[0]["delta"]
        for call in mock_ws.send_json.call_args_list
        if call.args[0].get("type") == "story_sandbox_token"
    )
    assert "不是" not in deltas
    assert "他其实很在意她。" in deltas

    final_calls = [
        call.args[0] for call in mock_ws.send_json.call_args_list
        if call.args[0].get("type") == "story_sandbox_final"
    ]
    assert final_calls[0]["content"] == deltas  # stream already matches the final broadcast


@pytest.mark.asyncio
async def test_story_sandbox_turn_prose_skips_guard_when_disabled(monkeypatch):
    """sandbox prose's disable_style_guard=True bypasses guarded_stream entirely -- banned-pattern
    text passes through unmodified in the broadcast stream."""
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    patterns = style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`")
    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: patterns)

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            for ch in "他不是喜欢她，而是习惯了。":
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            raise AssertionError("rewrite must not be called when disable_style_guard is set")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"sandbox_llm_params": {"prose": {"disable_style_guard": True}}},
    )

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        result = await write_turn("system", "packet")
        yield {"type": SandboxStepType.PROSE, "text": result}

    import api.services.message_hub as mh_mod
    monkeypatch.setattr(mh_mod, "run_story_sandbox_turn", fake_run_turn)

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get("default")) is not None:
        await _t

    deltas = "".join(
        call.args[0]["delta"]
        for call in mock_ws.send_json.call_args_list
        if call.args[0].get("type") == "story_sandbox_token"
    )
    assert deltas == "他不是喜欢她，而是习惯了。"  # unrewritten -- guard bypassed


@pytest.mark.asyncio
async def test_story_sandbox_turn_guard_exhausted_logs_and_passes_through(monkeypatch):
    """重写 2 次仍命中 -> 耗尽不再回退，接受最后一次重写产出，且 prompt_logger 记一条 style_guard_exhausted。"""
    import engine.execution.style_guard as style_guard_mod
    import llm.prompt_logger as pl_mod
    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    patterns = style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`")
    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: patterns)

    original = "他不是喜欢她，而是习惯了。"

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            for ch in original:
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            return _Resp("还是不是喜欢她，而是习惯了。")  # 重写仍命中同款句式

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    logged_events: list[dict] = []
    original_log_event = pl_mod.PromptLogger.log_event

    def _capture_log_event(self, event_type, **kwargs):
        logged_events.append({"type": event_type, **kwargs})
        return original_log_event(self, event_type, **kwargs)

    monkeypatch.setattr(pl_mod.PromptLogger, "log_event", _capture_log_event)

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        result = await write_turn("system", "packet")
        yield {"type": SandboxStepType.PROSE, "text": result}

    import api.services.message_hub as mh_mod
    monkeypatch.setattr(mh_mod, "run_story_sandbox_turn", fake_run_turn)

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get("default")) is not None:
        await _t

    deltas = "".join(
        call.args[0]["delta"]
        for call in mock_ws.send_json.call_args_list
        if call.args[0].get("type") == "story_sandbox_token"
    )
    assert deltas == "还是不是喜欢她，而是习惯了。"  # 耗尽不再回退，接受最后一次重写产出
    exhausted = [e for e in logged_events if e["type"] == "style_guard_exhausted"]
    assert len(exhausted) == 1
    assert exhausted[0]["sentence"] == original


@pytest.mark.asyncio
async def test_story_sandbox_rewrite_guards_stream_and_rewrites_violation(monkeypatch):
    """sandbox 重写流式命中禁用句式 -> guarded_stream 触发局部重写，最终广播的
    story_sandbox_rewrite_token delta 拼起来不再含被禁句式，且重写走真实 prompt_logger 记录。"""
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    patterns = style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`")
    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: patterns)

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            for ch in "他不是喜欢她，而是习惯了。":
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            return _Resp("他其实很在意她。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    async def fake_rewrite_last_round(novel_id, chapter, feedback, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        async def _gen():
            result = await write_turn("system", "packet")
            yield {"type": SandboxStepType.PROSE, "text": result}
        return _gen()

    import engine.story_sandbox.graph as graph_mod
    monkeypatch.setattr(graph_mod, "rewrite_last_round", fake_rewrite_last_round)

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_story_sandbox_rewrite(1, "重写反馈")
    if (_t := hub._story_sandbox_tasks.get("default")) is not None:
        await _t

    deltas = "".join(
        call.args[0]["delta"]
        for call in mock_ws.send_json.call_args_list
        if call.args[0].get("type") == "story_sandbox_rewrite_token"
    )
    assert "不是" not in deltas
    assert "他其实很在意她。" in deltas

    done_calls = [
        call.args[0] for call in mock_ws.send_json.call_args_list
        if call.args[0].get("type") == "story_sandbox_rewrite_done"
    ]
    assert done_calls[0]["content"] == deltas  # stream already matches the final broadcast


@pytest.mark.asyncio
async def test_story_sandbox_rewrite_guard_exhausted_logs_and_passes_through(monkeypatch):
    """重写路径重写 2 次仍命中 -> 耗尽不再回退，接受最后一次重写产出，且 prompt_logger 记一条 style_guard_exhausted。"""
    import engine.execution.style_guard as style_guard_mod
    import llm.prompt_logger as pl_mod
    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    patterns = style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`")
    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: patterns)

    original = "他不是喜欢她，而是习惯了。"

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            for ch in original:
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            return _Resp("还是不是喜欢她，而是习惯了。")  # 重写仍命中同款句式

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    logged_events: list[dict] = []
    original_log_event = pl_mod.PromptLogger.log_event

    def _capture_log_event(self, event_type, **kwargs):
        logged_events.append({"type": event_type, **kwargs})
        return original_log_event(self, event_type, **kwargs)

    monkeypatch.setattr(pl_mod.PromptLogger, "log_event", _capture_log_event)

    async def fake_rewrite_last_round(novel_id, chapter, feedback, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        async def _gen():
            result = await write_turn("system", "packet")
            yield {"type": SandboxStepType.PROSE, "text": result}
        return _gen()

    import engine.story_sandbox.graph as graph_mod
    monkeypatch.setattr(graph_mod, "rewrite_last_round", fake_rewrite_last_round)

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_story_sandbox_rewrite(1, "重写反馈")
    if (_t := hub._story_sandbox_tasks.get("default")) is not None:
        await _t

    deltas = "".join(
        call.args[0]["delta"]
        for call in mock_ws.send_json.call_args_list
        if call.args[0].get("type") == "story_sandbox_rewrite_token"
    )
    assert deltas == "还是不是喜欢她，而是习惯了。"  # 耗尽不再回退，接受最后一次重写产出
    exhausted = [e for e in logged_events if e["type"] == "style_guard_exhausted"]
    assert len(exhausted) == 1
    assert exhausted[0]["sentence"] == original


@pytest.mark.asyncio
async def test_story_sandbox_turn_word_density_guard_rewrites_on_violation(monkeypatch):
    """sandbox 正常写入流式命中词密度超标 -> guarded_stream 触发局部重写。"""
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: [])
    monkeypatch.setattr(style_guard_mod, "WORD_THRESHOLDS", {"仿佛": 0})

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            for ch in "他仿佛笑了。":
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            return _Resp("他似乎笑了。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        result = await write_turn("system", "packet")
        yield {"type": SandboxStepType.PROSE, "text": result}

    import api.services.message_hub as mh_mod
    monkeypatch.setattr(mh_mod, "run_story_sandbox_turn", fake_run_turn)

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get("default")) is not None:
        await _t

    deltas = "".join(
        call.args[0]["delta"]
        for call in mock_ws.send_json.call_args_list
        if call.args[0].get("type") == "story_sandbox_token"
    )
    assert "仿佛" not in deltas
    assert "他似乎笑了。" in deltas


@pytest.mark.asyncio
async def test_story_sandbox_rewrite_word_density_guard_rewrites_on_violation(monkeypatch):
    """sandbox 重写流式命中词密度超标 -> guarded_stream 触发局部重写。"""
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: [])
    monkeypatch.setattr(style_guard_mod, "WORD_THRESHOLDS", {"仿佛": 0})

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            for ch in "他仿佛笑了。":
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            return _Resp("他似乎笑了。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    async def fake_rewrite_last_round(novel_id, chapter, feedback, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        async def _gen():
            result = await write_turn("system", "packet")
            yield {"type": SandboxStepType.PROSE, "text": result}
        return _gen()

    import engine.story_sandbox.graph as graph_mod
    monkeypatch.setattr(graph_mod, "rewrite_last_round", fake_rewrite_last_round)

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_story_sandbox_rewrite(1, "重写反馈")
    if (_t := hub._story_sandbox_tasks.get("default")) is not None:
        await _t

    deltas = "".join(
        call.args[0]["delta"]
        for call in mock_ws.send_json.call_args_list
        if call.args[0].get("type") == "story_sandbox_rewrite_token"
    )
    assert "仿佛" not in deltas
    assert "他似乎笑了。" in deltas


# ── setup_chat live-turn snapshot ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emit_setup_chat_appends_to_live_snapshot_when_present(monkeypatch):
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub

    monkeypatch.setattr(mh_mod, "active_novel_id", lambda: "n")

    hub = MessageHub()
    hub._setup_chat_live["n"] = {"novel_id": "n", "instruction": "x", "events": []}
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    ev = {"type": "setup_chat_token", "delta": "a"}

    await hub._emit_setup_chat(ev)

    assert hub._setup_chat_live["n"]["events"] == [ev]
    mock_ws.send_json.assert_awaited_once_with(ev)


@pytest.mark.asyncio
async def test_emit_setup_chat_is_a_noop_bookkeeping_wise_when_no_live_snapshot():
    from api.services.message_hub import MessageHub

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    ev = {"type": "setup_chat_token", "delta": "a"}

    await hub._emit_setup_chat(ev)

    assert "default" not in hub._setup_chat_live
    mock_ws.send_json.assert_awaited_once_with(ev)


@pytest.mark.asyncio
async def test_emit_setup_chat_clears_live_snapshot_on_terminal_event(monkeypatch):
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub

    monkeypatch.setattr(mh_mod, "active_novel_id", lambda: "n")

    hub = MessageHub()
    hub._setup_chat_live["n"] = {"novel_id": "n", "instruction": "x", "events": []}

    await hub._emit_setup_chat({"type": "setup_chat_done"})

    assert "default" not in hub._setup_chat_live


@pytest.mark.asyncio
async def test_emit_setup_chat_does_not_clear_on_non_terminal_event():
    from api.services.message_hub import MessageHub

    hub = MessageHub()
    hub._setup_chat_live["n"] = {"novel_id": "n", "instruction": "x", "events": []}

    await hub._emit_setup_chat({"type": "setup_chat_tool", "name": "recall", "phase": "start"})

    assert "n" in hub._setup_chat_live


@pytest.mark.asyncio
async def test_setup_chat_turn_live_snapshot_lifecycle(monkeypatch, tmp_path):
    """_setup_chat_live fills in with the submitted text + events broadcast so far while a
    turn is in flight, and clears once the turn's terminal event fires."""
    import asyncio

    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub

    session_dir = str(tmp_path / "session")
    monkeypatch.setattr(mh_mod, "setup_chat_session_dir", lambda novel_id=None: session_dir)
    monkeypatch.setattr(mh_mod, "active_novel_id", lambda: "n")

    resume = asyncio.Event()

    async def fake_run_turn(agent, novel_id, text, emit, accountant):
        await emit({"type": "setup_chat_token", "delta": "半截"})
        await resume.wait()
        await emit({"type": "setup_chat_final", "content": "半截", "thinking": ""})

    async def fake_broadcast(ev):
        pass

    monkeypatch.setattr(mh_mod, "run_turn", fake_run_turn)

    hub = MessageHub()
    agent = type("A", (), {"aget_state": staticmethod(AsyncMock(return_value=None))})()
    monkeypatch.setattr(hub, "_ensure_setup_chat_agent", AsyncMock(return_value=agent))
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    monkeypatch.setattr(hub, "_make_setup_chat_accountant", lambda novel_id: AsyncMock())
    monkeypatch.setattr("engine.setup_chat.turn_snapshot.snapshot_turn_start", lambda: None)

    await hub.start_setup_chat_turn("继续写")

    for _ in range(200):
        live = hub._setup_chat_live.get("n")
        if live is not None and live["events"]:
            break
        await asyncio.sleep(0.005)
    else:
        pytest.fail("_setup_chat_live never populated")

    live = hub._setup_chat_live["n"]
    assert live["instruction"] == "继续写"
    assert {"type": "setup_chat_token", "delta": "半截"} in live["events"]

    resume.set()
    await hub._setup_chat_tasks["n"]

    assert "n" not in hub._setup_chat_live


@pytest.mark.asyncio
async def test_stop_setup_chat_turn_clears_live_snapshot(monkeypatch, tmp_path):
    import asyncio

    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub

    session_dir = str(tmp_path / "session")
    monkeypatch.setattr(mh_mod, "setup_chat_session_dir", lambda novel_id=None: session_dir)
    monkeypatch.setattr(mh_mod, "active_novel_id", lambda: "n")

    hub = MessageHub()
    started = asyncio.Event()

    async def fake_run_turn(agent, novel_id, text, emit, accountant):
        started.set()
        await asyncio.sleep(3600)

    async def fake_broadcast(ev):
        pass

    agent_holder = type("A", (), {
        "aget_state": staticmethod(AsyncMock(return_value=None)),
        "aupdate_state": staticmethod(AsyncMock()),
    })()

    monkeypatch.setattr(mh_mod, "run_turn", fake_run_turn)
    monkeypatch.setattr(hub, "_ensure_setup_chat_agent", AsyncMock(return_value=agent_holder))
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    monkeypatch.setattr(hub, "_make_setup_chat_accountant", lambda novel_id: AsyncMock())
    monkeypatch.setattr("engine.setup_chat.turn_snapshot.snapshot_turn_start", lambda: None)
    monkeypatch.setattr("engine.setup_chat.turn_snapshot.restore_turn_start", lambda: True)

    await hub.start_setup_chat_turn("继续")
    await asyncio.wait_for(started.wait(), timeout=1)
    assert "n" in hub._setup_chat_live

    await hub.stop_setup_chat_turn()

    assert "n" not in hub._setup_chat_live


@pytest.mark.asyncio
async def test_stop_setup_chat_turn_rolls_back_choice_records(monkeypatch, tmp_path):
    import asyncio

    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub
    from engine.setup_chat.session_record import load_messages

    session_dir = str(tmp_path / "session")
    monkeypatch.setattr(mh_mod, "setup_chat_session_dir", lambda novel_id=None: session_dir)
    monkeypatch.setattr(mh_mod, "active_novel_id", lambda: "n")

    hub = MessageHub()
    started = asyncio.Event()

    async def fake_run_turn(agent, novel_id, text, emit, accountant):
        await emit({"type": "setup_chat_choice", "question": "继续吗？", "options": ["是", "否"]})
        started.set()
        await asyncio.sleep(3600)

    async def fake_broadcast(ev):
        pass

    agent_holder = type("A", (), {
        "aget_state": staticmethod(AsyncMock(return_value=None)),
        "aupdate_state": staticmethod(AsyncMock()),
    })()

    monkeypatch.setattr(mh_mod, "run_turn", fake_run_turn)
    monkeypatch.setattr(hub, "_ensure_setup_chat_agent", AsyncMock(return_value=agent_holder))
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    monkeypatch.setattr(hub, "_make_setup_chat_accountant", lambda novel_id: AsyncMock())
    monkeypatch.setattr("engine.setup_chat.turn_snapshot.snapshot_turn_start", lambda: None)
    monkeypatch.setattr("engine.setup_chat.turn_snapshot.restore_turn_start", lambda: True)

    await hub.start_setup_chat_turn("继续")
    await asyncio.wait_for(started.wait(), timeout=1)
    assert len(load_messages(session_dir)) == 2  # user + choice

    await hub.stop_setup_chat_turn()

    assert load_messages(session_dir) == []
    assert hub._setup_chat_pre_turn_choice_msg_ids == []


def test_setup_chat_live_round_returns_snapshot_when_novel_matches(monkeypatch):
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub

    monkeypatch.setattr(mh_mod, "active_novel_id", lambda: "novel-a")
    hub = MessageHub()
    hub._setup_chat_live["novel-a"] = {
        "novel_id": "novel-a", "instruction": "继续",
        "events": [{"type": "setup_chat_token", "delta": "甲"}],
    }

    assert hub.setup_chat_live_round() == {
        "instruction": "继续", "events": [{"type": "setup_chat_token", "delta": "甲"}],
    }


def test_setup_chat_live_round_none_when_novel_mismatches(monkeypatch):
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub

    monkeypatch.setattr(mh_mod, "active_novel_id", lambda: "novel-b")
    hub = MessageHub()
    hub._setup_chat_live["novel-a"] = {"novel_id": "novel-a", "instruction": "继续", "events": []}

    assert hub.setup_chat_live_round() is None


def test_setup_chat_live_round_none_when_nothing_in_flight(monkeypatch):
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub

    monkeypatch.setattr(mh_mod, "active_novel_id", lambda: "novel-a")
    hub = MessageHub()

    assert hub.setup_chat_live_round() is None


# ── setup-chat author guard + recovery + notice persist ─────────────────────


@pytest.mark.asyncio
async def test_author_guard_stops_and_resets_running_chapter(monkeypatch, tmp_path):
    import asyncio as _aio

    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub

    journal = tmp_path / "ch3_journal.ndjson"
    journal.write_text('{"type":"x"}\n', encoding="utf-8")
    cp = tmp_path / "graph.sqlite"
    cp.write_text("x", encoding="utf-8")

    monkeypatch.setattr(mh_mod, "author_loop_journal_path", lambda ch: str(journal))
    monkeypatch.setattr(mh_mod, "author_loop_graph_checkpoint_path", lambda: str(cp))

    deleted: list[str] = []

    async def fake_adelete(self, thread_id):  # noqa: ANN001
        deleted.append(thread_id)

    import langgraph.checkpoint.sqlite.aio as cp_mod
    monkeypatch.setattr(cp_mod.AsyncSqliteSaver, "adelete_thread", fake_adelete)

    hub = MessageHub()
    hub._author_chapters["default"] = 3

    async def never_ends(*_a, **_k):
        await _aio.sleep(3600)

    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", never_ends)
    await hub.start_author_loop(3)
    assert hub._author_chapters.get("default") == 3

    broadcasts: list[dict] = []
    orig = hub.broadcast

    async def capture(ev):  # noqa: ANN001
        broadcasts.append(ev)
        await orig(ev)

    monkeypatch.setattr(hub, "broadcast", capture)
    await hub._on_setup_write_affects_author(1, 10**9, "第 3 章设定变更")

    assert "default" not in hub._author_tasks
    assert "default" not in hub._author_chapters
    assert deleted == ["ch3"]
    assert not journal.exists()
    assert any(
        e.get("type") == "author_loop_stopped" and e.get("chapter") == 3 and e.get("reason")
        for e in broadcasts
    )


@pytest.mark.asyncio
async def test_author_guard_ignores_unaffected_chapter(monkeypatch):
    import asyncio as _aio

    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    from api.services.message_hub import MessageHub

    async def never_ends(*_a, **_k):
        await _aio.sleep(3600)

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", never_ends)
    hub = MessageHub()
    await hub.start_author_loop(3)
    await hub._on_setup_write_affects_author(7, 7, "第 7 章设定变更")
    assert "default" in hub._author_tasks


@pytest.mark.asyncio
async def test_author_guard_noop_when_idle():
    from api.services.message_hub import MessageHub

    hub = MessageHub()
    await hub._on_setup_write_affects_author(1, 10**9, "reason")


@pytest.mark.asyncio
async def test_setup_chat_notice_persisted(monkeypatch, tmp_path):
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub
    from engine.setup_chat.session_record import load_messages

    session_dir = str(tmp_path / "session")
    monkeypatch.setattr(mh_mod, "setup_chat_session_dir", lambda novel_id=None: session_dir)
    monkeypatch.setattr(mh_mod, "active_novel_id", lambda: "n1")

    hub = MessageHub()
    emit = hub._make_setup_chat_emit()
    await emit({"type": "setup_chat_notice", "content": "上轮操作已回滚", "persist": True})
    await emit({"type": "setup_chat_notice", "content": "临时提示", "persist": False})

    msgs = load_messages(session_dir)
    assert len(msgs) == 1
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "上轮操作已回滚"


@pytest.mark.asyncio
async def test_setup_chat_choice_persisted(monkeypatch, tmp_path):
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub
    from engine.setup_chat.session_record import load_messages

    session_dir = str(tmp_path / "session")
    monkeypatch.setattr(mh_mod, "setup_chat_session_dir", lambda novel_id=None: session_dir)
    monkeypatch.setattr(mh_mod, "active_novel_id", lambda: "n1")

    hub = MessageHub()
    emit = hub._make_setup_chat_emit()
    await emit({"type": "setup_chat_choice", "question": "继续吗？", "options": ["是", "否"]})

    msgs = load_messages(session_dir)
    assert len(msgs) == 1
    assert msgs[0]["role"] == "choice"
    assert msgs[0]["content"] == "继续吗？"
    assert msgs[0]["options"] == ["是", "否"]
    assert hub._setup_chat_pre_turn_choice_msg_ids == [msgs[0]["id"]]


@pytest.mark.asyncio
async def test_setup_chat_choice_malformed_payload_not_persisted(monkeypatch, tmp_path):
    """Mirrors the isinstance guard already in agent.py:417-424 -- defensive, not a new
    constraint (a malformed event should never reach here, but must not crash or write junk
    if it somehow does)."""
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub
    from engine.setup_chat.session_record import load_messages

    session_dir = str(tmp_path / "session")
    monkeypatch.setattr(mh_mod, "setup_chat_session_dir", lambda novel_id=None: session_dir)
    monkeypatch.setattr(mh_mod, "active_novel_id", lambda: "n1")

    hub = MessageHub()
    emit = hub._make_setup_chat_emit()
    await emit({"type": "setup_chat_choice", "question": "", "options": ["是"]})
    await emit({"type": "setup_chat_choice", "question": "q", "options": "not-a-list"})

    assert load_messages(session_dir) == []
    assert hub._setup_chat_pre_turn_choice_msg_ids == []


@pytest.mark.asyncio
async def test_recovery_check_runs_once_per_novel(monkeypatch, tmp_path):
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub

    calls: list[str] = []

    async def fake_recovery(agent, novel_id, emit, accountant):  # noqa: ANN001
        calls.append(novel_id)

    monkeypatch.setattr("engine.setup_chat.agent.run_recovery", fake_recovery)
    monkeypatch.setattr(mh_mod, "active_novel_id", lambda: "novel-a")
    monkeypatch.setattr(
        mh_mod.MessageHub, "_ensure_setup_chat_agent", AsyncMock(return_value=object()),
    )

    hub = MessageHub()
    await hub.check_setup_chat_recovery()
    await hub.check_setup_chat_recovery()
    if hub._setup_chat_tasks.get("novel-a"):
        await hub._setup_chat_tasks["novel-a"]
    assert calls == ["novel-a"]

    hub2 = MessageHub()
    hub2._setup_chat_tasks["default"] = type("T", (), {"done": lambda self: False})()  # type: ignore[assignment]
    await hub2.check_setup_chat_recovery()
    assert calls == ["novel-a"]


@pytest.mark.asyncio
async def test_hub_run_accounts_token_usage_for_author_loop(monkeypatch):
    """主笔(author_loop)的每次 LLM 调用——流式(tag=...)带 usage tail chunk，以及非流式
    (ainvoke)——都应累计写入 token_ledger(subsystem=author_loop)。此前 message_hub 从不构造
    TokenAccountant、也不提取真实 usage(tokens 硬编码 0)，Token 统计页永远拿不到数据，
    这就是"看不到主笔消耗"的根因。"""
    import api.services.token_accountant as ta
    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    from api.services.message_hub import MessageHub

    ledger: dict[tuple[str, str], dict] = {}

    def fake_reset_cell(subsystem, key, *, novel_id=None):
        ledger[(subsystem, key)] = {"tokens_in": 0, "tokens_out": 0, "tokens_cached": 0}

    def fake_add_to_cell(subsystem, key, tin, tout, tc, model, *, novel_id=None):
        cell = ledger.setdefault((subsystem, key), {"tokens_in": 0, "tokens_out": 0, "tokens_cached": 0})
        cell["tokens_in"] += tin
        cell["tokens_out"] += tout
        cell["tokens_cached"] += tc
        return dict(cell)

    monkeypatch.setattr(ta, "reset_cell", fake_reset_cell)
    monkeypatch.setattr(ta, "add_to_cell", fake_add_to_cell)

    class _Chunk:
        def __init__(self, content: str, usage=None) -> None:
            self.content = content
            self.usage_metadata = usage

    class _Resp:
        def __init__(self, content: str, usage=None) -> None:
            self.content = content
            self.usage_metadata = usage

    class _FakeLLM:
        model = "fake-model"

        async def astream(self, msgs, stream_usage=False):
            for ch in "写好了":
                yield _Chunk(ch)
            if stream_usage:
                yield _Chunk("", usage={
                    "input_tokens": 100, "output_tokens": 20,
                    "input_token_details": {"cache_read": 5},
                })

        async def ainvoke(self, msgs):
            return _Resp("决策完成", usage={
                "input_tokens": 30, "output_tokens": 10,
                "input_token_details": {"cache_read": 0},
            })

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    async def fake_dialogue(chapter, call_llm, prose_style, *, emit, resume=False,
                             author_turns=None):
        await call_llm("system", "user", tag="synthesis", _log_step=0, _log_agent="director")
        await call_llm("system", "user", _log_step=1, _log_agent="scheduler")

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", fake_dialogue)

    hub = MessageHub()
    await hub.start_author_loop(11)
    if (_t := hub._author_tasks.get("default")) is not None:
        await _t

    cell = ledger.get(("author_loop", "11"))
    assert cell, "author_loop 的 token 用量从未记账"
    assert cell["tokens_in"] == 130   # 100 (streaming tail) + 30 (ainvoke)
    assert cell["tokens_out"] == 30   # 20 + 10
    assert cell["tokens_cached"] == 5


@pytest.mark.asyncio
async def test_reset_setup_chat_resets_mode_to_manual():
    from api.services.message_hub import MessageHub
    from engine.setup_chat.mode import is_auto_mode, set_auto_mode

    set_auto_mode(True)
    try:
        hub = MessageHub()
        await hub.reset_setup_chat()
        assert is_auto_mode() is False
    finally:
        set_auto_mode(False)  # safety net if the assertion above fails


@pytest.mark.asyncio
async def test_reset_setup_chat_broadcasts_mode_change_when_it_flips():
    from api.services.message_hub import MessageHub
    from engine.setup_chat.mode import is_auto_mode, set_auto_mode

    set_auto_mode(True)
    try:
        hub = MessageHub()
        events = []

        async def fake_broadcast(ev):
            events.append(ev)

        hub.broadcast = fake_broadcast  # type: ignore[method-assign]
        await hub.reset_setup_chat()
        assert is_auto_mode() is False
        assert events == [{"type": "setup_chat_mode_changed", "auto": False}]
    finally:
        set_auto_mode(False)


@pytest.mark.asyncio
async def test_reset_setup_chat_for_non_focused_novel_does_not_reset_mode(monkeypatch):
    """novel_memory_scavenger evicts idle novels other than the currently-focused one
    (see its `nid != focus` filter) -- that background eviction must not silently flip
    the global AUTO flag off for whatever novel the user is actively working on."""
    from api.services import message_hub as mh_mod
    from engine.setup_chat.mode import is_auto_mode, set_auto_mode

    monkeypatch.setattr(mh_mod, "active_novel_id", lambda: "focused-novel")
    set_auto_mode(True)
    try:
        hub = mh_mod.MessageHub()
        events = []

        async def fake_broadcast(ev):
            events.append(ev)

        hub.broadcast = fake_broadcast  # type: ignore[method-assign]
        await hub.reset_setup_chat("some-other-idle-novel")
        assert is_auto_mode() is True
        assert events == []
    finally:
        set_auto_mode(False)


@pytest.mark.asyncio
async def test_reset_setup_chat_invalidates_content_packs_cache(monkeypatch):
    """Regression: content_packs._packs() caches scan_content_packs() at module scope
    for the process lifetime. reset_setup_chat() is the natural rebuild boundary (see
    tool_args.py's _build_character_fields_args docstring), so that's the one choke
    point that must clear the cache -- otherwise gender/physique/custom_fields keep
    serving whatever content-pack state was computed on first use, even though the
    Pydantic schema layer above it is correctly rebuilt every build_agent() call
    (2026-07-29 content-rating-schema-freeze-fix only fixed that outer layer)."""
    import context.content_packs as cp
    from api.services.message_hub import MessageHub

    reload_calls = {"n": 0}
    real_reload = cp.reload_content_packs

    def fake_reload() -> None:
        reload_calls["n"] += 1
        real_reload()

    monkeypatch.setattr(cp, "reload_content_packs", fake_reload)

    hub = MessageHub()
    await hub.reset_setup_chat()
    assert reload_calls["n"] == 1


@pytest.mark.asyncio
async def test_ensure_setup_chat_agent_concurrent_callers_share_one_build(monkeypatch):
    import asyncio

    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub

    hub = MessageHub()
    # NOTE: deviates from the plan's literal `monkeypatch.setattr("utils.paths.active_novel_id",
    # ...)`. message_hub.py does `from utils.paths import active_novel_id` at module import
    # time, so it holds its own name binding in mh_mod's namespace -- patching
    # utils.paths.active_novel_id afterwards has no effect on that already-bound name (unlike
    # graph.py's ensure_checkpointer, which re-imports active_novel_id locally on every call).
    # Matches the existing convention already used elsewhere in this file (see line ~180).
    monkeypatch.setattr(mh_mod, "active_novel_id", lambda: "novelA")

    build_calls = []

    async def fake_build_agent():
        # No novel switch happens in this test, so the discard branch (which reads
        # agent.checkpointer.conn.close()) is never exercised -- a bare sentinel is enough.
        build_calls.append(1)
        await asyncio.sleep(0.01)
        return object()

    monkeypatch.setattr("engine.setup_chat.agent.build_agent", fake_build_agent)

    results = await asyncio.gather(
        hub._ensure_setup_chat_agent("novelA"), hub._ensure_setup_chat_agent("novelA"),
    )
    assert len(build_calls) == 1
    assert results[0] is results[1]


@pytest.mark.asyncio
async def test_setup_chat_agents_isolated_across_novels(monkeypatch):
    """Two novels each get their own agent instance; building one does not discard the other."""
    from api.services.message_hub import MessageHub

    hub = MessageHub()
    built_for: list[str] = []

    class _FakeAgent:
        def __init__(self, novel_id: str) -> None:
            self.novel_id = novel_id
            self.checkpointer = type("_CP", (), {"conn": type("_C", (), {
                "close": staticmethod(lambda: _noop()),
            })()})()

    async def _noop():
        return None

    async def fake_build_agent():
        from utils.paths import active_novel_id
        nid = active_novel_id()
        built_for.append(nid)
        return _FakeAgent(nid)

    monkeypatch.setattr("engine.setup_chat.agent.build_agent", fake_build_agent)

    agent_a = await hub._ensure_setup_chat_agent("novel-A")
    agent_b = await hub._ensure_setup_chat_agent("novel-B")

    assert agent_a.novel_id == "novel-A"
    assert agent_b.novel_id == "novel-B"
    assert built_for == ["novel-A", "novel-B"]
    again = await hub._ensure_setup_chat_agent("novel-A")
    assert again is agent_a
    assert built_for == ["novel-A", "novel-B"]


@pytest.mark.asyncio
async def test_ensure_story_sandbox_checkpointer_delegates_to_graph(monkeypatch):
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub

    hub = MessageHub()
    monkeypatch.setattr(mh_mod, "active_novel_id", lambda: "novelA")
    calls = []

    async def fake_ensure_checkpointer(novel_id: str):
        calls.append(novel_id)
        return object()

    monkeypatch.setattr("engine.story_sandbox.graph.ensure_checkpointer", fake_ensure_checkpointer)
    await hub._ensure_story_sandbox_checkpointer()
    assert calls == ["novelA"]


@pytest.mark.asyncio
async def test_message_hub_binds_director_llm_with_configured_params(monkeypatch):
    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    from api.services.message_hub import MessageHub

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _BoundLLM:
        def __init__(self, kwargs: dict) -> None:
            self.kwargs = kwargs

        async def astream(self, msgs, stream_usage=False):
            yield _Chunk("绑定后的正文")

    class _FakeLLM:
        model = "fake"

        def bind(self, **kwargs):
            return _BoundLLM(kwargs)

        async def astream(self, msgs, stream_usage=False):
            raise AssertionError("director 配置了参数时不该用裸 llm 流式")
            yield

        async def ainvoke(self, msgs):
            raise AssertionError("不该走这条路")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"llm_params": {"director": {"temperature": 0.8}}},
    )

    captured: dict = {}

    async def fake_dialogue(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        class _Msg:
            def __init__(self, content: str) -> None:
                self.content = content

        text = await author_turns.prose_turn([_Msg("sys"), _Msg("user")], step=0)
        captured["text"] = text

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", fake_dialogue)

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_author_loop(9)
    if (_t := hub._author_tasks.get("default")) is not None:
        await _t

    assert captured["text"] == "绑定后的正文"


@pytest.mark.asyncio
async def test_message_hub_call_llm_binds_params_for_non_director_node(monkeypatch):
    import engine.author_loop.dialogue_mode.chapter as dlg_mod
    from api.services.message_hub import MessageHub

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _BoundLLM:
        def __init__(self, kwargs: dict) -> None:
            self.kwargs = kwargs

        async def ainvoke(self, msgs):
            return _Resp("绑定后的审核结果")

    class _FakeLLM:
        model = "fake"

        def bind(self, **kwargs):
            return _BoundLLM(kwargs)

        async def ainvoke(self, msgs):
            raise AssertionError("review 配置了参数时不该用裸 llm")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"llm_params": {"review": {"temperature": 0.1}}},
    )

    captured: dict = {}

    async def fake_dialogue(chapter, call_llm, prose_style, *, emit, resume=False, author_turns=None):
        text, _, _ = await call_llm("system", "user", _log_step=0, _log_agent="review")
        captured["text"] = text

    monkeypatch.setattr(dlg_mod, "run_dialogue_chapter", fake_dialogue)

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    await hub.start_author_loop(9)
    if (_t := hub._author_tasks.get("default")) is not None:
        await _t

    assert captured["text"] == "绑定后的审核结果"


# ── story_sandbox live-turn snapshot ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_emit_sandbox_appends_to_live_snapshot_when_present(monkeypatch):
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub

    monkeypatch.setattr(mh_mod, "active_novel_id", lambda: "n")

    hub = MessageHub()
    hub._story_sandbox_live["n"] = {
        "novel_id": "n", "chapter": 1, "mode": "turn", "instruction": "x", "events": [],
    }
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    ev = {"type": "story_sandbox_token", "delta": "a"}

    await hub._emit_sandbox(ev)

    assert hub._story_sandbox_live["n"]["events"] == [ev]
    mock_ws.send_json.assert_awaited_once_with(ev)


@pytest.mark.asyncio
async def test_emit_sandbox_is_a_noop_bookkeeping_wise_when_no_live_snapshot():
    from api.services.message_hub import MessageHub

    hub = MessageHub()
    mock_ws = AsyncMock()
    hub._gateway._ws_clients.append(mock_ws)
    ev = {"type": "story_sandbox_token", "delta": "a"}

    await hub._emit_sandbox(ev)

    assert "default" not in hub._story_sandbox_live
    mock_ws.send_json.assert_awaited_once_with(ev)


@pytest.mark.asyncio
async def test_emit_sandbox_clears_live_snapshot_on_terminal_event(monkeypatch):
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub

    monkeypatch.setattr(mh_mod, "active_novel_id", lambda: "n")

    hub = MessageHub()
    hub._story_sandbox_live["n"] = {
        "novel_id": "n", "chapter": 1, "mode": "turn", "instruction": "x", "events": [],
    }

    await hub._emit_sandbox({"type": "story_sandbox_done"})

    assert "default" not in hub._story_sandbox_live


@pytest.mark.asyncio
async def test_emit_sandbox_does_not_clear_on_non_terminal_event():
    from api.services.message_hub import MessageHub

    hub = MessageHub()
    hub._story_sandbox_live["n"] = {
        "novel_id": "n", "chapter": 1, "mode": "turn", "instruction": "x", "events": [],
    }

    await hub._emit_sandbox({"type": "story_sandbox_states", "states": {}})

    assert hub._story_sandbox_live is not None


@pytest.mark.asyncio
async def test_story_sandbox_turn_live_snapshot_lifecycle(monkeypatch):
    """_story_sandbox_live fills in with the submitted instruction + events broadcast so far
    while a turn is in flight, and clears once the turn's terminal event fires."""
    import asyncio

    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    resume = asyncio.Event()

    async def fake_run_turn(
        novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene,
        call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest,
        guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract,
        guard_text_profile_mutate, guard_text_suggest,
        submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None,
    ):
        yield {"type": SandboxStepType.PROSE, "text": "半截正文"}
        await resume.wait()
        yield {"type": SandboxStepType.SUGGESTIONS, "options": ["继续"]}

    async def fake_broadcast(ev):
        pass

    import api.services.message_hub as mh_mod
    monkeypatch.setattr(mh_mod, "run_story_sandbox_turn", fake_run_turn)

    hub = MessageHub()
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续写")

    for _ in range(200):
        live = hub._story_sandbox_live.get("default")
        if live is not None and any(e["type"] == "story_sandbox_final" for e in live["events"]):
            break
        await asyncio.sleep(0.005)
    else:
        pytest.fail("story_sandbox_final never appeared in the live snapshot")

    live = hub._story_sandbox_live["default"]
    assert live["novel_id"] == mh_mod.active_novel_id()
    assert live["chapter"] == 1
    assert live["mode"] == "turn"
    assert live["instruction"] == "继续写"
    assert {"type": "story_sandbox_final", "content": "半截正文", "active_cast": []} in live["events"]
    assert {"type": "story_sandbox_recall_context", "recall_context": "", "recalled_settings": []} in live["events"]

    resume.set()
    if (_t := hub._story_sandbox_tasks.get("default")) is not None:
        await _t

    assert "default" not in hub._story_sandbox_live


@pytest.mark.asyncio
async def test_story_sandbox_rewrite_live_snapshot_lifecycle(monkeypatch):
    import asyncio

    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    resume = asyncio.Event()

    async def fake_rewrite_last_round(
        novel_id, chapter, feedback, *, write_turn, call_llm_derive_char, call_llm_derive_scene,
        call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest,
        guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract,
        guard_text_profile_mutate, guard_text_suggest, call_llm_identify=None,
        call_llm_dialogue_draft=None, branch_id=None,
    ):
        async def _gen():
            # PROSE steps aren't broadcast on the rewrite path (message_hub.py captures
            # step["text"] straight into a local var for the eventual rewrite_done payload,
            # with no intermediate broadcast) -- yield a STATE step first, which IS broadcast
            # (story_sandbox_states), so there's something in live["events"] to poll for below.
            yield {"type": SandboxStepType.STATE, "states": {"甲": {"mood": "紧张"}}, "scene_state": {}}
            yield {"type": SandboxStepType.PROSE, "text": "重写正文"}
            await resume.wait()
        return _gen()

    async def fake_broadcast(ev):
        pass

    import engine.story_sandbox.graph as graph_mod
    monkeypatch.setattr(graph_mod, "rewrite_last_round", fake_rewrite_last_round)

    hub = MessageHub()
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_rewrite(1, "重写反馈")

    for _ in range(200):
        live = hub._story_sandbox_live.get("default")
        if live is not None and live["events"]:
            break
        await asyncio.sleep(0.005)
    else:
        pytest.fail("_story_sandbox_live never populated for the rewrite flow")

    live = hub._story_sandbox_live["default"]
    assert live["mode"] == "rewrite"
    assert live["chapter"] == 1
    assert {
        "type": "story_sandbox_states", "states": {"甲": {"mood": "紧张"}}, "scene_state": {},
        "active_cast": [],
    } in live["events"]

    resume.set()
    if (_t := hub._story_sandbox_tasks.get("default")) is not None:
        await _t

    assert "default" not in hub._story_sandbox_live


@pytest.mark.asyncio
async def test_stop_story_sandbox_turn_clears_live_snapshot(monkeypatch):
    """Mirrors test_stop_story_sandbox_turn_cancels_and_restores's fixture shape (see
    tests/api/test_story_sandbox_api.py), plus the live-snapshot assertions."""
    import asyncio

    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    hub = MessageHub()
    started = asyncio.Event()

    async def fake_run_turn(
        novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene,
        call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest,
        guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract,
        guard_text_profile_mutate, guard_text_suggest,
        submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None,
    ):
        started.set()
        await asyncio.sleep(3600)
        yield {"type": SandboxStepType.SUGGESTIONS, "options": []}  # pragma: no cover -- never reached

    async def fake_broadcast(ev):
        pass

    async def fake_snapshot_state(novel_id, chapter, branch_id=None):
        return {}

    async def fake_restore_state(novel_id, chapter, values, branch_id=None):
        pass

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)
    monkeypatch.setattr("api.services.message_hub.snapshot_story_sandbox_state", fake_snapshot_state)
    monkeypatch.setattr("api.services.message_hub.restore_story_sandbox_state", fake_restore_state)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: object())

    await hub.start_story_sandbox_turn(1, "继续")
    await asyncio.wait_for(started.wait(), timeout=1)
    assert hub._story_sandbox_live is not None

    await hub.stop_story_sandbox_turn(1)

    assert "default" not in hub._story_sandbox_live


@pytest.mark.asyncio
async def test_story_sandbox_history_returns_live_round_when_scope_matches(monkeypatch):
    from api.services.message_hub import MessageHub

    async def fake_peek_state(novel_id, chapter, branch_id=None):
        return {"turns": [], "active_cast": {}}

    import engine.story_sandbox.graph as graph_mod
    monkeypatch.setattr(graph_mod, "peek_state", fake_peek_state)

    hub = MessageHub()
    hub._story_sandbox_live["novel-a"] = {
        "novel_id": "novel-a", "chapter": 3, "branch_id": "legacy", "mode": "turn", "instruction": "继续",
        "events": [{"type": "story_sandbox_token", "delta": "甲"}],
    }

    result = await hub.story_sandbox_history(3, novel_id="novel-a")

    assert result["live_round"] == {
        "mode": "turn", "instruction": "继续",
        "events": [{"type": "story_sandbox_token", "delta": "甲"}],
    }


@pytest.mark.asyncio
async def test_story_sandbox_history_live_round_none_when_chapter_mismatches(monkeypatch):
    from api.services.message_hub import MessageHub

    async def fake_peek_state(novel_id, chapter, branch_id=None):
        return {"turns": [], "active_cast": {}}

    import engine.story_sandbox.graph as graph_mod
    monkeypatch.setattr(graph_mod, "peek_state", fake_peek_state)

    hub = MessageHub()
    hub._story_sandbox_live["novel-a"] = {
        "novel_id": "novel-a", "chapter": 3, "branch_id": "legacy", "mode": "turn", "instruction": "继续",
        "events": [],
    }

    result = await hub.story_sandbox_history(4, novel_id="novel-a")

    assert result["live_round"] is None


@pytest.mark.asyncio
async def test_story_sandbox_history_live_round_none_when_novel_mismatches(monkeypatch):
    from api.services.message_hub import MessageHub

    async def fake_peek_state(novel_id, chapter, branch_id=None):
        return {"turns": [], "active_cast": {}}

    import engine.story_sandbox.graph as graph_mod
    monkeypatch.setattr(graph_mod, "peek_state", fake_peek_state)

    hub = MessageHub()
    hub._story_sandbox_live["novel-a"] = {
        "novel_id": "novel-a", "chapter": 3, "branch_id": "legacy", "mode": "turn", "instruction": "继续",
        "events": [],
    }

    result = await hub.story_sandbox_history(3, novel_id="novel-b")

    assert result["live_round"] is None


@pytest.mark.asyncio
async def test_story_sandbox_history_live_round_none_when_nothing_in_flight(monkeypatch):
    from api.services.message_hub import MessageHub

    async def fake_peek_state(novel_id, chapter, branch_id=None):
        return {"turns": [], "active_cast": {}}

    import engine.story_sandbox.graph as graph_mod
    monkeypatch.setattr(graph_mod, "peek_state", fake_peek_state)

    hub = MessageHub()

    result = await hub.story_sandbox_history(3, novel_id="novel-a")

    assert result["live_round"] is None

def test_is_story_sandbox_busy_is_per_novel():
    from api.services.message_hub import MessageHub

    hub = MessageHub()
    hub._story_sandbox_tasks["A"] = type("_T", (), {"done": lambda self: False})()
    assert hub.is_story_sandbox_busy("A") is True
    assert hub.is_story_sandbox_busy("B") is False


def test_is_story_sandbox_busy_defaults_to_active_novel(monkeypatch):
    from api.services.message_hub import MessageHub

    hub = MessageHub()
    hub._story_sandbox_tasks["A"] = type("_T", (), {"done": lambda self: False})()
    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "A")
    assert hub.is_story_sandbox_busy() is True
    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "B")
    assert hub.is_story_sandbox_busy() is False

@pytest.mark.asyncio
async def test_story_sandbox_tasks_isolated_across_novels(monkeypatch):
    """Two novels' sandbox turns run concurrently without one clobbering the other's task slot."""
    from api.services.message_hub import MessageHub

    hub = MessageHub()
    started = {"A": asyncio.Event(), "B": asyncio.Event()}
    release = {"A": asyncio.Event(), "B": asyncio.Event()}

    async def fake_snapshot(novel_id, chapter, *, branch_id):
        return {}

    async def fake_run_turn(novel_id, chapter, text, **kwargs):
        started[novel_id].set()
        await release[novel_id].wait()
        return
        yield  # pragma: no cover - never reached, keeps this an async generator

    monkeypatch.setattr(
        "api.services.message_hub.snapshot_story_sandbox_state", fake_snapshot,
    )
    monkeypatch.setattr(
        "api.services.message_hub.run_story_sandbox_turn", fake_run_turn,
    )
    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "A")
    await hub.start_story_sandbox_turn(1, "text-A")
    assert "A" in hub._story_sandbox_tasks

    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "B")
    await hub.start_story_sandbox_turn(1, "text-B")
    assert "B" in hub._story_sandbox_tasks
    assert set(hub._story_sandbox_tasks) == {"A", "B"}

    await asyncio.wait_for(started["A"].wait(), timeout=1)
    await asyncio.wait_for(started["B"].wait(), timeout=1)
    release["A"].set()
    release["B"].set()
    await asyncio.gather(*hub._story_sandbox_tasks.values(), return_exceptions=True)


@pytest.mark.asyncio
async def test_trigger_system_notice_turn_enqueues_when_busy(monkeypatch):
    """Busy agent must not start a turn immediately; item stays queued until drain."""
    from api.services.message_hub import MessageHub
    from api.services.setup_chat_turn_queue import SETUP_CHAT_TURN_QUEUE, SetupChatTurnKind

    hub = MessageHub()
    SETUP_CHAT_TURN_QUEUE.clear("n")
    monkeypatch.setattr(hub, "is_setup_chat_busy", lambda novel_id=None: True)
    agent_build_called = False

    async def boom_build(_novel_id: str):
        nonlocal agent_build_called
        agent_build_called = True
        raise AssertionError("must not build the agent while busy")

    monkeypatch.setattr(hub, "_ensure_setup_chat_agent", boom_build)

    await hub.trigger_system_notice_turn("n", "第3章后台审查结果：全部通过。")

    assert SETUP_CHAT_TURN_QUEUE.len_for("n") == 1
    item = SETUP_CHAT_TURN_QUEUE.peek("n")
    assert item is not None
    assert item.kind == SetupChatTurnKind.SYSTEM_NOTICE
    assert "全部通过" in item.summary_text
    assert agent_build_called is False
    SETUP_CHAT_TURN_QUEUE.clear("n")


@pytest.mark.asyncio
async def test_setup_chat_queue_drains_after_turn_finishes(monkeypatch, tmp_path):
    """Simulate user turn finishing: queued notice should start automatically."""
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub
    from api.services.setup_chat_turn_queue import (
        SETUP_CHAT_TURN_QUEUE,
        SetupChatTurnItem,
        SetupChatTurnKind,
    )

    session_dir = str(tmp_path / "session")
    monkeypatch.setattr(mh_mod, "setup_chat_session_dir", lambda novel_id=None: session_dir)

    hub = MessageHub()
    SETUP_CHAT_TURN_QUEUE.clear("n")
    monkeypatch.setattr(hub, "broadcast", AsyncMock())
    monkeypatch.setattr(hub, "_make_setup_chat_accountant", lambda novel_id: AsyncMock())
    monkeypatch.setattr(hub, "_ensure_setup_chat_agent", AsyncMock(return_value=object()))

    run_calls: list[str] = []

    async def fake_run_turn(agent, novel_id, text, emit, accountant):
        run_calls.append(text)

    monkeypatch.setattr(mh_mod, "run_turn", fake_run_turn)

    SETUP_CHAT_TURN_QUEUE.enqueue(
        SetupChatTurnItem("n", SetupChatTurnKind.SYSTEM_NOTICE, summary_text="queued notice")
    )
    await hub._try_drain_setup_chat_queue("n")
    await hub._setup_chat_tasks["n"]

    assert len(run_calls) == 1
    assert "queued notice" in run_calls[0]
    assert SETUP_CHAT_TURN_QUEUE.len_for("n") == 0
    SETUP_CHAT_TURN_QUEUE.clear("n")


@pytest.mark.asyncio
async def test_setup_chat_queue_drains_fifo_two_notices(monkeypatch, tmp_path):
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub
    from api.services.setup_chat_turn_queue import SETUP_CHAT_TURN_QUEUE

    session_dir = str(tmp_path / "session")
    monkeypatch.setattr(mh_mod, "setup_chat_session_dir", lambda novel_id=None: session_dir)

    hub = MessageHub()
    SETUP_CHAT_TURN_QUEUE.clear("n")
    monkeypatch.setattr(hub, "broadcast", AsyncMock())
    monkeypatch.setattr(hub, "_make_setup_chat_accountant", lambda novel_id: AsyncMock())
    monkeypatch.setattr(hub, "_ensure_setup_chat_agent", AsyncMock(return_value=object()))

    summaries: list[str] = []
    release = asyncio.Event()

    async def fake_run_turn(agent, novel_id, text, emit, accountant):
        summaries.append(text)
        await release.wait()

    monkeypatch.setattr(mh_mod, "run_turn", fake_run_turn)

    await hub.trigger_system_notice_turn("n", "notice one")
    await hub.trigger_system_notice_turn("n", "notice two")

    assert SETUP_CHAT_TURN_QUEUE.len_for("n") == 1
    release.set()
    await hub._setup_chat_tasks["n"]
    assert len(summaries) == 2
    assert "notice one" in summaries[0]
    assert "notice two" in summaries[1]
    assert SETUP_CHAT_TURN_QUEUE.len_for("n") == 0
    SETUP_CHAT_TURN_QUEUE.clear("n")


@pytest.mark.asyncio
async def test_trigger_system_notice_turn_merges_bursts_while_busy(monkeypatch, tmp_path):
    """Character review, skeleton review, timeline cascade etc. each call
    trigger_system_notice_turn independently once they finish. If several land while the
    agent is busy running the first notice's turn, they must fold into one queued item and
    surface as a single chat-agent turn -- not one turn per background job."""
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub
    from api.services.setup_chat_turn_queue import SETUP_CHAT_TURN_QUEUE

    session_dir = str(tmp_path / "session")
    monkeypatch.setattr(mh_mod, "setup_chat_session_dir", lambda novel_id=None: session_dir)

    hub = MessageHub()
    SETUP_CHAT_TURN_QUEUE.clear("n")
    monkeypatch.setattr(hub, "broadcast", AsyncMock())
    monkeypatch.setattr(hub, "_make_setup_chat_accountant", lambda novel_id: AsyncMock())
    monkeypatch.setattr(hub, "_ensure_setup_chat_agent", AsyncMock(return_value=object()))

    summaries: list[str] = []
    release = asyncio.Event()

    async def fake_run_turn(agent, novel_id, text, emit, accountant):
        summaries.append(text)
        await release.wait()

    monkeypatch.setattr(mh_mod, "run_turn", fake_run_turn)

    # First call finds the agent idle -> drains immediately and starts an in-flight turn
    # (which blocks on `release`). The next two calls land while that turn is running, so
    # they must fold into a single queued item rather than each starting their own turn.
    await hub.trigger_system_notice_turn("n", "character review: 角色A修复完成")
    await hub.trigger_system_notice_turn("n", "skeleton review: 第5章骨架修复完成")
    await hub.trigger_system_notice_turn("n", "timeline cascade: 角色B档案推演完成")

    assert SETUP_CHAT_TURN_QUEUE.len_for("n") == 1
    merged = SETUP_CHAT_TURN_QUEUE.peek("n").summary_text
    assert "第5章骨架修复完成" in merged
    assert "角色B档案推演完成" in merged

    release.set()
    await hub._setup_chat_tasks["n"]

    assert len(summaries) == 2  # one in-flight turn (notice 1) + one merged turn (notices 2+3)
    assert "角色A修复完成" in summaries[0]
    assert "第5章骨架修复完成" in summaries[1]
    assert "角色B档案推演完成" in summaries[1]
    assert SETUP_CHAT_TURN_QUEUE.len_for("n") == 0
    SETUP_CHAT_TURN_QUEUE.clear("n")


@pytest.mark.asyncio
async def test_reset_setup_chat_clears_turn_queue(monkeypatch):
    from api.services.message_hub import MessageHub
    from api.services.setup_chat_turn_queue import (
        SETUP_CHAT_TURN_QUEUE,
        SetupChatTurnItem,
        SetupChatTurnKind,
    )

    hub = MessageHub()
    SETUP_CHAT_TURN_QUEUE.enqueue(
        SetupChatTurnItem("n", SetupChatTurnKind.SYSTEM_NOTICE, summary_text="pending")
    )
    await hub.reset_setup_chat("n")
    assert SETUP_CHAT_TURN_QUEUE.len_for("n") == 0


@pytest.mark.asyncio
async def test_trigger_system_notice_turn_runs_a_real_turn_when_idle(monkeypatch, tmp_path):
    """Idle case: records a system-authored line (not attributed to the user), then
    drives a real run_turn call whose input text carries the structured summary."""
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub
    from engine.setup_chat.session_record import load_messages

    session_dir = str(tmp_path / "session")
    monkeypatch.setattr(mh_mod, "setup_chat_session_dir", lambda novel_id=None: session_dir)

    hub = MessageHub()
    monkeypatch.setattr(hub, "is_setup_chat_busy", lambda novel_id=None: False)
    monkeypatch.setattr(hub, "broadcast", AsyncMock())
    monkeypatch.setattr(hub, "_make_setup_chat_accountant", lambda novel_id: AsyncMock())
    monkeypatch.setattr(hub, "_ensure_setup_chat_agent", AsyncMock(return_value=object()))

    captured_calls = []

    async def fake_run_turn(agent, novel_id, text, emit, accountant):
        captured_calls.append((novel_id, text))

    monkeypatch.setattr(mh_mod, "run_turn", fake_run_turn)

    summary = "第3章后台审查结果：跑了 1 轮。全部通过。"
    await hub.trigger_system_notice_turn("n", summary)
    await hub._setup_chat_tasks["n"]

    assert len(captured_calls) == 1
    novel_id, text = captured_calls[0]
    assert novel_id == "n"
    assert summary in text

    msgs = load_messages(session_dir)
    assert any(m.get("role") == "system" for m in msgs)
    assert not any(m.get("role") == "user" for m in msgs)  # not misattributed to the user


@pytest.mark.asyncio
async def test_trigger_system_notice_turn_clears_task_bookkeeping_after_completion(
    monkeypatch, tmp_path,
):
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub

    session_dir = str(tmp_path / "session")
    monkeypatch.setattr(mh_mod, "setup_chat_session_dir", lambda novel_id=None: session_dir)

    hub = MessageHub()
    monkeypatch.setattr(hub, "is_setup_chat_busy", lambda novel_id=None: False)
    monkeypatch.setattr(hub, "broadcast", AsyncMock())
    monkeypatch.setattr(hub, "_make_setup_chat_accountant", lambda novel_id: AsyncMock())
    monkeypatch.setattr(hub, "_ensure_setup_chat_agent", AsyncMock(return_value=object()))

    async def fake_run_turn(agent, novel_id, text, emit, accountant):
        pass

    monkeypatch.setattr(mh_mod, "run_turn", fake_run_turn)

    await hub.trigger_system_notice_turn("n", "全部通过。")
    await hub._setup_chat_tasks["n"]

    assert "n" not in hub._setup_chat_tasks
    assert "n" not in hub._setup_chat_live


@pytest.mark.asyncio
async def test_trigger_system_notice_turn_writes_target_novel_session_not_active_novel(
    monkeypatch, tmp_path,
):
    """Background notice must land in the job's novel session, not whichever novel is active."""
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub
    from engine.setup_chat.session_record import load_messages
    from utils.paths import setup_chat_session_dir

    novels_root = tmp_path / "novels"
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(novels_root))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "novel-a")

    hub = MessageHub()
    monkeypatch.setattr(hub, "is_setup_chat_busy", lambda novel_id=None: False)
    broadcast = AsyncMock()
    monkeypatch.setattr(hub, "broadcast", broadcast)
    monkeypatch.setattr(hub, "_make_setup_chat_accountant", lambda novel_id: AsyncMock())
    monkeypatch.setattr(hub, "_ensure_setup_chat_agent", AsyncMock(return_value=object()))

    async def fake_run_turn(agent, novel_id, text, emit, accountant):
        pass

    monkeypatch.setattr(mh_mod, "run_turn", fake_run_turn)

    await hub.trigger_system_notice_turn("novel-b", "全部通过。")
    await hub._setup_chat_tasks["novel-b"]

    assert load_messages(setup_chat_session_dir("novel-a")) == []
    msgs_b = load_messages(setup_chat_session_dir("novel-b"))
    assert any(
        m.get("role") == "system" and "后台系统事件" in m.get("content", "")
        for m in msgs_b
    )
    start_calls = [c.args[0] for c in broadcast.await_args_list if c.args]
    assert any(ev.get("type") == "setup_chat_start" and ev.get("novel_id") == "novel-b" for ev in start_calls)


@pytest.fixture
def _clean_review_feedback():
    from api.services.setup_chat_review_feedback import REVIEW_FEEDBACK
    REVIEW_FEEDBACK.clear_all("n")
    yield REVIEW_FEEDBACK
    REVIEW_FEEDBACK.clear_all("n")


@pytest.mark.asyncio
async def test_report_review_done_holds_batch_while_pending(monkeypatch, _clean_review_feedback):
    from api.services.message_hub import MessageHub
    from api.services.setup_chat_review_feedback import ReviewFeedbackEntry, ReviewStatus

    rf = _clean_review_feedback
    hub = MessageHub()
    notices: list[tuple[str, str]] = []
    monkeypatch.setattr(hub, "is_setup_chat_busy", lambda novel_id=None: False)

    async def fake_trigger(novel_id, text):
        notices.append((novel_id, text))

    monkeypatch.setattr(hub, "trigger_system_notice_turn", fake_trigger)

    rf.mark_pending("n", ("character", "甲"))
    rf.mark_pending("n", ("character", "乙"))

    await hub.report_review_done(
        "n", ("character", "甲"),
        [(("character", "甲"), ReviewFeedbackEntry("character", "角色「甲」", ReviewStatus.CLEAN, ""))],
    )
    assert notices == []  # 乙 still pending

    await hub.report_review_done(
        "n", ("character", "乙"),
        [(("character", "乙"), ReviewFeedbackEntry("character", "角色「乙」", ReviewStatus.RESOLVED, "已修"))],
    )
    assert len(notices) == 1
    assert "角色「甲」" in notices[0][1] and "角色「乙」" in notices[0][1]
    assert rf.snapshot("n") == []  # buffer drained


@pytest.mark.asyncio
async def test_maybe_flush_defers_while_agent_busy_then_flushes_on_turn_finished(
    monkeypatch, _clean_review_feedback
):
    from api.services.message_hub import MessageHub
    from api.services.setup_chat_review_feedback import ReviewFeedbackEntry, ReviewStatus

    rf = _clean_review_feedback
    hub = MessageHub()
    notices: list[str] = []
    busy = {"v": True}
    monkeypatch.setattr(hub, "is_setup_chat_busy", lambda novel_id=None: busy["v"])

    async def fake_trigger(novel_id, text):
        notices.append(text)

    monkeypatch.setattr(hub, "trigger_system_notice_turn", fake_trigger)
    monkeypatch.setattr(hub, "_finish_incomplete_image_progress", AsyncMock())
    monkeypatch.setattr(hub, "_try_drain_setup_chat_queue", AsyncMock())

    rf.mark_pending("n", ("world",))
    await hub.report_review_done(
        "n", ("world",),
        [(("world",), ReviewFeedbackEntry("world", "世界观", ReviewStatus.RESOLVED, "已修"))],
    )
    assert notices == []  # pending clear but agent busy

    busy["v"] = False
    await hub._on_setup_chat_turn_finished("n")
    assert len(notices) == 1 and "世界观" in notices[0]


@pytest.mark.asyncio
async def test_report_review_done_empty_entries_only_releases_barrier(
    monkeypatch, _clean_review_feedback
):
    from api.services.message_hub import MessageHub
    from api.services.setup_chat_review_feedback import ReviewFeedbackEntry, ReviewStatus

    rf = _clean_review_feedback
    hub = MessageHub()
    notices: list[str] = []
    monkeypatch.setattr(hub, "is_setup_chat_busy", lambda novel_id=None: False)

    async def fake_trigger(novel_id, text):
        notices.append(text)

    monkeypatch.setattr(hub, "trigger_system_notice_turn", fake_trigger)

    rf.mark_pending("n", ("character", "甲"))
    rf.record("n", ("world",), ReviewFeedbackEntry("world", "世界观", ReviewStatus.CLEAN, ""))

    # 甲 was deleted mid-review -> empty entries, just release its barrier unit
    await hub.report_review_done("n", ("character", "甲"), [])
    assert len(notices) == 1  # world entry now flushes (no pending left)
    assert "世界观" in notices[0]


@pytest.mark.asyncio
async def test_reset_setup_chat_clears_review_feedback(monkeypatch, _clean_review_feedback, tmp_path):
    import api.services.message_hub as mh_mod
    from api.services.message_hub import MessageHub
    from api.services.setup_chat_review_feedback import ReviewFeedbackEntry, ReviewStatus

    rf = _clean_review_feedback
    monkeypatch.setattr(mh_mod, "active_novel_id", lambda: "n")
    hub = MessageHub()
    monkeypatch.setattr(hub, "broadcast", AsyncMock())

    rf.mark_pending("n", ("world",))
    rf.record("n", ("world",), ReviewFeedbackEntry("world", "世界观", ReviewStatus.CLEAN, ""))
    await hub.reset_setup_chat("n")
    assert rf.has_pending("n") is False and rf.snapshot("n") == []

