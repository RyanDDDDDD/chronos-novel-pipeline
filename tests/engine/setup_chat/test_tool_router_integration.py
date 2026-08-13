"""Integration: agent.py's dynamic model callable binds only the routed subset."""
import pytest
from langchain_core.tools import tool


@tool
def tool_a() -> str:
    """Tool A."""
    return "a"


@tool
def tool_b() -> str:
    """Tool B."""
    return "b"


@pytest.mark.asyncio
async def test_select_model_binds_only_routed_subset(monkeypatch):
    from unittest.mock import MagicMock

    all_tools = [tool_a, tool_b]
    bound_with = {}

    class _FakeLLM:
        def bind_tools(self, subset):
            bound_with["names"] = {t.name for t in subset}
            return MagicMock()

    llm = _FakeLLM()

    async def _select_model(state: dict, runtime) -> object:
        routed_names = set(state.get("routed_tool_names") or [])
        subset = [t for t in all_tools if t.name in routed_names] if routed_names else all_tools
        return llm.bind_tools(subset)

    await _select_model({"routed_tool_names": ["tool_a"]}, runtime=None)
    assert bound_with["names"] == {"tool_a"}

    await _select_model({}, runtime=None)
    assert bound_with["names"] == {"tool_a", "tool_b"}
