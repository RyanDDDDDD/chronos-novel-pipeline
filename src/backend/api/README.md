# `api/` — 接口网关层

后端唯一对外入口（FastAPI @ :8775）：WebSocket 推事件流 + REST 收命令。

| 文件 | 作用 | 关键符号 |
|------|------|----------|
| `hub.py` | **入口**：FastAPI `app`、lifespan、CORS；全局 `HUB` 单例。 | `app`、`HUB` |
| `routes.py` | **路由层**：WebSocket `/ws`、REST `/api/*`、静态资源；`author_loop_reply` 解锁主笔交互 Future。 | `register_routes`、`_handle_ws_message` |
| `services/` | 应用服务（MessageHub、章节目录、pipeline 档案等）。 | 见 [`services/README.md`](services/README.md) |
