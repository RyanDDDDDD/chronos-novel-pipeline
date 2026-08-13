"""Stage-level character timeline reading and writing - pure function, does not rely on langgraph."""
import context.character_timeline as tl
from utils.paths import use_novel


def test_append_and_get_current(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    with use_novel("test-novel"):
        tl.append_stage("女主丙", 6, 1, {"state": {"physiology": "p"}})
        tl.append_stage("女主丙", 6, 2, {"gender": "xeno"})
        cur = tl.get_current("女主丙")
        assert cur["chapter"] == 6 and cur["stage"] == 2
        assert cur["delta"] == {"gender": "xeno"}


def test_snapshots_sorted_by_chapter_stage(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    with use_novel("test-novel"):
        tl.append_stage("女主甲", 7, 1, {"a": 1})
        tl.append_stage("女主甲", 6, 2, {"a": 2})
        tl.append_stage("女主甲", 6, 1, {"a": 3})
        snaps = tl.load_timeline("女主甲")["snapshots"]
        coords = [(s["chapter"], s["stage"]) for s in snaps]
        assert coords == [(6, 1), (6, 2), (7, 1)]


def test_append_same_coord_replaces(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    with use_novel("test-novel"):
        tl.append_stage("女主乙", 6, 1, {"gender": "female"})
        tl.append_stage("女主乙", 6, 1, {"gender": "xeno"})
        snaps = tl.load_timeline("女主乙")["snapshots"]
        assert len(snaps) == 1 and snaps[0]["delta"] == {"gender": "xeno"}


def test_deltas_upto_inclusive(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    with use_novel("test-novel"):
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
        tl.append_stage("女主丙", 6, 1, {"x": 1})
        tl.append_stage("女主丙", 6, 2, {"x": 2})
        tl.append_stage("女主丙", 4, 1, {"x": 0})
        assert tl.latest_chapter("女主丙") == 6
