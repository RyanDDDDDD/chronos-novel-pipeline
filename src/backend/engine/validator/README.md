# `engine/validator/` — 结构校验与 preflight

启动前 fail-fast：agent 包结构、上下文依赖、plot 库形状。零 LLM、尽量零热路径 I/O。

| 文件 | 作用 | 关键符号 |
|------|------|----------|
| `agent_package_check.py` | **Agent Package 校验**：injects⊆requires、meta 同步、未接入包。 | `check_agent_valid`、`sync_agent_meta_files` |
| `plot_validator.py` | `plot_library` 结构验证（设定层构建前）。 | — |

段级产出校验（preserve/structure）在 `execution/validation.py`，与本目录 preflight 分层不同。
