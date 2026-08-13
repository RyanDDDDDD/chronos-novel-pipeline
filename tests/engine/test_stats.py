"""Tests for stats.record new signature."""
import json

from domain.stats import _load, record


def test_record_with_sub_category(tmp_path):
    p = tmp_path / "stats.json"
    record("体位", "2人", ["折叠夯桩", "侧入"], path=p)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["体位"]["2人"]["折叠夯桩"] == 1
    assert data["体位"]["2人"]["侧入"] == 1


def test_record_accumulates(tmp_path):
    p = tmp_path / "stats.json"
    record("插件", "肉体异化类", ["异化爆发"], path=p)
    record("插件", "肉体异化类", ["异化爆发"], path=p)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["插件"]["肉体异化类"]["异化爆发"] == 2


def test_record_empty_names_noop(tmp_path):
    p = tmp_path / "stats.json"
    record("体位", "2人", [], path=p)
    assert not p.exists()


def test_load_migrates_flat_format(tmp_path):
    """
Old flat {name: count} format migrates to {Unknown: {name: count}}."""
    p = tmp_path / "stats.json"
    p.write_text('{"体位": {"折叠夯桩": 3}}', encoding="utf-8")
    data = _load(p)
    assert data["体位"]["未知"]["折叠夯桩"] == 3
