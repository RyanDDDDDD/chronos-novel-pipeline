"""Stage-level character timeline reading and writing - pure function, does not rely on langgraph."""
import context.character_timeline as tl
import pytest
from utils.paths import use_novel


def _seed_character(name: str) -> None:
    """Register `name` in lore_characters without wiping existing roster rows (FK-safe)."""
    import json

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
    """Ensure plot_chapters rows exist so timeline FK(chapter) inserts succeed."""
    from repositories.sqlite_store import get_connection
    from utils.paths import active_novel_id, novel_db_path

    conn = get_connection(novel_db_path(active_novel_id()))
    for c in chapters:
        conn.execute(
            "INSERT OR IGNORE INTO plot_chapters (chapter, data_json, seq) VALUES (?, '{}', ?)",
            (c, c),
        )
    conn.commit()


def test_append_and_get_current(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    with use_novel("test-novel"):
        _seed_character("女主丙")
        _ensure_plot_chapters(6)
        tl.append_stage("女主丙", 6, 1, {"state": {"physiology": "p"}})
        tl.append_stage("女主丙", 6, 2, {"gender": "xeno"})
        cur = tl.get_current("女主丙")
        assert cur["chapter"] == 6 and cur["stage"] == 2
        assert cur["delta"] == {"gender": "xeno"}


def test_snapshots_sorted_by_chapter_stage(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    with use_novel("test-novel"):
        _seed_character("女主甲")
        _ensure_plot_chapters(6, 7)
        tl.append_stage("女主甲", 7, 1, {"a": 1})
        tl.append_stage("女主甲", 6, 2, {"a": 2})
        tl.append_stage("女主甲", 6, 1, {"a": 3})
        snaps = tl.load_timeline("女主甲")["snapshots"]
        coords = [(s["chapter"], s["stage"]) for s in snaps]
        assert coords == [(6, 1), (6, 2), (7, 1)]


def test_append_same_coord_replaces(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    with use_novel("test-novel"):
        _seed_character("女主乙")
        _ensure_plot_chapters(6)
        tl.append_stage("女主乙", 6, 1, {"gender": "female"})
        tl.append_stage("女主乙", 6, 1, {"gender": "xeno"})
        snaps = tl.load_timeline("女主乙")["snapshots"]
        assert len(snaps) == 1 and snaps[0]["delta"] == {"gender": "xeno"}


def test_deltas_upto_inclusive(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    with use_novel("test-novel"):
        _seed_character("A")
        _ensure_plot_chapters(6, 7)
        tl.append_stage("A", 6, 1, {"x": 1})
        tl.append_stage("A", 6, 2, {"x": 2})
        tl.append_stage("A", 7, 1, {"x": 3})
        got = [d["delta"]["x"] for d in tl.deltas_upto("A", 6, 2)]
        assert got == [1, 2]
        assert [d["delta"]["x"] for d in tl.deltas_upto("A", 7, 1)] == [1, 2, 3]


def test_unknown_char_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    with use_novel("test-novel"):
        assert tl.get_current("查无此人") is None
        assert tl.deltas_upto("查无此人", 9, 9) == []
        assert tl.load_timeline("查无此人") == {"name": "查无此人", "snapshots": []}


def test_latest_chapter(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    with use_novel("test-novel"):
        assert tl.latest_chapter("新人") == 0
        _seed_character("女主丙")
        _ensure_plot_chapters(4, 6)
        tl.append_stage("女主丙", 6, 1, {"x": 1})
        tl.append_stage("女主丙", 6, 2, {"x": 2})
        tl.append_stage("女主丙", 4, 1, {"x": 0})
        assert tl.latest_chapter("女主丙") == 6


def test_append_stage_raises_for_unknown_character(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    with use_novel("test-novel"):
        with pytest.raises(ValueError, match="花名册"):
            tl.append_stage("查无此人", 1, 1, {"x": 1})
