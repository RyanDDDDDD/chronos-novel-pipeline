import os

from utils.paths import novel_db_path


def test_novel_db_path_under_active_novel(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "bookA")
    d = novel_db_path()
    assert d.endswith(os.path.join("bookA", "chronos.sqlite3"))
