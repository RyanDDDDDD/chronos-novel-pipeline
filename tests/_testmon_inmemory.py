"""In-memory backend for pytest-testmon's `.testmondata` SQLite store -- makes testmon hold
no open disk file handle for the duration of a test session (only briefly at session start/
finish), eliminating a real failure mode: a process that gets forcibly killed mid-session
(e.g. an external caller's timeout+kill, see docs/TECHNICAL_JOURNEY.md #30) can leave an
OS-level file lock on `.testmondata` that later runs block on indefinitely.

Deliberately does not reimplement any of testmon's own query/schema logic -- only swaps
where the bytes physically live, via SQLite's own :memory: mode and Connection.backup().
See docs/superpowers/specs/2026-08-12-testmon-inmemory-backend-design.md."""
from __future__ import annotations

import os
import sqlite3

import pytest
import testmon.db as _testmon_db

# datafile path -> most recent non-readonly in-memory connection for that path. Readonly
# connections are deliberately never registered here (see module docstring) -- they're
# independent point-in-time snapshots, not something that should ever be written back.
_LIVE_CONNECTIONS: dict[str, sqlite3.Connection] = {}


def _memory_backed_connect(datafile: str, readonly: bool = False) -> sqlite3.Connection:
    mem_conn = sqlite3.connect(":memory:")
    if os.path.exists(datafile):
        disk_conn = sqlite3.connect(
            f"file:{datafile}{'?mode=ro' if readonly else ''}", uri=True
        )
        try:
            disk_conn.backup(mem_conn)
        finally:
            disk_conn.close()
    elif not readonly:
        # Vanilla connect() creates the file when missing; testmon's schema migration path
        # calls os.remove(datafile) and expects that file to exist. Touch it briefly here
        # without keeping a handle open for the session.
        disk_conn = sqlite3.connect(datafile)
        disk_conn.close()
    if not readonly:
        _LIVE_CONNECTIONS[datafile] = mem_conn
    return mem_conn


def flush_to_disk() -> None:
    """Write every live (non-readonly) in-memory connection back to its real datafile path.
    Call once at session end (pytest_sessionfinish) -- never mid-session, that would
    reintroduce the disk IO this module exists to avoid."""
    for datafile, mem_conn in _LIVE_CONNECTIONS.items():
        disk_conn = sqlite3.connect(datafile)
        try:
            mem_conn.backup(disk_conn)
        finally:
            disk_conn.close()


def _fail_patch_not_in_effect(file_path: str) -> None:
    pytest.exit(
        "testmon in-memory patch did not take effect (testmon's live connection is "
        f"backed by a real file: {file_path!r}) -- testmon's internal DB construction "
        "path has likely changed; update tests/_testmon_inmemory.py",
        returncode=1,
    )


def verify_patch_took_effect(testmon_data) -> None:
    """Behavioral self-check: confirm testmon's actual live connection is really
    :memory:-backed, not silently falling back to a stale symbol after a testmon version
    upgrade changed its internals."""
    row = testmon_data.db.con.execute("PRAGMA database_list").fetchone()
    file_path = row[2] if row else None
    if file_path:
        _fail_patch_not_in_effect(file_path)


_testmon_db.connect = _memory_backed_connect
