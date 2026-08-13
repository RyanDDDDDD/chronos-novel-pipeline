# 运行时插件根 (`hooks/`)

三类可热插拔插件共用一个顶层目录；加载器在 `src/backend/`，插件包在本目录。

| 子目录 | 常量 | 基类 | 加载器 |
|--------|------|------|--------|
| `packages/` | `AGENTS_DIR` | `AgentHook` | `engine/execution/agent_plugin_loader.py` |
| `archive/` | `ARCHIVE_HOOKS_DIR` | `ArchiveDeltaHook` / `ArchiveEnrichHook` | `engine/archive/hook_loader.py` |
| `context/` | `CONTEXT_HOOKS_DIR` | `ContextProvider` | `context/context_hook_loader.py` |

路径 SSOT：`src/backend/utils/paths.py`（`HOOKS_ROOT`；可用 `CHRONOS_HOOKS_ROOT` 覆盖）。

**不是 Agent 包**：根目录 `skills/` 存跨 agent 协议 Markdown（`global_base.md`、`prose-styles/` 等），由 `SKILLS_DIR` 指向，不进 `hooks/`。

- Agent Package 规范：`docs/AGENT_PACKAGE.md`
- 包内索引：`hooks/packages/README.md`
