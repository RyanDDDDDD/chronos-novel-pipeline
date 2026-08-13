# `domain/` — 业务实体与统计

系统的业务侧数据：用量/偏好统计的读写。核心状态模型 `PipelineState` 在 `engine/state.py`。

| 文件 | 作用 | 关键符号 |
|------|------|----------|
| `usage.py` | **章节用量清理**：读写 `pipeline_state.json`，章节重置时清除 consumed_poses / plugin_usage。 | `get_pipeline_state_path`、`clear_chapter_usage` |
| `stats.py` | **LLM 选项偏好统计**：纯 key-value 计数存储（哪些选项/动作被选得多）。 | `record`、`_load` |
