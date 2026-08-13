"""audit_agent_assets.py unit test"""
import json
import pathlib
import sys

import pytest

SCRIPTS_DIR = pathlib.Path(__file__).parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from audit_agent_assets import (
    _run_audit,
    _validate_asset,
)


@pytest.fixture
def asset_dir(tmp_path):
    return tmp_path


def test_validate_asset_passes_when_no_schema(asset_dir):
    """When there is no corresponding schema file, SKIP is returned (no error is reported)."""
    f = asset_dir / "vocab.json"
    f.write_text('{"a": 1}', encoding="utf-8")
    result = _validate_asset(f)
    assert result.status == "skip"


def test_validate_asset_passes_valid_json(asset_dir):
    """
PASS is returned when both JSON and schema are valid."""
    schema = {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object", "minProperties": 1}
    data = {"x": 1}
    schema_file = asset_dir / "vocab.schema.json"
    schema_file.write_text(json.dumps(schema), encoding="utf-8")
    data_file = asset_dir / "vocab.json"
    data_file.write_text(json.dumps(data), encoding="utf-8")
    result = _validate_asset(data_file)
    assert result.status == "pass"


def test_validate_asset_fails_invalid_json(asset_dir):
    """Returns FAIL if the JSON does not conform to the schema."""
    schema = {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object", "minProperties": 2}
    data = {}
    (asset_dir / "x.schema.json").write_text(json.dumps(schema), encoding="utf-8")
    (asset_dir / "x.json").write_text(json.dumps(data), encoding="utf-8")
    result = _validate_asset(asset_dir / "x.json")
    assert result.status == "fail"
    assert result.message


def test_validate_asset_fails_corrupt_json(asset_dir):
    """
Returns FAIL if the JSON file content is corrupted."""
    schema = {"type": "object"}
    (asset_dir / "y.schema.json").write_text(json.dumps(schema), encoding="utf-8")
    (asset_dir / "y.json").write_text("NOT JSON", encoding="utf-8")
    result = _validate_asset(asset_dir / "y.json")
    assert result.status == "fail"
    assert "parse" in result.message.lower() or "json" in result.message.lower()


def test_run_audit_real_agent_assets():
    """Perform an audit on the real hooks/packages/ directory, all assets with schema must pass."""
    from utils.paths import AGENTS_DIR

    agents_dir = pathlib.Path(AGENTS_DIR)
    results = _run_audit(agents_dir)
    failures = [r for r in results if r.status == "fail"]
    assert failures == [], f"资产校验失败: {[str(r) for r in failures]}"
