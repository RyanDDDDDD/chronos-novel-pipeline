import os

from utils.paths import setup_chat_checkpoint_path, setup_chat_dir


def test_setup_chat_dir_under_novel(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "default")
    d = setup_chat_dir()
    assert d.endswith(os.path.join("setup_chat"))
    assert "default" in d


def test_checkpoint_path_under_setup_chat_dir():
    assert setup_chat_checkpoint_path().endswith(
        os.path.join("setup_chat", "checkpoint.sqlite")
    )
