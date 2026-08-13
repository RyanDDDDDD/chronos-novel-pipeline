from __future__ import annotations

import os
import sys

from utils import paths


def test_writable_root_defaults_to_dev_root(monkeypatch) -> None:
    monkeypatch.delenv("CHRONOS_ROOT", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    assert paths._writable_root() == paths._DEV_ROOT


def test_writable_root_prefers_chronos_root_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CHRONOS_ROOT", str(tmp_path))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert paths._writable_root() == str(tmp_path)


def test_writable_root_falls_back_to_exe_dir_when_frozen(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("CHRONOS_ROOT", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    fake_exe = tmp_path / "chronos" / "chronos.exe"
    monkeypatch.setattr(sys, "executable", str(fake_exe), raising=False)

    assert paths._writable_root() == str(fake_exe.parent)


def test_bundle_root_defaults_to_dev_root(monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    assert paths._bundle_root() == paths._DEV_ROOT


def test_bundle_root_uses_meipass_when_frozen(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert paths._bundle_root() == str(tmp_path)


def test_story_sandbox_checkpoint_path_under_chapters_dir():
    from utils.paths import story_sandbox_checkpoint_path

    assert story_sandbox_checkpoint_path().endswith(
        os.path.join("chapters", "_story_sandbox.sqlite")
    )


def test_story_sandbox_branches_path_under_chapters_dir():
    from utils.paths import story_sandbox_branches_path

    assert story_sandbox_branches_path().endswith(
        os.path.join("chapters", "_story_sandbox_branches.json")
    )


def test_prose_styles_dir_under_data_dir() -> None:
    from utils.paths import prose_styles_dir

    assert prose_styles_dir().endswith(os.path.join("data", "prose_styles"))

