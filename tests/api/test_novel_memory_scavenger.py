import pytest
import repositories as repo
from api.services import novel_memory_scavenger as nms
from api.services.scheduler import EventScheduler


class _FakeGateway:
    def __init__(self, focus: str | None = None) -> None:
        self._focus = focus

    def get_focus(self) -> str | None:
        return self._focus


class _FakeHub:
    def __init__(self, focus: str | None = None, busy: set[str] | None = None) -> None:
        self._gateway = _FakeGateway(focus)
        self._busy = busy or set()
        self.reset_setup_chat_calls: list[str | None] = []
        self.reset_story_sandbox_calls: list[str | None] = []

    def is_pipeline_busy(self, novel_id: str | None = None) -> bool:
        return novel_id in self._busy

    def is_setup_chat_busy(self, novel_id: str | None = None) -> bool:
        return False

    def is_story_sandbox_busy(self, novel_id: str | None = None) -> bool:
        return False

    async def reset_setup_chat(self, novel_id: str | None = None) -> None:
        self.reset_setup_chat_calls.append(novel_id)

    async def reset_story_sandbox(self, novel_id: str | None = None) -> None:
        self.reset_story_sandbox_calls.append(novel_id)


class _FakeStore:
    def close(self) -> None:
        pass


def _seed(nid: str, touched_at: float) -> None:
    repo._STORES[nid] = _FakeStore()
    repo._last_touched[nid] = touched_at


def _clear_stores() -> None:
    repo._STORES.clear()
    repo._last_touched.clear()


@pytest.mark.asyncio
async def test_scan_evicts_idle_novel_regardless_of_memory(monkeypatch):
    _clear_stores()
    _seed("novel-old", touched_at=0.0)
    monkeypatch.setattr(nms.time, "monotonic", lambda: nms.IDLE_EVICT_TTL_S + 1)
    monkeypatch.setattr(nms, "_current_rss_bytes", lambda: 0)
    hub = _FakeHub()
    await nms._scan(hub)
    assert "novel-old" not in repo.loaded_novel_ids()
    assert hub.reset_setup_chat_calls == ["novel-old"]
    assert hub.reset_story_sandbox_calls == ["novel-old"]


@pytest.mark.asyncio
async def test_scan_keeps_recently_touched_novel(monkeypatch):
    _clear_stores()
    _seed("novel-fresh", touched_at=100.0)
    monkeypatch.setattr(nms.time, "monotonic", lambda: 160.0)  # 1 min idle, under 15 min TTL
    monkeypatch.setattr(nms, "_current_rss_bytes", lambda: 0)
    hub = _FakeHub()
    await nms._scan(hub)
    assert "novel-fresh" in repo.loaded_novel_ids()
    assert hub.reset_setup_chat_calls == []


@pytest.mark.asyncio
async def test_scan_never_evicts_focused_novel(monkeypatch):
    _clear_stores()
    _seed("novel-focused", touched_at=0.0)
    monkeypatch.setattr(nms.time, "monotonic", lambda: nms.IDLE_EVICT_TTL_S + 1)
    monkeypatch.setattr(nms, "_current_rss_bytes", lambda: nms.MEMORY_HIGH_WATERMARK_BYTES + 1)
    hub = _FakeHub(focus="novel-focused")
    await nms._scan(hub)
    assert "novel-focused" in repo.loaded_novel_ids()
    assert hub.reset_setup_chat_calls == []


@pytest.mark.asyncio
async def test_scan_never_evicts_busy_novel(monkeypatch):
    _clear_stores()
    _seed("novel-busy", touched_at=0.0)
    monkeypatch.setattr(nms.time, "monotonic", lambda: nms.IDLE_EVICT_TTL_S + 1)
    monkeypatch.setattr(nms, "_current_rss_bytes", lambda: nms.MEMORY_HIGH_WATERMARK_BYTES + 1)
    hub = _FakeHub(busy={"novel-busy"})
    await nms._scan(hub)
    assert "novel-busy" in repo.loaded_novel_ids()
    assert hub.reset_setup_chat_calls == []


@pytest.mark.asyncio
async def test_scan_high_water_evicts_only_the_oldest_one(monkeypatch):
    _clear_stores()
    _seed("novel-a", touched_at=10.0)  # least recently used
    _seed("novel-b", touched_at=20.0)
    monkeypatch.setattr(nms.time, "monotonic", lambda: 25.0)  # both well under idle TTL
    monkeypatch.setattr(nms, "_current_rss_bytes", lambda: nms.MEMORY_HIGH_WATERMARK_BYTES + 1)
    hub = _FakeHub()
    await nms._scan(hub)
    assert "novel-a" not in repo.loaded_novel_ids()
    assert "novel-b" in repo.loaded_novel_ids()
    assert hub.reset_setup_chat_calls == ["novel-a"]


@pytest.mark.asyncio
async def test_scan_no_op_when_under_watermark_and_not_idle(monkeypatch):
    _clear_stores()
    _seed("novel-a", touched_at=10.0)
    monkeypatch.setattr(nms.time, "monotonic", lambda: 25.0)
    monkeypatch.setattr(nms, "_current_rss_bytes", lambda: 0)
    hub = _FakeHub()
    await nms._scan(hub)
    assert "novel-a" in repo.loaded_novel_ids()
    assert hub.reset_setup_chat_calls == []


@pytest.mark.asyncio
async def test_scan_empty_candidate_pool_is_noop(monkeypatch):
    _clear_stores()
    monkeypatch.setattr(nms, "_current_rss_bytes", lambda: nms.MEMORY_HIGH_WATERMARK_BYTES + 1)
    hub = _FakeHub()
    await nms._scan(hub)  # must not raise
    assert repo.loaded_novel_ids() == []


def test_current_rss_bytes_returns_none_on_psutil_error(monkeypatch):
    class _BoomProcess:
        def memory_info(self):
            raise nms.psutil.Error("boom")

    # patch the name as looked up inside nms (nms.psutil is the same shared module
    # object psutil.Process would otherwise resolve to -- monkeypatch restores this
    # automatically at teardown, unlike a manual assign/restore).
    monkeypatch.setattr(nms.psutil, "Process", lambda: _BoomProcess())
    assert nms._current_rss_bytes() is None


@pytest.mark.asyncio
async def test_register_novel_memory_scavenger_schedules_periodic():
    s = EventScheduler()
    hub = _FakeHub()
    nms.register_novel_memory_scavenger(s, hub)
    s.start()
    try:
        assert any(ev.name == "novel_memory_scavenger" for ev in s._heap)
    finally:
        await s.stop()
