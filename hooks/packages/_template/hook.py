"""{package} 插件钩子。"""
from __future__ import annotations

from engine.execution.agent_hook import AgentHook


class Hook(AgentHook):
    display_name = "{role}"
    description = "TODO: 节点职能一句话"
    default_role = "{role}"
