"""Shared fixtures for all engine tests."""
import os
import random

import llm.prompt_logger as _pl
import pytest
import utils.config as _config

#Freeze manifest: CI/new clone is used for package verification and other tests when there is no config/pipelines/(gitignore).
_FIXTURE_MANIFEST = os.path.join(os.path.dirname(__file__), "fixtures", "test_pipeline_manifest.json")


def _live_manifest_path() -> str:
    """
Default live manifest path (does not read CHRONOS_MANIFEST override)."""
    from utils.paths import active_pipeline_id, pipelines_dir

    return os.path.join(pipelines_dir(), active_pipeline_id(), "manifest.json")


@pytest.fixture(autouse=True)
def _deterministic_random():
    """Fixed the random seed to ensure that tests that rely on random (such as the random selection of pose's preset) are reproducible.

    topology_engine._match_group_preset shuffles the preset library with seedless random.shuffle to provide
    Diversity; fixed seeds in testing avoid flaky caused by random fluctuations in option shapes/bindings."""
    random.seed(1)


@pytest.fixture(autouse=True)
def redirect_prompt_logger(tmp_path, monkeypatch):
    """
Redirect all test PromptLogger logs to tmp_path to avoid polluting the logs/ directory."""
    monkeypatch.setattr(_pl, "_DEFAULT_LOGS_DIR", str(tmp_path / "logs"))


@pytest.fixture(autouse=True)
def seed_pipeline_manifest_when_missing(monkeypatch):
    """When there is no live pipeline in the clean workspace, it points to the frozen fixture, which is consistent with the behavior when there is config/pipelines/ locally."""
    if os.environ.get("CHRONOS_MANIFEST"):
        return
    if not os.path.isfile(_live_manifest_path()):
        monkeypatch.setenv("CHRONOS_MANIFEST", _FIXTURE_MANIFEST)


@pytest.fixture(autouse=True)
def isolate_config(monkeypatch):
    """Force all engine tests to use isolated empty configurations to prevent misreading the real config.json / hitting the real API.

    Preload a fresh LazyCache with a safe empty configuration so get_config() never reads the
    disk. monkeypatch automatically restores after each test.
    This is the same as using tests/servers to isolate the server configuration with MCP_ENV=testing."""

    _fake_cfg = {
        "llm": {},
        "api": {},
        "server": {},
        "paths": {},
        "novel_import": {
            "chunk_size": 10000,
            "concurrency": None,
            "warn_threshold_chars": 100000,
            "compaction_interval": 5,
        },
        "novels": {
            "trash_retention_days": 30,
        },
    }
    _cache = _config.LazyCache(lambda: _fake_cfg)
    _cache.get()
    monkeypatch.setattr(_config, "_config_cache", _cache)


@pytest.fixture(autouse=True)
def _pin_active_novel(monkeypatch):
    """
All engine tests are fixed to read the default novel to prevent users from switching live active.json in WebUI.
    (like new lore-only novels) impact testing. Tests that require this novel can be overwritten by setenv in the body."""
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "default")


@pytest.fixture(autouse=True)
def _isolate_novels_dir(monkeypatch, tmp_path):
    """Pin CHRONOS_NOVELS_DIR to a fresh per-test tmp directory by default.

    _pin_active_novel above fixes the active novel id to "default", which is also the id of
    the real, user-authored novel under data/novels/default -- so any test that exercises a
    write/delete path without ALSO individually isolating chapters_dir/get_character_archive_dir/
    lore_library_path/etc (there are several independent module-level bindings of these helpers:
    engine.archive.archive_view's own, repositories.json_store's own, context.character_timeline's
    own) silently falls through to the real directory instead of erroring. Confirmed via a live
    incident: an un-isolated write_character_archive test call wrote a bogus archive.json into
    data/novels/default/chapters, and a separate un-isolated delete-from-chapter test then swept
    it up alongside the real chapter's own archives. Tests that need CHRONOS_NOVELS_DIR pointed
    elsewhere (e.g. to assert against a specific fixture novel) already call monkeypatch.setenv
    themselves, which simply overrides this default."""
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path / "novels"))


@pytest.fixture(autouse=True)
def _reset_sliders_hook_rubrics_method():
    """Tests used to monkeypatch SlidersHook via instance `_rubrics` dict; restore the method."""
    from engine.archive.hook_loader import DELTA_HOOKS

    def _clean() -> None:
        for h in DELTA_HOOKS:
            if h.name == "sliders" and isinstance(getattr(h, "_rubrics", None), dict):
                del h._rubrics

    _clean()
    yield
    _clean()


@pytest.fixture(autouse=True)
def _isolate_character_timeline(monkeypatch, tmp_path):
    """Timeline rows live in chronos.sqlite3 under the isolated CHRONOS_NOVELS_DIR (see
    _isolate_novels_dir). No per-module path monkeypatch needed after SQLite migration."""
    del monkeypatch, tmp_path
