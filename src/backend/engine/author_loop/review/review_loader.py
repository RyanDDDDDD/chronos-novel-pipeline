"""Found the review plug-in under hooks/review/ (according to archive/hook_loader: loader is in src, plug-in is in hooks/).

Scan hooks/review/<name>/hook.py → importlib loading → find ReviewHook subclass → instantiate →
Stable sorting by directory name (the order has no semantics, only reproducibility is guaranteed). Loading/instantiation failure warning skips, does not block."""
from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

from loguru import logger
from utils.paths import REVIEW_HOOKS_DIR

from engine.author_loop.review.review_hook import ReviewHook


def _load_hook_classes(hook_path: Path) -> list[type]:
    module_name = f"_review_hook_{hook_path.parent.name}"
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
    except Exception as exc:  #noqa: BLE001 — A single bad plugin doesn’t bring down discovery
        logger.warning("[ReviewHookLoader] 加载 {} 失败: {}", hook_path, exc)
        return []
    return [
        obj for _, obj in inspect.getmembers(mod, inspect.isclass)
        if issubclass(obj, ReviewHook) and obj is not ReviewHook
        and obj.__module__ == mod.__name__
    ]


def discover_review_hooks(base: Path | None = None) -> list[ReviewHook]:
    root = Path(base) if base is not None else Path(REVIEW_HOOKS_DIR)
    if not root.is_dir():
        return []
    out: list[ReviewHook] = []
    for sub in sorted(p for p in root.iterdir() if p.is_dir()):
        hook_py = sub / "hook.py"
        if not hook_py.exists():
            continue
        for cls in _load_hook_classes(hook_py):
            try:
                out.append(cls())
            except Exception as exc:  # noqa: BLE001
                logger.warning("[ReviewHookLoader] 实例化 {} 失败: {}", hook_py, exc)
    return out


REVIEW_HOOKS: list[ReviewHook] = discover_review_hooks()


def get_review_hook_card(name: str) -> str | None:
    """Read a review hook's markdown card (hooks/review/<name>/<name>.md, the naming
    convention every hook.py already relies on for its own build_prompt). Returns None
    for unknown names and code-only hooks (evaluate()-only, no .md) alike -- callers
    that need to distinguish "unknown hook" from "known hook, no card" should check
    membership in REVIEW_HOOKS themselves first (the API route does this to pick
    404 vs. 200)."""
    if name not in {h.name for h in REVIEW_HOOKS}:
        return None
    path = Path(REVIEW_HOOKS_DIR) / name / f"{name}.md"
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None
