"""Tests for tests/_testmon_inmemory.py -- the pytest-testmon in-memory backend patch.
See docs/superpowers/specs/2026-08-12-testmon-inmemory-backend-design.md."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import _testmon_inmemory as tm_mem  # noqa: E402


def _make_disk_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
    conn.execute("INSERT INTO t (val) VALUES ('hello')")
    conn.commit()
    conn.close()


def test_memory_backed_connect_loads_existing_disk_content(tmp_path):
    datafile = tmp_path / "data.db"
    _make_disk_db(datafile)

    mem_conn = tm_mem._memory_backed_connect(str(datafile))
    row = mem_conn.execute("SELECT val FROM t").fetchone()

    assert row == ("hello",)


def test_memory_backed_connect_missing_file_returns_empty_usable_connection(tmp_path):
    datafile = tmp_path / "does_not_exist.db"

    mem_conn = tm_mem._memory_backed_connect(str(datafile))
    mem_conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")  # must not raise

    assert mem_conn.execute("SELECT count(*) FROM t").fetchone() == (0,)


def test_memory_backed_connect_registers_write_connection_for_flush(tmp_path):
    datafile = tmp_path / "data.db"
    tm_mem._LIVE_CONNECTIONS.clear()

    tm_mem._memory_backed_connect(str(datafile))

    assert str(datafile) in tm_mem._LIVE_CONNECTIONS


def test_memory_backed_connect_readonly_not_registered_for_flush(tmp_path):
    datafile = tmp_path / "data.db"
    _make_disk_db(datafile)
    tm_mem._LIVE_CONNECTIONS.clear()

    tm_mem._memory_backed_connect(str(datafile), readonly=True)

    assert str(datafile) not in tm_mem._LIVE_CONNECTIONS


def test_flush_to_disk_writes_memory_content_back(tmp_path):
    datafile = tmp_path / "data.db"
    _make_disk_db(datafile)
    tm_mem._LIVE_CONNECTIONS.clear()

    mem_conn = tm_mem._memory_backed_connect(str(datafile))
    mem_conn.execute("INSERT INTO t (val) VALUES ('added in memory')")
    mem_conn.commit()

    tm_mem.flush_to_disk()

    reopened = sqlite3.connect(str(datafile))
    rows = {row[0] for row in reopened.execute("SELECT val FROM t")}
    reopened.close()
    assert rows == {"hello", "added in memory"}


def test_verify_patch_took_effect_passes_for_memory_connection():
    class FakeDb:
        con = sqlite3.connect(":memory:")

    class FakeTestmonData:
        db = FakeDb()

    calls = []
    original = tm_mem._fail_patch_not_in_effect
    tm_mem._fail_patch_not_in_effect = lambda file_path: calls.append(file_path)
    try:
        tm_mem.verify_patch_took_effect(FakeTestmonData())
    finally:
        tm_mem._fail_patch_not_in_effect = original

    assert calls == []


def test_verify_patch_took_effect_fails_for_real_file_connection(tmp_path):
    datafile = tmp_path / "data.db"
    _make_disk_db(datafile)

    class FakeDb:
        con = sqlite3.connect(str(datafile))

    class FakeTestmonData:
        db = FakeDb()

    calls = []
    original = tm_mem._fail_patch_not_in_effect
    tm_mem._fail_patch_not_in_effect = lambda file_path: calls.append(file_path)
    try:
        tm_mem.verify_patch_took_effect(FakeTestmonData())
    finally:
        tm_mem._fail_patch_not_in_effect = original

    assert len(calls) == 1
    assert str(datafile) in calls[0]
