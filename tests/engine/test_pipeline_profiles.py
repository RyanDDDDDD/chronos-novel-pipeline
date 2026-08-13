"""Pipeline file addition, deletion, modification, and migration (pure file operation, does not rely on LLM/langgraph)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "backend"))

import api.services.pipeline_profiles as pp


@pytest.fixture()
def store(monkeypatch, tmp_path):
    """Point the pipeline root directory to tmp to isolate the real config."""
    monkeypatch.setenv("CHRONOS_PIPELINES_DIR", str(tmp_path))
    return tmp_path


def _write_profile(root, pid, name, nodes=None):
    d = root / pid
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(
        json.dumps({"name": name, "nodes": nodes or {"start": {"type": "start"}}}),
        encoding="utf-8",
    )


def test_slugify_ascii_and_cjk_fallback(store):
    assert pp.slugify("Full Pipeline") == "full-pipeline"
    #Pure Chinese → Complete pipeline-<n> (n is determined by the number of existing directories)
    s = pp.slugify("全量")
    assert s.startswith("pipeline-") or s == "全量"  #See Step 3 for implementation: CJK walks through the details


def test_list_profiles_scans_disk_and_marks_active(store):
    _write_profile(store, "a", "甲档")
    _write_profile(store, "b", "乙档")
    (store / "active.json").write_text(json.dumps({"active": "b"}), encoding="utf-8")
    profiles = pp.list_profiles()
    by_id = {p["id"]: p for p in profiles}
    assert by_id["a"]["name"] == "甲档" and by_id["a"]["active"] is False
    assert by_id["b"]["active"] is True


def test_set_active_writes_pointer(store):
    _write_profile(store, "a", "甲档")
    pp.set_active("a")
    assert json.loads((store / "active.json").read_text(encoding="utf-8"))["active"] == "a"


def test_set_active_rejects_unknown(store):
    _write_profile(store, "a", "甲档")
    with pytest.raises(ValueError):
        pp.set_active("nope")


def test_create_blank_has_start_only(store):
    _write_profile(store, "a", "甲档")
    (store / "active.json").write_text(json.dumps({"active": "a"}), encoding="utf-8")
    new_id = pp.create_profile("空白档", clone=False)
    man = json.loads((store / new_id / "manifest.json").read_text(encoding="utf-8"))
    assert man["name"] == "空白档"
    assert list(man["nodes"].keys()) == ["start"]


def test_create_clone_is_independent(store):
    _write_profile(store, "a", "甲档", nodes={"start": {"type": "start"}, "n1": {"agent": "x"}})
    (store / "active.json").write_text(json.dumps({"active": "a"}), encoding="utf-8")
    new_id = pp.create_profile("甲档副本", clone=True)
    #Clone the original node
    man = json.loads((store / new_id / "manifest.json").read_text(encoding="utf-8"))
    assert "n1" in man["nodes"] and man["name"] == "甲档副本"
    #Changing the clone does not affect the original file
    (store / new_id / "manifest.json").write_text(json.dumps({"name": "改了", "nodes": {}}), encoding="utf-8")
    orig = json.loads((store / "a" / "manifest.json").read_text(encoding="utf-8"))
    assert orig["name"] == "甲档"


def test_rename_changes_name_not_dir(store):
    _write_profile(store, "a", "甲档")
    pp.rename_profile("a", "新名")
    assert (store / "a").is_dir()  #Directory id remains unchanged
    man = json.loads((store / "a" / "manifest.json").read_text(encoding="utf-8"))
    assert man["name"] == "新名"


def test_delete_removes_dir(store):
    _write_profile(store, "a", "甲档")
    _write_profile(store, "b", "乙档")
    (store / "active.json").write_text(json.dumps({"active": "a"}), encoding="utf-8")
    pp.delete_profile("b")
    assert not (store / "b").exists()


def test_delete_active_rejected(store):
    _write_profile(store, "a", "甲档")
    _write_profile(store, "b", "乙档")
    (store / "active.json").write_text(json.dumps({"active": "a"}), encoding="utf-8")
    with pytest.raises(ValueError):
        pp.delete_profile("a")


def test_delete_last_one_rejected(store):
    _write_profile(store, "a", "甲档")
    (store / "active.json").write_text(json.dumps({"active": "a"}), encoding="utf-8")
    with pytest.raises(ValueError):
        pp.delete_profile("a")


def test_migrate_creates_default_from_legacy(store, tmp_path, monkeypatch):
    #Simulate the old config: CONFIG_DIR points to another tmp and put the old manifest
    legacy_cfg = tmp_path / "legacy_config"
    legacy_cfg.mkdir()
    (legacy_cfg / "pipeline_manifest.json").write_text(
        json.dumps({"nodes": {"start": {"type": "start"}}}), encoding="utf-8"
    )
    monkeypatch.setattr(pp, "LEGACY_MANIFEST", str(legacy_cfg / "pipeline_manifest.json"))

    pp.ensure_initialized()
    dft = store / "default"
    assert dft.is_dir()
    man = json.loads((dft / "manifest.json").read_text(encoding="utf-8"))
    assert man["name"] == "默认" and "start" in man["nodes"]
    assert json.loads((store / "active.json").read_text(encoding="utf-8"))["active"] == "default"
    #Old files retained (rollback safe)
    assert (legacy_cfg / "pipeline_manifest.json").exists()


def test_ensure_initialized_idempotent(store):
    _write_profile(store, "a", "甲档")
    (store / "active.json").write_text(json.dumps({"active": "a"}), encoding="utf-8")
    pp.ensure_initialized()  #Existing file → Do not move
    assert not (store / "default").exists()


def test_ensure_initialized_fresh_creates_blank_default(store, monkeypatch):
    #No old files, no files → Create a blank default
    monkeypatch.setattr(pp, "LEGACY_MANIFEST", str(store / "nonexist.json"))
    pp.ensure_initialized()
    assert (store / "default" / "manifest.json").is_file()
    assert json.loads((store / "active.json").read_text(encoding="utf-8"))["active"] == "default"
