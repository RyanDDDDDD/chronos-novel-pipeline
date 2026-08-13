"""agent.meta.json field reconciliation."""
import json
from pathlib import Path

from engine.validator.agent_package_check import _check_agent_meta_file


def _write_meta(tmp_path: Path, **fields) -> Path:
    pkg = tmp_path / "demo"
    pkg.mkdir()
    (pkg / "agent.meta.json").write_text(
        json.dumps({"package": "demo", "roles": ["demo"], **fields}, ensure_ascii=False),
        encoding="utf-8",
    )
    return pkg


def _expected(**fields) -> dict:
    return {"package": "demo", "roles": ["demo"], **fields}


def test_meta_both_false_ok(tmp_path):
    pkg = _write_meta(tmp_path)
    assert _check_agent_meta_file(pkg, _expected()) == []
