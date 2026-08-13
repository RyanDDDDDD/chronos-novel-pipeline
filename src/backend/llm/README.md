# `llm/` — 大模型基建层

封装 LLM 路由（云端/本地）、Prompt 分层组装、调用日志。上层经 `factory.get_cloud_llm` 取 caller，不直接碰具体模型 SDK。

| 文件 | 作用 | 关键符号 |
|------|------|----------|
| `factory.py` | **LLM 实例工厂**：无状态构造云端/本地 LLM caller（主笔/setup/archive 共用）。 | `get_cloud_llm`、`_make_local_llm`、`_make_cloud_llm` |
| `prompt_manager.py` | **PromptManager**：分层组装 system prompt（global_base → agent prompt → few-shot →（运行时）prose-styles/&lt;preset&gt;，按 active 小说动态拼装）；preamble/状态标记剥离。 | `PromptManager`（`load_agent_prompt`、`strip_preamble`、`strip_status_header`） |
| `prompt_logger.py` | **PromptLogger**：每次 LLM 调用的 prompt/响应/token 落盘（含 git commit 标记），供审计。 | `PromptLogger` |
