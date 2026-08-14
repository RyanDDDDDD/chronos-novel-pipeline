"""timeline truncation + list enumeration primitive."""
from __future__ import annotations

import json

from context import character_timeline as ct
from utils.paths import use_novel


def _seed_character(name: str) -> None:
    """Register `name` in lore_characters without wiping existing roster rows (FK-safe)."""
    from repositories.sqlite_store import get_connection
    from utils.paths import active_novel_id, novel_db_path

    conn = get_connection(novel_db_path(active_novel_id()))
    if conn.execute("SELECT id FROM lore_characters WHERE name = ?", (name,)).fetchone():
        return
    seq = conn.execute("SELECT COALESCE(MAX(seq), -1) + 1 FROM lore_characters").fetchone()[0]
    conn.execute(
        "INSERT INTO lore_characters (name, data_json, seq) VALUES (?, ?, ?)",
        (name, json.dumps({"name": name}, ensure_ascii=False), seq),
    )
    conn.commit()


def _ensure_plot_chapters(*chapters: int) -> None:
    from repositories.sqlite_store import get_connection
    from utils.paths import active_novel_id, novel_db_path

    conn = get_connection(novel_db_path(active_novel_id()))
    for c in chapters:
        conn.execute(
            "INSERT OR IGNORE INTO plot_chapters (chapter, data_json, seq) VALUES (?, '{}', ?)",
            (c, c),
        )
    conn.commit()


def _seed(tmp_path, monkeypatch, name, snaps):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    with use_novel("test-novel"):
        _seed_character(name)
        _ensure_plot_chapters(*(s["chapter"] for s in snaps))
        for s in snaps:
            ct.append_stage(name, s["chapter"], s["stage"], s.get("delta", {}))


def test_truncate_from_drops_chapter_ge_n(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, "角色A", [
        {"chapter": 1, "stage": 1, "delta": {}},
        {"chapter": 2, "stage": 1, "delta": {}},
        {"chapter": 2, "stage": 2, "delta": {}},
        {"chapter": 3, "stage": 1, "delta": {}},
    ])
    with use_novel("test-novel"):
        removed = ct.truncate_from("角色A", 2)
        assert removed == 3
        left = ct.load_timeline("角色A")["snapshots"]
        assert [(s["chapter"], s["stage"]) for s in left] == [(1, 1)]


def test_truncate_from_noop_when_nothing_ge_n(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, "角色A", [{"chapter": 1, "stage": 1, "delta": {}}])
    with use_novel("test-novel"):
        assert ct.truncate_from("角色A", 5) == 0
        assert len(ct.load_timeline("角色A")["snapshots"]) == 1


def test_truncate_from_removes_all_rows_when_everything_is_cleared(tmp_path, monkeypatch):
    """from_chapter=1 (delete-everything) must leave no timeline_snapshots rows for this name."""
    _seed(tmp_path, monkeypatch, "角色A", [
        {"chapter": 1, "stage": 1, "delta": {}},
        {"chapter": 2, "stage": 1, "delta": {}},
    ])
    with use_novel("test-novel"):
        removed = ct.truncate_from("角色A", 1)
        assert removed == 2
        assert ct.list_timeline_names() == []
        assert ct.load_timeline("角色A")["snapshots"] == []


def test_truncate_from_keeps_remaining_chapters(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, "角色A", [
        {"chapter": 1, "stage": 1, "delta": {}},
        {"chapter": 2, "stage": 1, "delta": {}},
    ])
    with use_novel("test-novel"):
        removed = ct.truncate_from("角色A", 2)
        assert removed == 1
        assert [s["chapter"] for s in ct.load_timeline("角色A")["snapshots"]] == [1]


def test_truncate_from_empty_timeline(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    with use_novel("test-novel"):
        assert ct.truncate_from("不存在", 1) == 0


def test_list_timeline_names(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, "角色A", [{"chapter": 1, "stage": 1, "delta": {}}])
    _seed(tmp_path, monkeypatch, "角色B", [{"chapter": 1, "stage": 1, "delta": {}}])
    with use_novel("test-novel"):
        assert sorted(ct.list_timeline_names()) == ["角色A", "角色B"]


def test_list_timeline_names_empty_when_no_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    with use_novel("test-novel"):
        assert ct.list_timeline_names() == []
