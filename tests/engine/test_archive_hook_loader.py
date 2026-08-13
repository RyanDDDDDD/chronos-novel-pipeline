import os
import textwrap
from pathlib import Path

from utils.paths import ARCHIVE_HOOKS_DIR, PROJECT_ROOT


def test_archive_hooks_dir_at_root():
    assert ARCHIVE_HOOKS_DIR == os.path.join(PROJECT_ROOT, "hooks", "archive")


def _write_hook(base: Path, name: str, body: str) -> None:
    d = base / name
    d.mkdir(parents=True)
    (d / "hook.py").write_text(textwrap.dedent(body), encoding="utf-8")


def test_discover_groups_and_sorts(tmp_path):
    from engine.archive.hook_loader import discover_hooks

    _write_hook(tmp_path, "bbb", """
        from engine.archive.archive_hook import ArchiveDeltaHook
        class BHook(ArchiveDeltaHook):
            name = "b"
            fields = ["b"]
            merge = {"b": "replace"}
    """
)
    _write_hook(tmp_path, "aaa", """

        from engine.archive.archive_hook import ArchiveEnrichHook
        class AHook(ArchiveEnrichHook):
            name = "a"
    """
)
    hooks = discover_hooks(base=tmp_path)
    assert [h.name for h in hooks] == ["a", "b"]


def test_collect_merge_strategies_from_delta(tmp_path):
    from engine.archive.hook_loader import collect_merge_strategies, discover_hooks

    _write_hook(tmp_path, "x", """

        from engine.archive.archive_hook import ArchiveDeltaHook
        class XHook(ArchiveDeltaHook):
            name = "x"
            fields = ["foo"]
            merge = {"foo": "deep_ignore_none"}
    """
)
    delta = [h for h in discover_hooks(base=tmp_path) if h.phase == "delta"]
    assert collect_merge_strategies(delta) == {"foo": "deep_ignore_none"}


def test_real_archive_hooks_discovered():
    from engine.archive.hook_loader import (
        DELTA_HOOKS,
        ENRICH_HOOKS,
        collect_merge_strategies,
    )

    assert sorted(h.name for h in DELTA_HOOKS) == ["action", "physique", "sliders", "state"]
    assert sorted(h.name for h in ENRICH_HOOKS) == []
    strat = collect_merge_strategies()
    assert strat["sliders"] == "deep_ignore_none"
    assert strat["action"] == "replace"
    assert strat["physique"] == "deep_remove_none"
