# `engine/execution/` — Hook 契约与执行原语

> 创作主路径为 **主笔逐段写作循环**（`engine/author_loop/`）。本目录保留主笔/setup/校验共用的 Hook 契约与原语。

| 文件 | 作用 | 关键符号 |
|------|------|----------|
| `agent_hook.py` | **AgentHook 协议基类** + ROUND 出题解析。 | `AgentHook`、`build_round_from_md`、`QuestionType` |
| `agent_plugin_loader.py` | 扫描 `hooks/packages/*/hook.py` 动态加载；注入包路径。 | `AgentPluginLoader`、`get_plugin_loader` |
| `embed_json.py` | LLM-JSON 容错解析（主笔决策/skill 选择、setup 解析共用）。 | `parse_embed_json` |
| `prose_style.py` | per-novel 文风卡片加载。 | `build_active_prose_style_card` |

> 策略下沉 hook；引擎只提供原语。详见 `docs/AGENT_PACKAGE.md`。
