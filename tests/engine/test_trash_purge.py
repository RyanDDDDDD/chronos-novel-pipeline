"""Trash purge: expired novels under novels/.trash/."""
from __future__ import annotations

import json
import os
import time

import pytest
from api.services import trash_purge as tp


@pytest.fixture
def novels_root(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    return tmp_path


def _trash_entry(
    novels_root,
    name: str,
    *,
    deleted_at: int | None = None,
    mtime: float | None = None,
) -> os.PathLike[str]:
    path = novels_root / ".trash" / name
    path.mkdir(parents=True)
    meta: dict = {}
    if deleted_at is not None:
        meta["deleted_at"] = deleted_at
    (path / "novel.json").write_text(json.dumps(meta), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_trash_entry_deleted_at_prefers_deleted_at(novels_root):
    now = int(time.time())
    path = _trash_entry(novels_root, "foo", deleted_at=now - 100)
    os.utime(path, (now, now))
    assert tp.trash_entry_deleted_at(str(path)) == float(now - 100)


def test_trash_entry_deleted_at_falls_back_to_mtime(novels_root):
    old = time.time() - 40 * 86400
    path = _trash_entry(novels_root, "legacy", mtime=old)
    assert tp.trash_entry_deleted_at(str(path)) == pytest.approx(old, abs=1)


def test_purge_expired_trash_keeps_recent(novels_root):
    now = int(time.time())
    _trash_entry(novels_root, "fresh", deleted_at=now - 86400)
    assert tp.purge_expired_trash(retention_days=30) == 0
    assert (novels_root / ".trash" / "fresh").is_dir()


def test_purge_expired_trash_removes_by_deleted_at(novels_root):
    now = int(time.time())
    _trash_entry(novels_root, "old", deleted_at=now - 31 * 86400)
    _trash_entry(novels_root, "keep", deleted_at=now - 86400)
    assert tp.purge_expired_trash(retention_days=30) == 1
    assert not (novels_root / ".trash" / "old").exists()
    assert (novels_root / ".trash" / "keep").is_dir()


def test_purge_expired_trash_uses_mtime_when_no_deleted_at(novels_root):
    old = time.time() - 31 * 86400
    _trash_entry(novels_root, "legacy", mtime=old)
    assert tp.purge_expired_trash(retention_days=30) == 1
    assert not (novels_root / ".trash" / "legacy").exists()


def test_purge_expired_trash_retention_zero_is_noop(novels_root):
    now = int(time.time())
    _trash_entry(novels_root, "old", deleted_at=now - 365 * 86400)
    assert tp.purge_expired_trash(retention_days=0) == 0
    assert (novels_root / ".trash" / "old").is_dir()


def test_purge_expired_trash_missing_trash_dir(novels_root):
    assert tp.purge_expired_trash(retention_days=30) == 0


def test_purge_expired_trash_continues_after_one_failure(novels_root, monkeypatch):
    now = int(time.time())
    _trash_entry(novels_root, "bad", deleted_at=now - 31 * 86400)
    _trash_entry(novels_root, "good", deleted_at=now - 31 * 86400)
    real_rmtree = tp.shutil.rmtree
    calls: list[str] = []

    def flaky_rmtree(path: str, *args, **kwargs):
        calls.append(os.path.basename(path))
        if os.path.basename(path) == "bad":
            raise OSError("locked")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(tp.shutil, "rmtree", flaky_rmtree)
    assert tp.purge_expired_trash(retention_days=30) == 1
    #os.listdir() order is filesystem-dependent (not creation order) -- only that both
    #entries were attempted exactly once matters, not which one came first.
    assert sorted(calls) == ["bad", "good"]
    assert not (novels_root / ".trash" / "good").exists()
    assert (novels_root / ".trash" / "bad").is_dir()


@pytest.mark.asyncio
async def test_run_trash_purge_respects_config_zero(novels_root, monkeypatch):
    now = int(time.time())
    _trash_entry(novels_root, "old", deleted_at=now - 365 * 86400)
    monkeypatch.setattr(tp, "trash_retention_days", lambda: 0)
    await tp.run_trash_purge()
    assert (novels_root / ".trash" / "old").is_dir()
