"""Novel path analysis: active novel determines the placement point of lore/plot/chapters; env can be overridden."""
import importlib
import os


def _reload_paths():
    import utils.paths as p
    return importlib.reload(p)


def test_paths_resolve_under_active_novel(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "bookA")
    p = _reload_paths()
    assert p.active_novel_id() == "bookA"
    assert p.active_novel_dir() == str(tmp_path / "bookA")
    assert p.lore_dir() == str(tmp_path / "bookA" / "lore")
    assert p.lore_library_path().endswith(
        os.path.join("bookA", "lore", "character_lore_library.json"))
    assert p.plot_library_path().endswith(
        os.path.join("bookA", "plot", "plot_library.json"))
    assert p.chapters_dir() == str(tmp_path / "bookA" / "chapters")
    assert p.get_chapter_dir(2) == str(tmp_path / "bookA" / "chapters" / "第2章")


def test_sandbox_event_log_path(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "bookA")
    p = _reload_paths()
    path = p.sandbox_event_log_path()
    assert path.endswith("sandbox_event_log.json")
    assert "lore" in path.replace("\\", "/")


def test_active_novel_id_reads_pointer(tmp_path, monkeypatch):
    from tests.conftest import seed_registry_novel

    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.delenv("CHRONOS_ACTIVE_NOVEL", raising=False)
    seed_registry_novel(tmp_path, "bookA", "甲")
    seed_registry_novel(tmp_path, "bookB", "乙", active=True)
    p = _reload_paths()
    assert p.active_novel_id() == "bookB"


def test_active_novel_id_fallback_default(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.delenv("CHRONOS_ACTIVE_NOVEL", raising=False)
    p = _reload_paths()
    assert p.active_novel_id() == "default"


def test_world_paths_resolve_under_active_novel(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "bookA")
    p = _reload_paths()
    assert p.world_dir() == str(tmp_path / "bookA" / "world")
    assert p.world_bible_path().endswith(os.path.join("bookA", "world", "world_bible.json"))


def test_novel_db_path_resolves_under_active_novel(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "bookA")
    p = _reload_paths()
    assert p.novel_db_path() == str(tmp_path / "bookA" / "chronos.sqlite3")
