import pytest
from api.services.gateway import Gateway
from loguru import logger


class _FakeWS:
    def __init__(self, *, fail=False):
        self.sent: list = []
        self.fail = fail

    async def send_json(self, ev):
        if self.fail:
            raise RuntimeError("dead")
        self.sent.append(ev)


@pytest.mark.asyncio
async def test_broadcast_buffers_and_sends():
    gw = Gateway()
    ws = _FakeWS()
    await gw.add_client(ws)
    await gw.broadcast({"type": "x", "n": 1})
    assert ws.sent == [{"type": "x", "n": 1, "_seq": 1}]


@pytest.mark.asyncio
async def test_add_client_replays_buffer():
    gw = Gateway()
    await gw.broadcast({"type": "a"})
    await gw.broadcast({"type": "b"})
    ws = _FakeWS()
    await gw.add_client(ws)
    assert ws.sent == [{"type": "a", "_seq": 1}, {"type": "b", "_seq": 2}]


@pytest.mark.asyncio
async def test_broadcast_drops_dead_client():
    gw = Gateway()
    dead = _FakeWS(fail=True)
    await gw.add_client(dead)  #Play back an empty buffer and do not trigger send
    await gw.broadcast({"type": "x"})  #send throws error → clean
    live = _FakeWS()
    await gw.add_client(live)
    await gw.broadcast({"type": "y"})
    assert live.sent[-1] == {"type": "y", "_seq": 2}


@pytest.mark.asyncio
async def test_add_client_since_seq_skips_already_seen_events():
    """Reconnecting with since_seq == the highest _seq already applied should replay nothing
    new -- the whole point of the seq handshake is to avoid re-applying buffered events the
    client already processed before a plain reconnect (e.g. a flaky connection dropping and
    coming back), instead of blasting the full buffer every time."""
    gw = Gateway()
    await gw.broadcast({"type": "a"})
    await gw.broadcast({"type": "b"})
    ws = _FakeWS()
    await gw.add_client(ws, since_seq=1)
    assert ws.sent == [{"type": "b", "_seq": 2}]


@pytest.mark.asyncio
async def test_add_client_since_seq_zero_replays_full_buffer():
    """since_seq defaults to 0 -- a first-time connect (no prior state) still gets the full
    buffer, same as before this feature existed."""
    gw = Gateway()
    await gw.broadcast({"type": "a"})
    await gw.broadcast({"type": "b"})
    ws = _FakeWS()
    await gw.add_client(ws)
    assert ws.sent == [{"type": "a", "_seq": 1}, {"type": "b", "_seq": 2}]


@pytest.mark.asyncio
async def test_add_client_since_seq_at_or_beyond_buffer_head_replays_nothing():
    gw = Gateway()
    await gw.broadcast({"type": "a"})
    ws = _FakeWS()
    await gw.add_client(ws, since_seq=999)
    assert ws.sent == []


def test_remove_client():
    gw = Gateway()
    ws = _FakeWS()
    gw._ws_clients.append(ws)
    gw.remove_client(ws)
    assert ws not in gw._ws_clients


def _token(agent, delta, role=None):
    ev = {"type": "author_loop_token", "agent": agent, "delta": delta}
    if role is not None:
        ev["role"] = role
    return ev


@pytest.mark.asyncio
async def test_token_stream_aggregated_logged_once_on_flush():
    """Streaming tokens do not record logs one by one; they are integrated into one [ws-stream] only after the entire segment is collected (in case of non-token events)."""
    gw = Gateway()
    cap: list[str] = []
    sink = logger.add(lambda m: cap.append(str(m)), level="INFO")
    try:
        for d in ("亮", "晶晶", "的水痕。"):
            await gw.broadcast(_token("character", d, role="爱丽丝"))
        mid = "".join(cap)
        assert "[ws-send]" not in mid     #tokens are never itemized [ws-send]
        assert "[ws-stream]" not in mid    #The flow has not ended and has not been integrated yet.
        await gw.broadcast({"type": "author_loop_state", "index": 0, "characters": []})  #non-token → flush
    finally:
        logger.remove(sink)
    out = "".join(cap)
    assert "[ws-stream]" in out
    assert "爱丽丝" in out and "亮晶晶的水痕。" in out  #The integrated full text once
    assert "tokens=3" in out


@pytest.mark.asyncio
async def test_tokens_still_forwarded_to_frontend():
    """
Aggregating logs does not affect forwarding: each token is still sent_json to the front end as usual."""
    gw = Gateway()
    ws = _FakeWS()
    await gw.add_client(ws)
    await gw.broadcast(_token("character", "亮", role="爱丽丝"))
    await gw.broadcast(_token("character", "晶晶", role="爱丽丝"))
    assert ws.sent == [_token("character", "亮", role="爱丽丝"), _token("character", "晶晶", role="爱丽丝")]


