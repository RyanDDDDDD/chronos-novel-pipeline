# Agent Package 模板

由 `scripts/new_agent.py` 复制到 `hooks/packages/<package>/`。规范见 [docs/AGENT_PACKAGE.md](../../docs/AGENT_PACKAGE.md)。

占位符：

- `{package}` — 与 `pipeline_manifest.json` 的 `"agent"` 一致  
- `{role}` — 主 prompt 文件名前缀（通常与节点 key 或 `Hook.default_role` 一致）
