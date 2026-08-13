"""Textual-based live status dashboard for local startup.

Replaces raw, interleaved multi-process console output with one structured
view shared by every launch path (combined / --dev / --distributed /
--sequenced): a polled service table (name/port/health/PID) plus a
scrollable log tail panel.

Application logs still land in log files (loguru file sinks); the dashboard
incrementally tails those files (LogTailer) so the terminal stays readable
without losing visibility, and the log panel can be scrolled back with the
mouse wheel / PageUp-PageDown instead of only showing the last few lines.
"""
from __future__ import annotations

import os
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from textual.app import App, ComposeResult
from textual.widgets import DataTable, RichLog, Static

_STATE_STYLE = {"starting": "yellow", "healthy": "green", "down": "red"}


@dataclass
class ServiceStatus:
    """One dashboard row. `is_alive`/`is_healthy` are polled every tick --
    kept as callables (not booleans) so Dashboard never has to know how a
    given service checks itself (subprocess.poll() vs. thread.is_alive() vs.
    an HTTP probe)."""

    name: str
    port: int
    is_alive: Callable[[], bool]
    is_healthy: Callable[[], bool]
    pid: int | None = None
    state: str = "starting"


def _probe_http_health(port: int, path: str = "/api/health") -> bool:
    """One-shot health check, polled every `poll_interval` (0.5s) for the dashboard's
    lifetime. Explicitly requests `Connection: close` -- without it, urllib's default
    keep-alive request leaves the *server* (uvicorn) holding the socket open for its
    5s keep-alive timeout while this throwaway connection object is immediately
    garbage-collected client-side, so uvicorn's own timeout sweep later finds the peer
    already gone and logs a spurious "connection reset during transport cleanup"
    (WinError 10054 on Windows) for every single poll tick."""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", headers={"Connection": "close"}
        )
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            resp.read()
            return bool(resp.status == 200)
    except (urllib.error.URLError, OSError):
        return False


