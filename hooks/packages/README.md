# 🎭 Agent Package 索引

> **现行主笔路径**使用 `skills/setup_chat_skills/`（构建期对话 skill + 代码 skill 包）与 `engine/author_loop/dialogue_mode/`（LangGraph 整章图）。`hooks/packages/` 是旧 V9–V11 段级 DAG 时代遗留的 Agent Package 加载目录，规范仍由 `AgentPluginLoader` 支撑，但**目前已无真实接线的 agent 包**（最后一个 `dialogue_design` 已确认零运行时消费方并删除——台词设计走 `dialogue_mode` 内的 director 等机制，不需要迁入 `skills/`）：

- **`_template/`** —— 新建 Agent Package 的脚手架（`scripts/new_agent.py` 生成的目标结构）。

V9/V10 时代的段级 DAG Agent 集群已随管线整体退役，目录早已不存在，不再在此列出——历史索引已删除以避免误导；如需对照旧管线设计，查 git 历史。

---

## 🏗 Agent Package 目录结构规范

完整约定见 **[Agent Package 规范](../../docs/AGENT_PACKAGE.md)**（manifest / hook / prompt / assets 与引擎加载器对齐）。

每个 Agent Package 至少应包含：
- **`[role_id].md`**：核心 System Prompt（`role` 由 manifest 节点 key 或 `hook.default_role` 解析，见规范 §3）
- **`agent.meta.json`**：包清单，由 `sync_agent_meta_files` 自动生成 + drift 校验——**禁止手写字段**
- **`hook.py`**（可选）：`class Hook(AgentHook)` —— 预注入、后处理、自审开关等声明式属性
- **`assets/`**（可选）：Agent 专属静态资产
