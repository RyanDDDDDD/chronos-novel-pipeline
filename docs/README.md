# 📚 Chronos 文档中心 (Documentation Hub)

本目录存放 Chronos 叙事引擎的架构设计、协议规范、数据格式与创作范式。
本文件只做**索引**——各文档自身是真源（SSOT）。

---

## 🏗 当前架构速览

权威总纲见 `ARCHITECTURE.md`；此处只给定位坐标：

- **创作主路径**：`src/backend/engine/author_loop/dialogue_mode/` — setup_chat 预建 beats → LangGraph 整章图（task_packet → author_prose → review_stage → advance）。
- **设定共创**：`src/backend/engine/setup_chat/` + `skills/setup_chat_skills/`（骨架扩写、分 beat、台词设计）。
- **接口网关**：`src/backend/api/hub.py`（MessageHub，WebSocket 广播 + REST 命令）。
- **数据层**：`src/backend/repositories/`（JsonStore + 领域 repo；**非**独立 MCP 进程）。
- **Pipeline 档案**：`config/pipelines/<id>/manifest.json` + `author_loop_skill_prefs.json`（gitignore）。manifest 供 agent-meta / skill 编排，不驱动运行时拓扑。
- **Agent**：`hooks/packages/<name>/`（`hook.py` + `<role>.md` prompt）。
- **档案 hooks**：`hooks/archive/<name>/`（角色档案/timeline 相关插件）。
- **多小说隔离**：`data/novels/<id>/`。
- **设定批构建**：`src/backend/engine/setup/`（world → cast → plot，legacy 入口）。
- **前端**：`src/frontend/`（主笔流式对话 + Setup Chat + Pipeline 配置视图）。

**典型章节生产路径**：Setup Chat 扩写骨架 → WebUI 选章 → `POST /api/author-loop/start` → 流式落字 → `POST /api/author-loop/save`。

---

## 📂 文档索引

### 架构与协议
- `ARCHITECTURE.md` — 系统架构总纲（dialogue mode、分层、通信协议、架构图）。
- `TECHNICAL_JOURNEY.md` — 技术演进白皮书（里程碑、踩过的系统级坑）。
- `protocol-contract.md` — 主笔循环 WebSocket 事件契约。
- `AGENT_PACKAGE.md` — Agent 包规范（hook + prompt + 资产的组装与注入）。

### 数据格式
- `CHAPTER_TEMPLATE.md` — 章节产物模板（plot_library.json stage 规范；beats 由 setup_chat 写入）。

### 创作范式
- `PLOT_DESIGN_PARADIGM.md` — 解耦式剧情编排范式（plot 作为"干瘪事件流"）。
- `prose-style-template.md` — 文风预设模板格式。
