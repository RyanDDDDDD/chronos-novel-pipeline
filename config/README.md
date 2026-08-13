# Chronos 全局配置中心 (Global Configuration)

本目录存放 Chronos 叙事引擎的全局运行参数、管线定义及环境配置。

---

## 📂 核心文件说明

### 1. Pipeline 编排（`config/pipelines/<id>/`）
**全系统的逻辑灵魂**。节点 DAG 存在各档案的 `manifest.json`（live，gitignore）；`active.json` 指向当前选中档案。首启无档案时自动建空白 `default/`。

- **Agent 映射**：每一步由哪个 Agent 角色执行（供 agent-meta 同步与 skill 接线，不驱动运行时拓扑）。
- **skill 启用名单**：`author_loop_skill_prefs.json` 里的 `disabled_detail_skills`/`disabled_buildtime_review_hooks`/`disabled_runtime_review_hooks` 等禁用列表。
- **上下文供给**：不再是"从 MCP Server 抓取字段"——现由 `src/backend/context/`（`ContextRegistry` + `ContextRequest`）在进程内并发装配，`author_loop` 直接调用。

### 2. `config.json`（及 `config.example.json` 示例文件）
**本地环境适配器**。
- **模型路由**：`llm.cloud_model`（云端模型，如 `claude-opus-4-7`/`deepseek-v4-flash`）或 `llm.local_model`（本地模型，经 LM Studio/Ollama 的 OpenAI 兼容接口）的 API 端点与秘钥。
- **并发与限额**：`llm.max_concurrency`/`max_tokens` 等控制并发、Token 上限。
- **通信端口**：`server.engine_port`——内部引擎端口。后端 REST/WebSocket（默认 8775，`CHRONOS_SERVER_PORT` 覆盖）与前端 Vite dev server（固定 5173）不再走 `config.json`——启动时自动探测空闲端口递增避让，无需也不支持用户手动指定。

---

## 🛠️ 配置维护原则
1. **单一事实来源 (SSOT)**：管线拓扑在 WebUI 或当前 active 档案的 `manifest.json` 中维护；测试用冻结样例见 `tests/engine/fixtures/test_pipeline_manifest.json`。禁止在 Python 代码中硬编码步骤逻辑。
2. **机密脱敏**：绝不在 `config.json` 中硬编码 API 秘钥，建议通过环境变量注入。

---
*Chronos Config | 驱动多智能体协同的核心参数库*