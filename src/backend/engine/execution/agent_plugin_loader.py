"""AgentPluginLoader: Dynamically discovers and instantiates hook.py in the hooks/packages/ directory.

Discovery rules (by priority):
  1. hooks/packages/<subdirectory>/<agent_name>/hook.py — agent has its own subdirectory
  2. hooks/packages/<agent_name>/hook.py — agent is in the top directory
  3. hooks/packages/<subdirectory>/hook.py — directory-level hook, whose Hook.handles contains agent_name

The results are cached by agent_name and are only imported once in the same process."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from loguru import logger

from engine.execution.agent_hook import AgentHook


class AgentPluginLoader:
    """
Dynamically discovers and loads hook.py from the hooks/packages/ directory tree.

    Usage::

        loader = AgentPluginLoader(AGENTS_DIR)
        hook = loader.load_hook("synthesis") # AgentHook | None"""


    def __init__(self, agents_dir: str | Path) -> None:
        self.agents_dir = Path(agents_dir)
        self._cache: dict[str, AgentHook | None] = {}
        #Loaded module path → module to avoid the same hook.py being repeatedly exec'd by multiple agents
        self._mod_cache: dict[Path, object] = {}

    def load_hook(self, agent_name: str) -> AgentHook | None:
        """
Returns the Hook instance corresponding to agent_name.
        Returns None if not found or failed to load (caller falls back to original behavior)."""

        if agent_name in self._cache:
            return self._cache[agent_name]

        hook_path = self._find_hook_path(agent_name)
        hook = self._load_from_path(hook_path) if hook_path else None
        self._cache[agent_name] = hook
        if hook:
            hook._agent_name = agent_name
            logger.debug("[PluginLoader] {} ← {}", agent_name, hook_path)
        return hook


    def resolve_role(self, cfg: dict) -> str | None:
        """
Prompt file name: manifest role > hook.default_role > node key > agent name."""
        explicit = cfg.get("role")
        if explicit:
            return str(explicit)
        agent = cfg.get("agent")
        hook = self.load_hook(agent) if agent else None
        dr = str(getattr(hook, "default_role", "")) if hook else ""
        if dr:
            return dr
        node_id = cfg.get("_node_id")
        if node_id:
            return str(node_id)
        return agent

    #── Path discovery ────────────────────────────────────────────────────────

    def _find_hook_path(self, agent_name: str) -> Path | None:
        if not self.agents_dir.is_dir():
            return None

        #Strategy 1: hooks/packages/<subdirectory>/<agent_name>/hook.py
        for subdir in self.agents_dir.iterdir():
            if not subdir.is_dir():
                continue
            c = subdir / agent_name / "hook.py"
            if c.exists():
                return c

        #Strategy 2: hooks/packages/<agent_name>/hook.py
        c = self.agents_dir / agent_name / "hook.py"
        if c.exists():
            return c

        #Strategy 3: hooks/packages/<subdirectory>/hook.py, check whether Hook.handles contains agent_name
        for subdir in self.agents_dir.iterdir():
            if not subdir.is_dir():
                continue
            c = subdir / "hook.py"
            if c.exists() and agent_name in self._peek_handles(c):
                return c

        return None

    def _peek_handles(self, hook_path: Path) -> list[str]:
        """Load hook.py and read Hook.handles for discovery of strategy 3."""
        hook = self._load_from_path(hook_path)
        return getattr(hook, "handles", []) if hook else []

    #── Loading ───────────────────────────────────────────────────────────

    def _load_from_path(self, hook_path: Path) -> AgentHook | None:
        """
Import hook_path, instantiate and return the Hook class (use _mod_cache to avoid repeated exec)."""
        if hook_path in self._mod_cache:
            mod = self._mod_cache[hook_path]
        else:
            module_name = f"_agent_hook_{hook_path.parent.name}"
            try:
                #Add the directory where the hook is located and the assets/ subdirectory to sys.path.
                #Allow hook.py to directly import `from topology_engine import...`
                _hook_dir   = str(hook_path.parent)
                _assets_dir = str(hook_path.parent / "assets")
                for _d in (_hook_dir, _assets_dir):
                    if _d not in sys.path:
                        sys.path.insert(0, _d)

                spec = importlib.util.spec_from_file_location(module_name, hook_path)
                if spec is None or spec.loader is None:
                    return None
                mod = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = mod
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
                self._mod_cache[hook_path] = mod
            except Exception as exc:
                logger.warning("[PluginLoader] 加载 {} 失败: {}", hook_path, exc)
                return None

        hook_cls = getattr(mod, "Hook", None)
        if hook_cls is None:
            logger.warning("[PluginLoader] {} 未定义 Hook 类，跳过", hook_path)
            return None
        try:
            return hook_cls()  # type: ignore[no-any-return]
        except Exception as exc:
            logger.warning("[PluginLoader] Hook() 实例化失败 {}: {}", hook_path, exc)
            return None


#── Process-level shared singleton ──────────────────────────────────────────────────────
#AGENTS_DIR remains unchanged throughout the process, and the loader cache is instance level - each API/orchestration path will cause hooks if each instance is created.
#Import repeatedly (reload every time the page is refreshed). Unify the factory: build it once when it is first used and reuse it throughout the process.
_DEFAULT_LOADER: AgentPluginLoader | None = None


def get_plugin_loader() -> AgentPluginLoader:
    """Returns a process-level shared AgentPluginLoader (AGENTS_DIR); created and cached on first call."""
    global _DEFAULT_LOADER
    if _DEFAULT_LOADER is None:
        from utils.paths import AGENTS_DIR

        _DEFAULT_LOADER = AgentPluginLoader(AGENTS_DIR)
    return _DEFAULT_LOADER
