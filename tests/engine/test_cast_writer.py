"""cast dropper test (written through LoreRepository)."""
from engine.setup.cast.cast_writer import write_cast
from repo_test_helpers import init_store, lore_raw


def test_write_cast_creates_library(tmp_path, monkeypatch):
    del tmp_path, monkeypatch
    init_store()
    roster = [
        {"name": "甲", "causal_anchors": {"stance": "submissive"}},
        {"name": "乙", "causal_anchors": {"stance": "dominant"}},
    ]
    write_cast(roster)
    got_lib = lore_raw()
    assert [c["name"] for c in got_lib] == ["甲", "乙"]


def test_write_cast_overwrites(tmp_path, monkeypatch):
    del tmp_path, monkeypatch
    init_store()
    from repo_test_helpers import seed_lore

    seed_lore([{"name": "旧", "causal_anchors": {"stance": "dominant"}}])
    write_cast([{"name": "新", "causal_anchors": {"stance": "dominant"}}])
    got = lore_raw()
    assert [c["name"] for c in got] == ["新"]


def test_write_cast_non_ascii_not_escaped(tmp_path, monkeypatch):
    del tmp_path, monkeypatch
    init_store()
    write_cast([{"name": "角色甲", "causal_anchors": {"stance": "dominant"}}])
    names = [c["name"] for c in lore_raw()]
    assert "角色甲" in names