@pytest.mark.asyncio
async def test_token_stream_flushes_on_agent_role_switch():
    """Switch agent/role → The previous stream integrates logs first."""
    gw = Gateway()
    cap: list[str] = []
    sink = logger.add(lambda m: cap.append(str(m)), level="INFO")
    try:
        await gw.broadcast(_token("director", "旁白句"))
        await gw.broadcast(_token("character", "台词句", role="甲"))  #Cut flow → flush director
    finally:
        logger.remove(sink)
    out = "".join(cap)
    assert "[ws-stream]" in out and "旁白句" in out  #director flow integrated


@pytest.mark.asyncio
async def test_story_sandbox_token_stream_aggregated_logged_once_on_flush():
    """story_sandbox_token has no agent/role -- must still be aggregated (not itemized per
    token) like author_loop_token, keyed on event type alone."""
    gw = Gateway()
    cap: list[str] = []
    sink = logger.add(lambda m: cap.append(str(m)), level="INFO")
    try:
        for d in ("他", "抬", "起头。"):
            await gw.broadcast({"type": "story_sandbox_token", "delta": d})
        mid = "".join(cap)
        assert "[ws-send]" not in mid
        assert "[ws-stream]" not in mid
        await gw.broadcast({"type": "story_sandbox_final", "content": "他抬起头。"})  #non-token → flush
    finally:
        logger.remove(sink)
    out = "".join(cap)
    assert "[ws-stream]" in out
    assert "他抬起头。" in out
    assert "tokens=3" in out


@pytest.mark.asyncio
async def test_token_stream_flushes_on_type_switch():
    """story_sandbox_token giving way to story_sandbox_rewrite_token must flush the first
    stream even though neither carries an agent/role to key on."""
    gw = Gateway()
    cap: list[str] = []
    sink = logger.add(lambda m: cap.append(str(m)), level="INFO")
    try:
        await gw.broadcast({"type": "story_sandbox_token", "delta": "原句"})
        await gw.broadcast({"type": "story_sandbox_rewrite_token", "delta": "改写句"})
    finally:
        logger.remove(sink)
    out = "".join(cap)
    assert "[ws-stream]" in out and "原句" in out


@pytest.mark.asyncio
async def test_setup_chat_token_stream_aggregated_logged_once_on_flush():
    """setup_chat_token has no agent/role either -- must be aggregated like the other
    streaming-token event types instead of itemized to [ws-send] per token."""
    gw = Gateway()
    cap: list[str] = []
    sink = logger.add(lambda m: cap.append(str(m)), level="INFO")
    try:
        for d in ("好", "的，", "我明白了。"):
            await gw.broadcast({"type": "setup_chat_token", "delta": d})
        mid = "".join(cap)
        assert "[ws-send]" not in mid
        assert "[ws-stream]" not in mid
        await gw.broadcast({"type": "setup_chat_final", "content": "好的，我明白了。"})  #non-token → flush
    finally:
        logger.remove(sink)
    out = "".join(cap)
    assert "[ws-stream]" in out
    assert "好的，我明白了。" in out
    assert "tokens=3" in out


@pytest.mark.asyncio
async def test_setup_chat_events_not_buffered_or_replayed():
    gw = Gateway()
    ws1 = _FakeWS()
    await gw.add_client(ws1)
    await gw.broadcast({"type": "setup_chat_final", "content": "ok"})
    await gw.broadcast({"type": "author_loop_state", "index": 0, "characters": []})
    assert [e["type"] for e in gw._buffer] == ["author_loop_state"]
    ws2 = _FakeWS()
    await gw.add_client(ws2)
    assert ws2.sent == [{"type": "author_loop_state", "index": 0, "characters": [], "_seq": 1}]
    assert {"type": "setup_chat_final", "content": "ok"} in ws1.sent


