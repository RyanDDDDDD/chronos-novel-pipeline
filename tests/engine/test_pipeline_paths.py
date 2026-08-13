"""Pipeline path resolution: active pointer derives manifest/layout/prefs path."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "backend"))

import utils.paths as paths


def test_pipelines_dir_honors_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_PIPELINES_DIR", str(tmp_path))
    assert paths.pipelines_dir() == str(tmp_path)


def test_active_id_falls_back_to_default_when_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_PIPELINES_DIR", str(tmp_path))
    #active.json does not exist → default
    assert paths.active_pipeline_id() == "default"


def test_active_id_falls_back_on_corrupt(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_PIPELINES_DIR", str(tmp_path))
    (tmp_path / "active.json").write_text("{ not json", encoding="utf-8")
    assert paths.active_pipeline_id() == "default"


def test_active_id_reads_pointer(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_PIPELINES_DIR", str(tmp_path))
    (tmp_path / "active.json").write_text(json.dumps({"active": "full"}), encoding="utf-8")
    assert paths.active_pipeline_id() == "full"


def test_manifest_path_derives_from_active(monkeypatch, tmp_path):
    monkeypatch.delenv("CHRONOS_MANIFEST", raising=False)
    monkeypatch.setenv("CHRONOS_PIPELINES_DIR", str(tmp_path))
    (tmp_path / "active.json").write_text(json.dumps({"active": "full"}), encoding="utf-8")
    assert paths.manifest_path() == os.path.join(str(tmp_path), "full", "manifest.json")


def test_skill_prefs_path_under_active_novel_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "novel-x")
    assert paths.skill_prefs_path() == os.path.join(
        str(tmp_path), "novel-x", "author_loop_skill_prefs.json",
    )


def test_manifest_path_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_PIPELINES_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_MANIFEST", "/custom/m.json")
    assert paths.manifest_path() == "/custom/m.json"
