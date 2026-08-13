
import pytest
from engine.setup_chat import construction_plan as cp
from repo_test_helpers import init_store, seed_lore, seed_plot, seed_world


@pytest.fixture(autouse=True)
def _reset_world_pipeline_active_target():
    import engine.setup_chat.world_pipeline as wp

    wp._ACTIVE_TARGET = None
    wp._ACTIVE_TIMELINE_TARGET = None
    yield
    wp._ACTIVE_TARGET = None
    wp._ACTIVE_TIMELINE_TARGET = None


def _patch_paths(monkeypatch, tmp_path):
    """Rebuild the sqlite repo for derive_task_status tests."""
    del monkeypatch, tmp_path
    init_store()


def test_derive_world_done_when_bible_exists(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    assert cp.derive_task_status({"kind": "world"}) == "pending"
    item = {"name": "条目", "desc": "这是一个足够长的描述内容用于通过校验"}
    bible = {
        "tone": "苍凉史诗的基调描述",
        "background": "剑客传奇的核心背景与时代设定",
        "factions": [item],
        "geography": [item],
        "races": [item],
        "power_system": [item],
        "core_themes": [item],
    }
    seed_world(bible)
    assert cp.derive_task_status({"kind": "world"}) == "done"


def test_derive_character_done_when_in_cast(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    seed_lore([{"name": "爱丽丝"}])
    assert cp.derive_task_status({"kind": "character", "params": {"given_name": "爱丽丝"}}) == "done"
    assert cp.derive_task_status({"kind": "character", "params": {"given_name": "柚子"}}) == "pending"


def test_derive_plot_chapter_done_when_chapter_exists(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    seed_plot([{"chapter": 1}])
    assert cp.derive_task_status({"kind": "plot_chapter", "params": {"chapter": 1}}) == "done"
    assert cp.derive_task_status({"kind": "plot_chapter", "params": {"chapter": 2}}) == "pending"


def test_derive_timeline_done_when_archive_exists(monkeypatch, tmp_path):
    from repo_test_helpers import save_archive

    _patch_paths(monkeypatch, tmp_path)
    assert cp.derive_task_status({"kind": "timeline", "params": {"chapter": 1}}) == "pending"
    save_archive("爱丽丝", 1, {"name": "爱丽丝"})
    assert cp.derive_task_status({"kind": "timeline", "params": {"chapter": 1}}) == "done"


def test_derive_character_aggregate_no_given_name(monkeypatch, tmp_path):
    """
Aggregate character tasks (without given_name): cast is either empty or done."""
    _patch_paths(monkeypatch, tmp_path)
    assert cp.derive_task_status({"kind": "character", "params": {}}) == "pending"
    seed_lore([{"name": "甲"}])
    assert cp.derive_task_status({"kind": "character", "params": {}}) == "done"


def test_derive_character_given_names_list(monkeypatch, tmp_path):
    """Given a list of given_names: done only if all are present."""
    _patch_paths(monkeypatch, tmp_path)
    seed_lore([{"name": "甲"}, {"name": "乙"}])
    assert cp.derive_task_status({"kind": "character", "params": {"given_names": ["甲", "乙"]}}) == "done"
    assert cp.derive_task_status({"kind": "character", "params": {"given_names": ["甲", "丙"]}}) == "pending"


def test_derive_timeline_aggregate_no_chapter(monkeypatch, tmp_path):
    """
Aggregation timeline task (no chapter): All plot chapters have files and are done."""
    _patch_paths(monkeypatch, tmp_path)
    seed_plot([{"chapter": 1}, {"chapter": 2}])
    assert cp.derive_task_status({"kind": "timeline", "params": {}}) == "pending"  #No files
    from repo_test_helpers import save_archive

    for ch in (1, 2):
        save_archive("甲", ch, {"name": "甲"})
    assert cp.derive_task_status({"kind": "timeline", "params": {}}) == "done"


def test_derive_timeline_aggregate_partial_pending(monkeypatch, tmp_path):
    """Aggregation timeline: Only some chapters have files → still pending."""
    _patch_paths(monkeypatch, tmp_path)
    seed_plot([{"chapter": 1}, {"chapter": 2}])
    from repo_test_helpers import save_archive

    save_archive("甲", 1, {"name": "甲"})
    assert cp.derive_task_status({"kind": "timeline", "params": {}}) == "pending"


def _plot_with_beats(monkeypatch, stages):
    """Install a fake plot repo whose chapter 2 has the given stages."""
    import engine.setup_chat.construction_plan as cp_mod

    class _Repo:
        def list_raw(self):
            return [{"chapter": 2, "stages": stages}]
    monkeypatch.setattr("repositories.get_plot_repo", lambda: _Repo())
    return cp_mod


def test_skeleton_stage_done_when_beats_nonempty(monkeypatch):
    cp_mod = _plot_with_beats(monkeypatch, [
        {"stage_num": 1, "beats": [{"text": "拍零"}]},
        {"stage_num": 2},
    ])
    done = {"kind": "skeleton_stage", "params": {"chapter": 2, "stage_num": 1}}
    pending = {"kind": "skeleton_stage", "params": {"chapter": 2, "stage_num": 2}}
    assert cp_mod.derive_task_status(done) == "done"
    assert cp_mod.derive_task_status(pending) == "pending"