@pytest.mark.asyncio
async def test_story_sandbox_events_not_buffered_or_replayed():
    """Regression: story_sandbox_* used to fall through to the replay buffer, so an F5 refresh
    right after a round finished would reconnect, replay that round's own events (token/final/
    states/suggestions/done), and the frontend's WS reducer would append a second, duplicate
    copy of the round already returned by /api/story-sandbox/history."""
    gw = Gateway()
    ws1 = _FakeWS()
    await gw.add_client(ws1)
    await gw.broadcast({"type": "story_sandbox_token", "delta": "他"})
    await gw.broadcast({"type": "story_sandbox_final", "content": "他抬起头。"})
    await gw.broadcast({"type": "story_sandbox_states", "states": {}, "scene_state": {}})
    await gw.broadcast({"type": "story_sandbox_suggestions", "options": []})
    await gw.broadcast({"type": "story_sandbox_done"})
    await gw.broadcast({"type": "author_loop_state", "index": 0, "characters": []})
    assert [e["type"] for e in gw._buffer] == ["author_loop_state"]
    ws2 = _FakeWS()
    await gw.add_client(ws2)
    assert ws2.sent == [{"type": "author_loop_state", "index": 0, "characters": [], "_seq": 1}]


@pytest.mark.asyncio
async def test_archive_build_events_not_buffered_or_replayed():
    """Regression: archive_build_* used to fall through to the replay buffer, and (unlike
    setup_chat_*/story_sandbox_*) nothing ever calls clear_buffer() after a normal successful
    build -- only chapter reset/app shutdown do. So a completed build's start/progress/done
    sequence sat in the buffer indefinitely, and ANY later reconnect (a plain page refresh
    included) replayed it, making the frontend's building->done toast re-fire on every refresh
    long after the build had actually finished."""
    gw = Gateway()
    ws1 = _FakeWS()
    await gw.add_client(ws1)
    await gw.broadcast({"type": "archive_build_start", "total": 2})
    await gw.broadcast({"type": "archive_build_progress", "chapter": 1, "index": 1, "total": 2, "ok": True})
    await gw.broadcast({"type": "archive_build_done"})
    await gw.broadcast({"type": "author_loop_state", "index": 0, "characters": []})
    assert [e["type"] for e in gw._buffer] == ["author_loop_state"]
    ws2 = _FakeWS()
    await gw.add_client(ws2)
    assert ws2.sent == [{"type": "author_loop_state", "index": 0, "characters": [], "_seq": 1}]


@pytest.mark.asyncio
async def test_author_loop_terminal_events_not_buffered_or_replayed():
    """author_loop_done/error/stopped: current status is always re-derivable via REST, same as
    archive_build_*, so these three don't need to survive in the buffer themselves."""
    gw = Gateway()
    ws1 = _FakeWS()
    await gw.add_client(ws1)
    await gw.broadcast({"type": "author_loop_done", "novel_id": "novel-A"})
    await gw.broadcast({"type": "author_loop_error", "novel_id": "novel-A", "error": "x"})
    await gw.broadcast({"type": "author_loop_stopped", "novel_id": "novel-A"})
    assert gw._buffer == []
    ws2 = _FakeWS()
    await gw.add_client(ws2)
    assert ws2.sent == []


@pytest.mark.asyncio
async def test_author_loop_terminal_event_prunes_this_run_own_buffered_milestones():
    """Regression: clear_buffer() is chapter-reset/shutdown-only (same gap archive_build_* had),
    so a finished chapter's start/segment/state/summary/chapter_progress milestones stayed
    buffered indefinitely -- any later reconnect (a plain page refresh included) replayed the
    whole run again, spuriously re-marking the 主笔 tab's unread badge for a chapter that had
    already finished and been seen. The terminal event must prune this novel's OTHER already-
    buffered author_loop_* entries too, not just skip buffering itself."""
    gw = Gateway()
    ws1 = _FakeWS()
    await gw.add_client(ws1)
    await gw.broadcast({"type": "author_loop_start", "novel_id": "novel-A", "chapter": 3})
    await gw.broadcast({"type": "author_loop_segment", "novel_id": "novel-A", "draft": False})
    await gw.broadcast({"type": "author_loop_state", "novel_id": "novel-A", "index": 0, "characters": []})
    await gw.broadcast({"type": "author_loop_done", "novel_id": "novel-A"})
    assert gw._buffer == []
    ws2 = _FakeWS()
    await gw.add_client(ws2)
    assert ws2.sent == []


@pytest.mark.asyncio
async def test_author_loop_terminal_event_only_prunes_same_novel():
    """A finished run's prune must not touch another novel's still-in-progress milestones."""
    gw = Gateway()
    ws1 = _FakeWS()
    await gw.add_client(ws1)
    await gw.broadcast({"type": "author_loop_state", "novel_id": "novel-B", "index": 0, "characters": []})
    await gw.broadcast({"type": "author_loop_done", "novel_id": "novel-A"})
    assert [e["type"] for e in gw._buffer] == ["author_loop_state"]
    assert gw._buffer[0]["novel_id"] == "novel-B"


