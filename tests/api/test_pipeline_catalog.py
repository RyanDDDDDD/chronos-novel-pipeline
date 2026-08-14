"""list_chapters() must read the plot library from SQLite, not the retired
plot_library.json path -- see api.services.pipeline_catalog.list_chapters."""
from __future__ import annotations

from api.services.pipeline_catalog import list_chapters
from repo_test_helpers import seed_plot


def test_list_chapters_returns_all_chapters_from_sqlite_plot_repo():
    seed_plot([
        {"chapter": 1, "title": "第一章"},
        {"chapter": 2, "title": "第二章"},
        {"chapter": 3, "title": "第三章"},
    ])

    assert list_chapters() == [
        {"chapter": 1, "title": "第一章"},
        {"chapter": 2, "title": "第二章"},
        {"chapter": 3, "title": "第三章"},
    ]


def test_list_chapters_empty_plot_falls_back_to_chapter_one():
    import repositories
    repositories.init_repositories()

    assert list_chapters() == [{"chapter": 1, "title": None}]
