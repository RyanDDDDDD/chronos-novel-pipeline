# 运维与分析脚本

`scripts/` 下的辅助工具：跑批诊断、成本分析、数据维护、Agent 包脚手架与 Git 提交门禁。  
一律用 `uv run python scripts/<名>.py` 调用（Windows 下同）。

---

## 跑批诊断（首选）

| 脚本 | 用途 |
|------|------|
| [`prompt_parse.py`](prompt_parse.py) | 从 `logs/engine_server/*.json` 解析每次 LLM 调用的 system / user / response，查 prompt 是否注错、锚点/台词为何异常 |
| [`token_report.py`](token_report.py) | 按 step/agent 聚合 input / cached / output token 与估算成本 |
| [`log_export.py`](log_export.py) | 将 NDJSON 日志导出为人类可读的 Markdown 报告 |
| [`tool_report.py`](tool_report.py) | 分析日志中的 MCP 工具调用：成功率、空返回、按 step 分组 |
| [`ai_word_report.py`](ai_word_report.py) | 按 `WORD_THRESHOLDS`/句式正则给本项目已存章节成稿算每万字 AI 特征密度并排行 |

```bash
# Prompt 调试
uv run python scripts/prompt_parse.py -c 6
uv run python scripts/prompt_parse.py -c 6 --agent director
uv run python scripts/prompt_parse.py logs/engine_server/chapter_006_*.json --list
uv run python scripts/prompt_parse.py path/to/log.json --index 3 -o out.txt

# Token / 成本
uv run python scripts/token_report.py --chapter 4
uv run python scripts/token_report.py --chapter 4 --all

# AI 特征词/句式密度
uv run python scripts/ai_word_report.py
uv run python scripts/ai_word_report.py --chapter 4

# 日志 Markdown 导出
uv run python scripts/log_export.py --chapter 6

# MCP 工具调用
uv run python scripts/tool_report.py --chapter 6 --by-step
uv run python scripts/tool_report.py --errors-only
```

---

## Agent 包脚手架与校验

| 脚本 | 用途 |
|------|------|
| [`new_agent.py`](new_agent.py) | 从 `hooks/packages/_template/` 脚手架生成新 Agent Package（`hook.py`、prompt、`EXAMPLE.md` 等） |
| [`validate_agent_packages.py`](validate_agent_packages.py) | 对照 manifest 校验已接线 agent 的主 prompt、`agent.meta.json`、review rubric、残留 `EXAMPLE.md` 等 |
| [`sync_agent_meta.py`](sync_agent_meta.py) | 根据 manifest + Hook 生成/更新各包 `agent.meta.json`（与 WebUI 保存 manifest 后引擎调用相同） |
| [`audit_agent_assets.py`](audit_agent_assets.py) | 扫描 `hooks/packages/*/assets/*.json`，按 `.schema.json` 与包内 `validator.py` 校验 |

```bash
uv run python scripts/new_agent.py my_agent --role my_role
uv run python scripts/new_agent.py my_agent --role my_role --review --refine

uv run python scripts/validate_agent_packages.py
uv run python scripts/sync_agent_meta.py
uv run python scripts/sync_agent_meta.py --check   # CI：只查漂移，不写盘

uv run python scripts/audit_agent_assets.py
```

规范见 [`docs/AGENT_PACKAGE.md`](../docs/AGENT_PACKAGE.md)。`validate_agent_packages.py` 已接入 **pre-commit**。

---

## 数据与索引维护

| 脚本 | 用途 |
|------|------|
| [`reindex.py`](reindex.py) | 手动调整章节/插件顺序后，重排 `plot_library.json` / `plugin_library.json` 的 chapter、stage_num 等序号 |
| [`validate_data_json.py`](validate_data_json.py) | 遍历 `data/` 下所有 JSON，检查能否 `json.load` |
| [`audit_agent_assets.py`](audit_agent_assets.py) | 见上节 |

```bash
uv run python scripts/reindex.py --plot
uv run python scripts/reindex.py --plugin

uv run python scripts/validate_data_json.py
```

---

## 运行环境与日志清理

| 脚本 | 用途 |
|------|------|
| [`reset_pipeline_state.py`](reset_pipeline_state.py) | 重置 `var/pipeline_state.json`（防重复注入的运行时状态）；可选按章清理 agent 产物与断点缓存 |
| [`clear_logs.py`](clear_logs.py) | 删除 `logs/engine_server/*.json`；清空根目录 `*.log` 内容（保留文件句柄） |
| [`show_selection_stats.py`](show_selection_stats.py) | 查看 WebUI 选项偏好统计（`var/selection_stats.json`：体位 / 前戏 / 插件勾选频次） |

```bash
# 默认：只清 pipeline_state（pre-commit 内部调用；不碰 chapters/）
uv run python scripts/reset_pipeline_state.py

# 按章重跑：删该章 *.md 产物与 temp/ 断点；保留 characters/ 档案
uv run python scripts/reset_pipeline_state.py --chapter 1

uv run python scripts/clear_logs.py

uv run python scripts/show_selection_stats.py
uv run python scripts/show_selection_stats.py --reset
```

---

## Git Hooks（`hooks/`）

| 文件 | 用途 |
|------|------|
| [`hooks/install.sh`](hooks/install.sh) | 一次性设置 `core.hooksPath=scripts/hooks`，启用版本管理的 hook |
| [`hooks/pre-commit`](hooks/pre-commit) | 提交门禁：`reset_pipeline_state` → `validate_agent_packages` → 全量 `pytest` → `ruff` → `mypy` |

```bash
sh scripts/hooks/install.sh
```

---

## 脚本一览

| 脚本 | 分类 | 一句话 |
|------|------|--------|
| `prompt_parse.py` | 诊断 | LLM 单次调用的 prompt/回复解析 |
| `token_report.py` | 诊断 | Token 与成本按 step 汇总 |
| `log_export.py` | 诊断 | 日志 → Markdown |
| `tool_report.py` | 诊断 | MCP 工具调用统计 |
| `ai_word_report.py` | 诊断 | AI 特征词/句式密度排行 |
| `new_agent.py` | Agent | 新建 Agent Package 脚手架 |
| `validate_agent_packages.py` | Agent | manifest 接线包结构校验 |
| `sync_agent_meta.py` | Agent | 同步 `agent.meta.json` |
| `audit_agent_assets.py` | Agent / 数据 | agent assets JSON schema 校验 |
| `reindex.py` | 数据 | plot / plugin 库序号重排 |
| `validate_data_json.py` | 数据 | `data/` JSON 语法检查 |
| `reset_pipeline_state.py` | 维护 | 流水线运行时状态 / 按章产物清理 |
| `clear_logs.py` | 维护 | 清空日志目录 |
| `show_selection_stats.py` | 维护 | 选项偏好统计查看/重置 |

写入类脚本（`reindex`、`sync_agent_meta`、`reset_pipeline_state --chapter`）执行前建议先 `git status` 确认工作区。
