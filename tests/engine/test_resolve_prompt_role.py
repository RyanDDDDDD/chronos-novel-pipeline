"""The only true source AgentPluginLoader.resolve_role: role resolution must contain the default_role file.

Returning to the guard - I stepped on the trap twice: plugin_injection (dir≠default_role), scene_director_2 (same as agent
Multiple nodes, node_id with _2 suffix). If ctx.role falls to the node name, {role}_embed.md will be empty → buried in the slot
system empty → rewrite the entire section → parse empty.

SSOT: role is now only parsed in one place by resolve_role. After segment.py is parsed, the string is passed to refine_manager.
refine_manager no longer calculates itself. This test directly adheres to resolve_role."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "backend"))

from engine.execution.agent_plugin_loader import AgentPluginLoader  # noqa: E402


class _Hook:
    def __init__(self, default_role: str = ""):
        self.default_role = default_role


def _loader(hooks: dict) -> AgentPluginLoader:
    ld = AgentPluginLoader.__new__(AgentPluginLoader)
    ld.load_hook = lambda agent: hooks.get(agent)  # type: ignore[method-assign]
    return ld


def test_explicit_role_wins():
    ld = _loader({"demo_agent": _Hook("demo_agent")})
    cfg = {"agent": "demo_agent", "role": "explicit_x", "_node_id": "node_y"}
    assert ld.resolve_role(cfg) == "explicit_x"


def test_numbered_duplicate_node_uses_default_role():
    #Core regression: Same as agent multi-node (node_id with _2 suffix) without explicit role → take default_role,
    #Otherwise, bury the slot prompt according to the node name demo_agent_2_embed.md.
    ld = _loader({"demo_agent": _Hook("demo_agent")})
    cfg = {"agent": "demo_agent", "_node_id": "demo_agent_2"}
    assert ld.resolve_role(cfg) == "demo_agent"


def test_node_id_when_no_default_role():
    #agent 用 handles 分发多角色、无 default_role → 落点用 node_id 本身。
    ld = _loader({"demo_multi_role_agent": _Hook("")})
    cfg = {"agent": "demo_multi_role_agent", "_node_id": "role_a"}
    assert ld.resolve_role(cfg) == "role_a"


def test_agent_fallback():
    ld = _loader({"some_agent": _Hook("")})
    assert ld.resolve_role({"agent": "some_agent"}) == "some_agent"
