"""Process-level shared AgentPluginLoader: get_plugin_loader returns the same instance (to prevent hook reloading per request)."""
from __future__ import annotations

import engine.execution.agent_plugin_loader as apl


def test_get_plugin_loader_is_singleton():
    a = apl.get_plugin_loader()
    b = apl.get_plugin_loader()
    assert a is b  #Reuse within the same process without rebuilding


def test_singleton_caches_hook_loads(monkeypatch):
    """The load_hook of the shared instance is cached for the second time (without repeated import/logging)."""
    apl._DEFAULT_LOADER = None  #Reset to isolate
    loader = apl.get_plugin_loader()
    calls: list[str] = []
    orig = loader._find_hook_path
    monkeypatch.setattr(loader, "_find_hook_path",
                        lambda name: calls.append(name) or orig(name))
    loader.load_hook("nonexistent_agent")
    loader.load_hook("nonexistent_agent")
    assert calls == ["nonexistent_agent"]  #_cache is hit for the second time and is not parsed again.
