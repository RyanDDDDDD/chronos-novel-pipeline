"""check_agent_valid — common to catalog and preflight."""
from pathlib import Path

from engine.validator.agent_package_check import check_agent_valid


def _mk(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    d = tmp_path / name
    d.mkdir()
    for fn, body in files.items():
        (d / fn).write_text(body, encoding="utf-8")
    return tmp_path


def test_valid_when_role_md_present(tmp_path):
    _mk(tmp_path, "foo", {"foo.md": "# foo"})
    assert check_agent_valid("foo", "foo", tmp_path, hook=None) == []


def test_missing_dir(tmp_path):
    errs = check_agent_valid("nope", "nope", tmp_path, hook=None)
    assert errs and "目录" in errs[0]


def test_missing_role_md(tmp_path):
    _mk(tmp_path, "foo", {})
    errs = check_agent_valid("foo", "foo", tmp_path, hook=None)
    assert errs and "foo.md" in errs[0]
