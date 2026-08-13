from engine.setup_chat import skeleton_seed as ss
from repo_test_helpers import save_archive, seed_plot, seed_world


def _setup(monkeypatch, tmp_path, plot, *, world=None, archives=None):
    """skeleton_seed reads plot/world/archive through repos. `archives` = {char_name:
    archive_dict}, written for the plot's first chapter number. Roster derivation scans
    `description` via entity_index.scan_characters -- stub it deterministically."""
    del tmp_path
    seed_plot(plot)
    if world is not None:
        seed_world(world)
    if archives:
        chapter = plot[0]["chapter"]
        for name, payload in archives.items():
            save_archive(name, chapter, payload)
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: [n for n in ("甲", "乙", "丙") if n in text],
    )


_PLOT = [{"chapter": 1, "title": "一", "stages": [
    {"stage_num": 1, "description": "甲乙对峙", "location": "书房"},
    {"stage_num": 2, "description": "丙登场"},
]}]


def test_seed_collects_roster_and_stages(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _PLOT)
    seed = ss.build_skeleton_seed(1)
    assert seed["chapter"] == 1
    assert seed["roster"] == ["甲", "乙", "丙"]
    assert [s["stage_num"] for s in seed["stages"]] == [1, 2]
    assert seed["stages"][0]["description"] == "甲乙对峙"
    assert seed["stages"][0]["location"] == "书房"
    assert seed["stages"][1]["location"] == ""  # stage2 未声明 location -> 空字符串兜底


def test_seed_missing_chapter(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _PLOT)
    seed = ss.build_skeleton_seed(9)
    assert seed["stages"] == [] and seed["roster"] == []


def test_seed_world_summary_present(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _PLOT, world={"background": "一个测试用的世界", "factions": []})
    seed = ss.build_skeleton_seed(1)
    assert "一个测试用的世界" in seed["world_summary"]


def test_seed_world_summary_empty_safe(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _PLOT)
    seed = ss.build_skeleton_seed(1)
    assert seed["world_summary"] == "（空）"


def test_seed_archive_summary_present(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _PLOT, archives={
        "甲": {"name": "甲", "role": "主角", "causal_anchors": {"stance": "dominant"}, "stages": {}},
    })
    seed = ss.build_skeleton_seed(1)
    assert "甲" in seed["archive_summary"]
    assert "dominant" in seed["archive_summary"]


def test_seed_archive_summary_empty_safe(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _PLOT)
    seed = ss.build_skeleton_seed(1)
    assert seed["archive_summary"] == "第 1 章角色档案："


def test_render_skeleton_seed_includes_all_four_blocks(monkeypatch, tmp_path):
    _setup(
        monkeypatch, tmp_path, _PLOT,
        world={"background": "测试世界观标记XYZ"},
        archives={"甲": {"name": "甲", "role": "主角", "causal_anchors": {}, "stages": {}}},
    )
    seed = ss.build_skeleton_seed(1)
    out = ss.render_skeleton_seed(seed)
    assert "测试世界观标记XYZ" in out
    assert "第 1 章角色档案" in out
    assert "甲乙对峙" in out
    assert "甲、乙、丙" in out
