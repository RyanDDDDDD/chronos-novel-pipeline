"""Tests for the Textual-based startup dashboard."""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from dev_console import (
    Dashboard,
    LogPanel,
    LogTailer,
    ServiceStatus,
    _initial_tail,
    _log_separator,
    _probe_http_health,
    _read_new_lines,
)
from textual.widgets import DataTable


def test_probe_http_health_sends_connection_close() -> None:
    """Without `Connection: close`, uvicorn parks the socket in its keep-alive pool
    instead of closing it once this one-shot health check reads its response --
    see _probe_http_health's docstring for how that produced spurious
    connection-reset log noise on every 0.5s dashboard poll tick."""
    seen_headers: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler's naming convention
            seen_headers["connection"] = self.headers.get("Connection", "")
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args: object) -> None:  # noqa: ANN401 -- silence test server's stderr logging
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    try:
        assert _probe_http_health(server.server_port, path="/") is True
    finally:
        thread.join(timeout=2.0)
        server.server_close()

    assert seen_headers["connection"] == "close"


def test_read_new_lines_returns_only_bytes_after_offset(tmp_path) -> None:
    log_path = tmp_path / "server.log"
    log_path.write_bytes(b"line1\n")
    lines, offset = _read_new_lines(str(log_path), 0)
    assert lines == ["line1"]
    assert offset == len(b"line1\n")

    log_path.write_bytes(b"line1\nline2\n")
    lines2, offset2 = _read_new_lines(str(log_path), offset)
    assert lines2 == ["line2"]
    assert offset2 == len(b"line1\nline2\n")


def test_read_new_lines_withholds_incomplete_trailing_line(tmp_path) -> None:
    log_path = tmp_path / "server.log"
    log_path.write_bytes(b"line1\npartial")
    lines, offset = _read_new_lines(str(log_path), 0)
    assert lines == ["line1"]
    assert offset == len(b"line1\n")  # "partial" 未换行，本轮不读出

    log_path.write_bytes(b"line1\npartial line\n")
    lines2, offset2 = _read_new_lines(str(log_path), offset)
    assert lines2 == ["partial line"]


def test_read_new_lines_missing_file_returns_empty_and_same_offset() -> None:
    lines, offset = _read_new_lines("/nonexistent/path/server.log", 5)
    assert lines == []
    assert offset == 5


def test_initial_tail_seeds_offset_at_current_end(tmp_path) -> None:
    log_path = tmp_path / "server.log"
    log_path.write_text("line1\nline2\nline3\n", encoding="utf-8")
    lines, offset = _initial_tail(str(log_path), max_lines=2)
    assert lines == ["line2", "line3"]
    assert offset == log_path.stat().st_size


def test_log_tailer_initial_lines_single_file_no_prefix(tmp_path) -> None:
    log_path = tmp_path / "server.log"
    log_path.write_text("line1\nline2\n", encoding="utf-8")
    tailer = LogTailer([str(log_path)])
    assert tailer.initial_lines() == ["line1", "line2"]


def test_log_tailer_initial_lines_prefixes_multi_file(tmp_path) -> None:
    gateway = tmp_path / "server-gateway.log"
    engine = tmp_path / "server-engine.log"
    gateway.write_text("gw line\n", encoding="utf-8")
    engine.write_text("en line\n", encoding="utf-8")
    tailer = LogTailer([str(gateway), str(engine)])
    lines = tailer.initial_lines()
    assert lines == ["[gateway] gw line", "[engine] en line"]


def test_log_tailer_poll_returns_only_newly_appended_lines(tmp_path) -> None:
    log_path = tmp_path / "server.log"
    log_path.write_text("line1\nline2\n", encoding="utf-8")
    tailer = LogTailer([str(log_path)])
    assert tailer.initial_lines() == ["line1", "line2"]

    assert tailer.poll() == []  # 还没新内容

    log_path.write_text("line1\nline2\nline3\n", encoding="utf-8")
    assert tailer.poll() == ["line3"]


async def test_dashboard_populates_service_table_on_mount() -> None:
    svc = ServiceStatus("gateway", 8775, is_alive=lambda: True, is_healthy=lambda: True, pid=123)
    svc.state = "healthy"
    app = Dashboard([svc], ["gateway http://localhost:8775"], still_running=lambda: True)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one("#services", DataTable)
        row = table.get_row_at(0)
        assert row[0] == "gateway"
        assert row[1] == "8775"
        assert "healthy" in row[2]
        assert row[3] == "123"


async def test_dashboard_poll_marks_service_healthy() -> None:
    healthy = {"flag": False}
    svc = ServiceStatus("chronos", 8775, is_alive=lambda: True, is_healthy=lambda: healthy["flag"])
    app = Dashboard([svc], ["info"], still_running=lambda: True)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert svc.state == "starting"
        healthy["flag"] = True
        app._poll()
        await pilot.pause()
        assert svc.state == "healthy"
        table = app.query_one("#services", DataTable)
        assert "healthy" in table.get_row_at(0)[2]