@pytest.mark.asyncio
async def test_author_loop_terminal_event_does_not_prune_unrelated_event_types():
    """The prune is scoped to the "author_loop_" type prefix -- a buffered non-author_loop event
    for the same novel_id must survive a terminal author_loop event."""
    gw = Gateway()
    ws1 = _FakeWS()
    await gw.add_client(ws1)
    await gw.broadcast({"type": "some_other_event", "novel_id": "novel-A"})
    await gw.broadcast({"type": "author_loop_done", "novel_id": "novel-A"})
    assert [e["type"] for e in gw._buffer] == ["some_other_event"]


@pytest.mark.asyncio
async def test_lifecycle_event_delivered_regardless_of_focus():
    gw = Gateway()
    ws = _FakeWS()
    await gw.add_client(ws)
    gw.set_focus("novel-A")
    await gw.broadcast({"type": "story_sandbox_done", "novel_id": "novel-B"})
    assert ws.sent == [{"type": "story_sandbox_done", "novel_id": "novel-B"}]


@pytest.mark.asyncio
async def test_content_event_filtered_when_not_focused():
    gw = Gateway()
    ws = _FakeWS()
    await gw.add_client(ws)
    gw.set_focus("novel-A")
    await gw.broadcast({"type": "story_sandbox_token", "novel_id": "novel-B", "delta": "x"})
    assert ws.sent == []


@pytest.mark.asyncio
async def test_setup_chat_final_filtered_when_not_focused():
    gw = Gateway()
    ws = _FakeWS()
    await gw.add_client(ws)
    gw.set_focus("novel-A")
    await gw.broadcast({"type": "setup_chat_final", "novel_id": "novel-B", "content": "别的书回复"})
    assert ws.sent == []


@pytest.mark.asyncio
async def test_setup_chat_final_delivered_when_focused():
    gw = Gateway()
    ws = _FakeWS()
    await gw.add_client(ws)
    gw.set_focus("novel-A")
    await gw.broadcast({"type": "setup_chat_final", "novel_id": "novel-A", "content": "本书回复"})
    assert ws.sent == [{"type": "setup_chat_final", "novel_id": "novel-A", "content": "本书回复"}]
@pytest.mark.asyncio
async def test_content_event_delivered_when_focused():
    gw = Gateway()
    ws = _FakeWS()
    await gw.add_client(ws)
    gw.set_focus("novel-A")
    await gw.broadcast({"type": "story_sandbox_token", "novel_id": "novel-A", "delta": "x"})
    assert ws.sent == [{"type": "story_sandbox_token", "novel_id": "novel-A", "delta": "x"}]


@pytest.mark.asyncio
async def test_content_event_delivered_before_any_focus_set():
    """Fail-open: before the first /api/novels/active call in a fresh process, there is no
    focus pointer yet -- don't silently black-hole events."""
    gw = Gateway()
    ws = _FakeWS()
    await gw.add_client(ws)
    await gw.broadcast({"type": "story_sandbox_token", "novel_id": "novel-A", "delta": "x"})
    assert ws.sent == [{"type": "story_sandbox_token", "novel_id": "novel-A", "delta": "x"}]


@pytest.mark.asyncio
async def test_log_shows_novel_display_name_but_wire_event_keeps_raw_id(monkeypatch, tmp_path):
    """server.log's [ws-send] line should read the novel's display name (multiple novels'
    sessions interleave in that one shared log file, so the raw id gave no readable way to
    tell them apart) -- but the event actually sent over the wire, matched against
    _focus_novel_id, must keep the raw id untouched."""
    import json

    from tests.conftest import seed_registry_novel

    novels_root = tmp_path / "novels"
    novels_root.mkdir()
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(novels_root))
    seed_registry_novel(novels_root, "novel-9", "九霄仙途")

    gw = Gateway()
    ws = _FakeWS()
    await gw.add_client(ws)
    cap: list[str] = []
    sink = logger.add(lambda m: cap.append(str(m)), level="INFO")
    try:
        await gw.broadcast({"type": "story_sandbox_done", "novel_id": "novel-9"})
    finally:
        logger.remove(sink)

    assert "九霄仙途" in "".join(cap)
    assert ws.sent == [{"type": "story_sandbox_done", "novel_id": "novel-9"}]


def test_get_focus_returns_none_before_any_set():
    gw = Gateway()
    assert gw.get_focus() is None


def test_get_focus_returns_last_set_value():
    gw = Gateway()
    gw.set_focus("novel-A")
    assert gw.get_focus() == "novel-A"
    gw.set_focus("novel-B")
    assert gw.get_focus() == "novel-B"
