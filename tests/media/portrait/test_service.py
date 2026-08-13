from __future__ import annotations

import pytest


class _FakeRepo:
    def __init__(self, chars: list[dict]):
        self._chars = chars
        self.upserted: list[dict] = []

    def list_raw(self) -> list[dict]:
        return self._chars

    def upsert_character(self, char: dict) -> None:
        self.upserted.append(char)


def test_store_portrait_writes_versioned_file_and_upserts_path(monkeypatch, tmp_path):
    from media.portrait import service

    portrait_dir = tmp_path / "portraits"
    monkeypatch.setattr("utils.paths.portrait_dir", lambda: str(portrait_dir))
    monkeypatch.setattr(
        "utils.paths.portrait_path", lambda filename: str(portrait_dir / filename),
    )
    monkeypatch.setattr("time.time", lambda: 1723200000.0)

    repo = _FakeRepo([{"name": "甲", "race": "狐族"}])
    monkeypatch.setattr("repositories.get_lore_repo", lambda: repo)

    relative = service.store_portrait("甲", b"PNGDATA")

    assert relative == "甲-1723200000.png"
    written = portrait_dir / "甲-1723200000.png"
    assert written.read_bytes() == b"PNGDATA"
    assert repo.upserted == [{"name": "甲", "race": "狐族", "portrait_path": "甲-1723200000.png"}]


def test_store_portrait_deletes_previous_file(monkeypatch, tmp_path):
    from media.portrait import service

    portrait_dir = tmp_path / "portraits"
    portrait_dir.mkdir()
    old_file = portrait_dir / "甲-1000.png"
    old_file.write_bytes(b"OLD")

    monkeypatch.setattr("utils.paths.portrait_dir", lambda: str(portrait_dir))
    monkeypatch.setattr(
        "utils.paths.portrait_path", lambda filename: str(portrait_dir / filename),
    )
    monkeypatch.setattr("time.time", lambda: 2000.0)

    repo = _FakeRepo([{"name": "甲", "portrait_path": "甲-1000.png"}])
    monkeypatch.setattr("repositories.get_lore_repo", lambda: repo)

    service.store_portrait("甲", b"NEW")

    assert not old_file.exists()
    assert (portrait_dir / "甲-2000.png").read_bytes() == b"NEW"


def test_store_portrait_raises_when_character_missing(monkeypatch, tmp_path):
    from media.portrait import service

    monkeypatch.setattr("utils.paths.portrait_dir", lambda: str(tmp_path / "portraits"))
    monkeypatch.setattr("repositories.get_lore_repo", lambda: _FakeRepo([]))

    with pytest.raises(ValueError, match="角色不存在"):
        service.store_portrait("不存在", b"PNGDATA")
