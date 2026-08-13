"""Find the user profile hook in the root directory of hooks/archive/ (according to AgentPluginLoader: loader is in src, plug-in is in hooks/).

Scan hooks/archive/<name>/hook.py → importlib loading → find ArchiveHook subclass → divide by phase DELTA/ENRICH
→ Stable sorting by directory name (the order has no semantics, only the prompt string can be reproduced)."""
from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

from loguru import logger
from utils.paths import ARCHIVE_HOOKS_DIR

from engine.archive.archive_hook import (
    ArchiveDeltaHook,
    ArchiveEnrichHook,
    ArchiveHook,
)

_BASES = {ArchiveHook, ArchiveDeltaHook, ArchiveEnrichHook}


def _load_hook_classes(hook_path: Path) -> list[type]:
    module_name = f"_archive_hook_{hook_path.parent.name}"
    d = str(hook_path.parent)
    if d not in sys.path:
        sys.path.insert(0, d)
    spec = importlib.util.spec_from_file_location(module_name, hook_path)
    if spec is None or spec.loader is None:
        return []
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ArchiveHookLoader] 加载 {} 失败: {}", hook_path, exc)
        return []
    return [
        obj for _, obj in inspect.getmembers(mod, inspect.isclass)
        if issubclass(obj, ArchiveHook) and obj not in _BASES and obj.__module__ == mod.__name__
    ]


def discover_hooks(base: Path | None = None) -> list[ArchiveHook]:
    root = Path(base) if base is not None else Path(ARCHIVE_HOOKS_DIR)
    if not root.is_dir():
        return []
    out: list[ArchiveHook] = []
    for sub in sorted(p for p in root.iterdir() if p.is_dir()):
        hook_py = sub / "hook.py"
        if not hook_py.exists():
            continue
        for cls in _load_hook_classes(hook_py):
            try:
                out.append(cls())
            except Exception as exc:  # noqa: BLE001
                logger.warning("[ArchiveHookLoader] 实例化 {} 失败: {}", hook_py, exc)
    return out


def collect_merge_strategies(delta_hooks: list[ArchiveDeltaHook] | None = None) -> dict[str, str]:
    hooks = delta_hooks if delta_hooks is not None else DELTA_HOOKS
    out: dict[str, str] = {}
    for h in hooks:
        out.update(getattr(h, "merge", {}))
    return out


def _split(hooks: list[ArchiveHook]) -> tuple[list[ArchiveDeltaHook], list[ArchiveEnrichHook]]:
    delta = [h for h in hooks if isinstance(h, ArchiveDeltaHook)]
    enrich = [h for h in hooks if isinstance(h, ArchiveEnrichHook)]
    return delta, enrich


DELTA_HOOKS, ENRICH_HOOKS = _split(discover_hooks())
