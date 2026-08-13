"""Engine built-in shared library path resolution: CHRONOS_LIB_DIR overrides /default data/lib."""
import importlib
import os


def _reload_paths():
    import utils.paths as p
    return importlib.reload(p)


def test_lib_paths_under_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_LIB_DIR", str(tmp_path))
    p = _reload_paths()
    assert p.lib_dir() == str(tmp_path)


def test_lib_dir_default_is_data_lib(monkeypatch):
    monkeypatch.delenv("CHRONOS_LIB_DIR", raising=False)
    p = _reload_paths()
    assert p.lib_dir().endswith(os.path.join("data", "lib"))


def test_portrait_dir_and_path(monkeypatch, tmp_path):
    from utils import paths

    monkeypatch.setattr(paths, "active_novel_dir", lambda: str(tmp_path / "novel-A"))

    assert paths.portrait_dir() == str(tmp_path / "novel-A" / "assets" / "portraits")
    assert paths.portrait_path("甲-123.png") == str(
        tmp_path / "novel-A" / "assets" / "portraits" / "甲-123.png"
    )
