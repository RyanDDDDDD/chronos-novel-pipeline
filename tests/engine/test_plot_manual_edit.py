"""patch_plot_chapter_title: manual-edit chapter-title rename via plot repo."""
from engine.setup.plot.manual_edit import patch_plot_chapter_title
from repo_test_helpers import seed_plot


def test_renames_existing_chapter():
    seed_plot([{"chapter": 1, "title": "旧标题", "stages": []}])

    ok, msg = patch_plot_chapter_title(1, "新标题")
    assert ok is True and "1" in msg
    from repositories import get_plot_repo
    saved = get_plot_repo().list_raw()
    assert saved[0]["title"] == "新标题"
    assert saved[0]["stages"] == []


def test_rejects_missing_chapter():
    seed_plot([{"chapter": 1, "title": "x", "stages": []}])

    ok, msg = patch_plot_chapter_title(9, "新标题")
    assert ok is False and "不存在" in msg
