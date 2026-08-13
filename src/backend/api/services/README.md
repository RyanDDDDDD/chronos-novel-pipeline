# `api/services/` — 网关应用服务

与 FastAPI 路由解耦的领域逻辑：后台任务生命周期、章节目录、pipeline 档案。`routes.py` / `hub.py` 只做接线，业务在此。

| 文件 | 作用 | 关键符号 |
|------|------|----------|
| `message_hub.py` | **MessageHub**：管理后台 task（archive/cast/world/plot/author_loop）+ 多 WebSocket 客户端；事件重放缓冲、广播、主笔交互 Future。 | `MessageHub` |
| `author_loop_skills.py` | 主笔 skill 编排配置读写（per-stage 启用 skill）。 | `read_state`、`write_enabled` |
| `pipeline_catalog.py` | 章节目录：plot + 磁盘进度并集。 | `list_chapters`、`clear_chapter_disk` |
| `pipeline_profiles.py` | Pipeline 档案 CRUD：列举/切换/克隆/新建/改名/删除与一次性迁移。 | — |
| `manifest_admin.py` | Agent 包目录枚举（agent.meta 同步 / 校验用）。 | `agent_names` |
| `novels.py` | 多小说档案读写（创建/切换/重命名/删除）。 | — |
| `asset_audit.py` | 启动前资产快审（缺失 prompt/配置告警）。 | `quick_audit_assets` |
| `paths.py` | API 层共享路径（`PROJECT_ROOT`、`CHAPTERS_DIR`、`manifest_path` 等）。 | — |
