"""pipeline_state.json read and write: posture/plugin usage tracking.

Unlike stats.py (preference statistics), this tracks "which gestures/plugins have been consumed"
(used to prevent repeated injection), data is written to pipeline_state.json."""
from __future__ import annotations

import json
import os

from loguru import logger


def get_pipeline_state_path() -> str:
    """
Return the absolute path of pipeline_state.json based on environment variables."""
    data_dir = os.environ.get(
        "MCP_DATA_DIR",
        os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "var")),
    )
    filename = (
        "pipeline_state_test.json"
        if os.environ.get("MCP_ENV") == "testing"
        else "pipeline_state.json"
    )
    return os.path.normpath(os.path.join(data_dir, filename))


def _load(path: str) -> dict:  # type: ignore[return]
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]
    except Exception:
        return {}


def _save(path: str, state: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def clear_chapter_usage(chapter: int, path: str | None = None) -> None:
    """Clear the consumed_poses / plugin_usage records of the specified chapter in pipeline_state.json.

    For chapter reset use: consumed_poses key is 'Chapter N', plugin_usage key is str(N)."""

    p = path or get_pipeline_state_path()
    try:
        state = _load(p)
        state.get("consumed_poses", {}).pop(f"第{chapter}章", None)
        state.get("plugin_usage", {}).pop(str(chapter), None)
        _save(p, state)
        logger.debug("  [RESET] 已清除第{}章使用记录", chapter)
    except Exception as e:
        logger.debug("  [WARN] 清除章节使用记录失败: {}", e)