def _probe_tcp(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _tail_lines(path: str, max_lines: int) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            raw = f.readlines()
    except OSError:
        return []
    return [line.rstrip("\n\r") for line in raw[-max_lines:]]


def _log_prefix(path: str) -> str:
    base = os.path.basename(path)
    if base.startswith("server-"):
        return base.removeprefix("server-").removesuffix(".log")
    return ""


def _read_new_lines(path: str, offset: int) -> tuple[list[str], int]:
    """Read only the bytes appended to `path` since `offset`. Withholds an
    incomplete trailing line (no newline yet) so tailing never shows a line
    before the writer finishes it; the next poll picks it up complete."""
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read()
    except OSError:
        return [], offset
    if not data:
        return [], offset
    last_newline = data.rfind(b"\n")
    if last_newline == -1:
        return [], offset
    complete = data[: last_newline + 1]
    text = complete.decode("utf-8", errors="replace")
    return text.splitlines(), offset + len(complete)


def _initial_tail(path: str, max_lines: int) -> tuple[list[str], int]:
    """Seed a file's tailing offset at its current end-of-file, and return
    the last `max_lines` lines as the panel's starting content."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            end_offset = f.tell()
    except OSError:
        return [], 0
    return _tail_lines(path, max_lines), end_offset


class LogTailer:
    """Tracks per-file byte offsets so the log panel only reads newly
    appended content each poll instead of re-reading the whole file --
    log files like logs/setup_chat_tools.log grow into multiple MB during
    a long dev session."""

    def __init__(self, paths: list[str], initial_lines: int = 12) -> None:
        self._paths = paths
        self._initial_lines = initial_lines
        self._offsets: dict[str, int] = {}

    def initial_lines(self) -> list[str]:
        merged: list[str] = []
        for path in self._paths:
            lines, offset = _initial_tail(path, self._initial_lines)
            self._offsets[path] = offset
            merged.extend(self._prefixed(path, lines))
        return merged

    def poll(self) -> list[str]:
        merged: list[str] = []
        for path in self._paths:
            offset = self._offsets.get(path, 0)
            lines, new_offset = _read_new_lines(path, offset)
            self._offsets[path] = new_offset
            merged.extend(self._prefixed(path, lines))
        return merged

    def _prefixed(self, path: str, lines: list[str]) -> list[str]:
        if len(self._paths) <= 1:
            return lines
        prefix = _log_prefix(path)
        return [f"[{prefix}] {line}" if prefix else line for line in lines]


class LogPanel(RichLog):
    """RichLog that locks auto-scroll while the user is reading history.

    RichLog's own `auto_scroll` flag already suppresses the scroll-to-end
    that `write()` does on every new line, so all this needs to do is keep
    that flag in sync with the user's actual scroll position: dropped as
    soon as `scroll_y` moves off the bottom (mouse wheel, arrow keys,
    PageUp/Down all funnel through this one reactive watcher), restored the
    moment it's back at `max_scroll_y` -- which also covers the `End` key
    for free, since `action_scroll_end` just sets `scroll_y` to the max.
    """

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        self.auto_scroll = new_value >= self.max_scroll_y


_LOG_SEPARATOR_CHAR = "─"


def _log_separator(width: int) -> str:
    return f"[dim]{_LOG_SEPARATOR_CHAR * max(width, 1)}[/dim]"


class Dashboard(App[None]):
    """Textual-based startup dashboard: a polled service table plus a
    scrollable log tail. Class name and constructor signature are kept
    stable across the rich -> Textual rewrite so main.py's three mount
    points (combined / --dev+--distributed / --sequenced) don't change."""

    CSS = """
    #header { height: auto; border: round white; padding: 0 1; }
    #services { height: auto; }
    #log { height: 1fr; border: round white; }
    """

    def __init__(
        self,
        services: list[ServiceStatus],
        info_lines: list[str],
        still_running: Callable[[], bool],
        log_paths: list[str] | None = None,
        max_log_lines: int = 12,
        poll_interval: float = 0.5,
        healthy_recheck_every: int = 6,
    ) -> None:
        super().__init__()
        self.services = services
        self.info_lines = info_lines
        self.still_running = still_running
        self._has_logs = bool(log_paths)
        self._tailer = LogTailer(log_paths or [], initial_lines=max_log_lines)
        self.poll_interval = poll_interval
        # Once a service has reached "healthy", its process staying alive (is_alive(),
        # checked every tick below, no network I/O) is what actually catches a crash --
        # re-issuing the network-level is_healthy() probe every single 0.5s tick forever
        # just opens+closes a fresh connection twice a second for the dashboard's entire
        # lifetime with nothing to show for it, which is what produced the steady drip of
        # "connection reset during transport cleanup" noise this was fixed alongside
        # (Connection: close on _probe_http_health closes most of them cleanly, but this
        # cuts the probe volume itself by 6x once there's nothing left to discover).
        self.healthy_recheck_every = healthy_recheck_every
        self._tick = 0

    def compose(self) -> ComposeResult:
        yield Static("\n".join([*self.info_lines, "按 Ctrl+C 停止所有服务"]), id="header")
        yield DataTable(id="services")
        if self._has_logs:
            yield LogPanel(id="log", max_lines=2000, markup=True, wrap=True)

    def on_mount(self) -> None:
        table = self.query_one("#services", DataTable)
        table.add_columns("Service", "Port", "Status", "PID")
        self._refresh_table()
        if self._has_logs:
            self._write_log_lines(self._tailer.initial_lines())
        self.set_interval(self.poll_interval, self._poll)

    def _refresh_table(self) -> None:
        table = self.query_one("#services", DataTable)
        table.clear()
        for svc in self.services:
            style = _STATE_STYLE.get(svc.state, "white")
            table.add_row(
                svc.name,
                str(svc.port),
                f"[{style}]{svc.state}[/{style}]",
                str(svc.pid) if svc.pid is not None else "-",
            )

    def _write_log_lines(self, lines: list[str]) -> None:
        if not lines:
            return
        log = self.query_one("#log", LogPanel)
        separator = _log_separator(log.scrollable_content_region.width or log.min_width)
        for line in lines:
            log.write(line)
            log.write(separator)

    def _poll(self) -> None:
        if not self.still_running():
            for svc in self.services:
                if svc.state != "healthy":
                    svc.state = "down"
            self._refresh_table()
            self.exit()
            return
        self._tick += 1
        recheck_healthy = self._tick % self.healthy_recheck_every == 0
        for svc in self.services:
            if not svc.is_alive():
                svc.state = "down"
            elif svc.state != "healthy" or recheck_healthy:
                if svc.is_healthy():
                    svc.state = "healthy"
        self._refresh_table()
        if self._has_logs:
            self._write_log_lines(self._tailer.poll())