async def test_dashboard_backs_off_health_probe_once_healthy() -> None:
    """Once a service is confirmed healthy, is_alive() (process poll, no network I/O)
    still runs every tick, but the network-level is_healthy() probe should only be
    re-issued every `healthy_recheck_every` ticks -- re-probing every 0.5s tick forever
    is what produced a steady stream of spurious connection-reset log noise (see
    dev_console.py's Dashboard.__init__ docstring comment)."""
    calls = {"n": 0}

    def is_healthy() -> bool:
        calls["n"] += 1
        return True

    svc = ServiceStatus("chronos", 8775, is_alive=lambda: True, is_healthy=is_healthy)
    app = Dashboard([svc], ["info"], still_running=lambda: True, healthy_recheck_every=3)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._poll()  # tick 1: not yet healthy -> probes, becomes healthy
        await pilot.pause()
        assert svc.state == "healthy"
        assert calls["n"] == 1

        app._poll()  # tick 2: already healthy, not a recheck tick -> skipped
        await pilot.pause()
        assert calls["n"] == 1

        app._poll()  # tick 3: already healthy, recheck tick (3 % 3 == 0) -> probes again
        await pilot.pause()
        assert calls["n"] == 2


async def test_dashboard_poll_exits_when_still_running_false() -> None:
    running = {"flag": True}
    svc = ServiceStatus("chronos", 8775, is_alive=lambda: True, is_healthy=lambda: True)
    app = Dashboard([svc], ["info"], still_running=lambda: running["flag"])
    async with app.run_test() as pilot:
        await pilot.pause()
        running["flag"] = False
        app._poll()
        await pilot.pause()
        assert svc.state == "down"


async def test_dashboard_writes_initial_log_tail_on_mount(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "server.log"
    log_path.write_text("line1\nline2\n", encoding="utf-8")
    written: list[list[str]] = []
    monkeypatch.setattr(Dashboard, "_write_log_lines", lambda self, lines: written.append(lines))
    svc = ServiceStatus("chronos", 8775, is_alive=lambda: True, is_healthy=lambda: True)
    app = Dashboard([svc], ["info"], still_running=lambda: True, log_paths=[str(log_path)])
    async with app.run_test() as pilot:
        await pilot.pause()
    assert written == [["line1", "line2"]]


async def test_dashboard_poll_writes_new_log_lines(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "server.log"
    log_path.write_text("line1\n", encoding="utf-8")
    written: list[list[str]] = []
    monkeypatch.setattr(Dashboard, "_write_log_lines", lambda self, lines: written.append(lines))
    svc = ServiceStatus("chronos", 8775, is_alive=lambda: True, is_healthy=lambda: True)
    app = Dashboard([svc], ["info"], still_running=lambda: True, log_paths=[str(log_path)])
    async with app.run_test() as pilot:
        await pilot.pause()
        log_path.write_text("line1\nline2\n", encoding="utf-8")
        app._poll()
        await pilot.pause()
    assert written == [["line1"], ["line2"]]


async def test_dashboard_no_log_panel_when_no_log_paths() -> None:
    svc = ServiceStatus("chronos", 8775, is_alive=lambda: True, is_healthy=lambda: True)
    app = Dashboard([svc], ["info"], still_running=lambda: True)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert not app.query("#log").nodes


def test_log_separator_repeats_dash_char_to_width() -> None:
    assert _log_separator(5) == "[dim]─────[/dim]"


def test_log_separator_never_empty() -> None:
    assert _log_separator(0) == "[dim]─[/dim]"


async def test_log_panel_locks_auto_scroll_when_user_scrolls_away_from_bottom(tmp_path) -> None:
    log_path = tmp_path / "server.log"
    log_path.write_text("\n".join(f"line{i}" for i in range(50)) + "\n", encoding="utf-8")
    svc = ServiceStatus("chronos", 8775, is_alive=lambda: True, is_healthy=lambda: True)
    app = Dashboard(
        [svc], ["info"], still_running=lambda: True, log_paths=[str(log_path)], max_log_lines=50
    )
    async with app.run_test() as pilot:
        # RichLog's own auto-scroll-to-end on write is itself deferred via
        # call_after_refresh, so it takes a second pause to settle at the
        # bottom before we can meaningfully scroll away from it.
        await pilot.pause()
        await pilot.pause()
        log = app.query_one("#log", LogPanel)
        assert log.auto_scroll is True

        log.scroll_home(animate=False)
        await pilot.pause()
        assert log.auto_scroll is False, "scrolling away from the bottom should drop auto-scroll"

        log.scroll_end(animate=False)
        await pilot.pause()
        assert log.auto_scroll is True, "returning to the bottom should resume auto-scroll"


async def test_log_panel_resumed_auto_scroll_does_not_yank_reading_position(tmp_path) -> None:
    """A write while the user is mid-history must not move scroll_y --
    only auto_scroll's own scroll_end() call (i.e. once resumed) may."""
    log_path = tmp_path / "server.log"
    log_path.write_text("\n".join(f"line{i}" for i in range(50)) + "\n", encoding="utf-8")
    svc = ServiceStatus("chronos", 8775, is_alive=lambda: True, is_healthy=lambda: True)
    app = Dashboard(
        [svc], ["info"], still_running=lambda: True, log_paths=[str(log_path)], max_log_lines=50
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        log = app.query_one("#log", LogPanel)
        log.scroll_home(animate=False)
        await pilot.pause()
        assert log.auto_scroll is False
        paused_scroll_y = log.scroll_y

        log_path.write_text(
            "\n".join(f"line{i}" for i in range(50)) + "\nnew line\n", encoding="utf-8"
        )
        app._poll()
        await pilot.pause()
        await pilot.pause()

        assert log.scroll_y == paused_scroll_y
        assert log.auto_scroll is False
