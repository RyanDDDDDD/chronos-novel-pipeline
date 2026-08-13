# `shared/` — 横切基础设施

与业务域无关、被多模块 import 的极简共享模块。

| 文件 | 作用 | 关键符号 |
|------|------|----------|
| `log.py` | 引擎日志配置：`setup_engine_logger`、hook 专用 stderr sink。 | `setup_engine_logger`、`add_hook_terminal_sink`、`HOOK_LOG_MARK` |

路径常量归 `utils/paths.py`，配置归 `utils/config.py`——本目录不放业务路径。
