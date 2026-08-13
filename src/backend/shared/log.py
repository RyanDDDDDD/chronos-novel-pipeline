"""Engine log configuration."""
import os
import sys

from loguru import logger

from utils.paths import PROJECT_ROOT

HOOK_LOG_MARK = "[hook]"
_HOOK_TERMINAL_SINK_ID: int | None = None
_SETUP_CHAT_TOOL_SINK_ID: int | None = None


def add_hook_terminal_sink(*, level: str = "DEBUG") -> None:
    """
Hit hook dispatch to stderr, and the main terminal can see it directly (it does not affect other DEBUG and still only writes files)."""
    global _HOOK_TERMINAL_SINK_ID
    if _HOOK_TERMINAL_SINK_ID is not None:
        return

    _HOOK_TERMINAL_SINK_ID = logger.add(
        sys.stderr,
        format="<cyan>{time:HH:mm:ss.SSS}</cyan> | <level>{level:<8}</level> | {message}",
        level=level,
        filter=lambda r: HOOK_LOG_MARK in r["message"] and "_ndjson_id" not in r["extra"],
        colorize=True,
    )


def add_setup_chat_tool_sink(*, logs_dir: str | None = None) -> None:
    """Dedicated append-only log for the setup_chat agent's tool-call trace
    (engine.setup_chat.tool_trace), grouped by conversation turn.

    Kept in its own file rather than server.log: server.log gets truncated on
    every process restart (main.py opens it with mode "w"), and mixing tool
    calls in with HTTP/connection noise there makes it hard to read one turn's
    full call flow top to bottom."""
    global _SETUP_CHAT_TOOL_SINK_ID
    if _SETUP_CHAT_TOOL_SINK_ID is not None:
        return
    if logs_dir is None:
        logs_dir = os.path.join(PROJECT_ROOT, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_path = os.path.join(logs_dir, "setup_chat_tools.log")
    _SETUP_CHAT_TOOL_SINK_ID = logger.add(
        log_path,
        rotation="50 MB",
        retention="30 days",
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {message}",
        level="INFO",
        filter=lambda r: r["extra"].get("setup_tool") is True,
    )


def setup_engine_logger(chapter: int, logs_dir: str | None = None) -> None:
    """Configure the loguru file sink for the main engine process. Do not call logger.remove() and keep the existing sink."""
    from datetime import datetime

    if logs_dir is None:
        logs_dir = os.path.join(PROJECT_ROOT, "logs", "engine")
    os.makedirs(logs_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(logs_dir, f"chapter_{chapter:03d}_{ts}.log")
    logger.add(
        log_path,
        rotation="50 MB",
        retention="30 days",
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
        level="DEBUG",
        filter=lambda r: "_ndjson_id" not in r["extra"],
    )
