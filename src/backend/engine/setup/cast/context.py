"""cast generates grounding: read active novel world_bible takes the world context.

cast forces the world to be built first - without world_bible (or empty), an error will be reported, prompting "Build a world view" first."""
from __future__ import annotations

import json
import os
from typing import Any

from engine.setup.world.summary import render_world_summary


def load_cast_grounding() -> dict[str, Any]:
    """
Return {world_text}. raise ValueError if world_bible does not exist/is empty."""
    from utils.paths import world_bible_path

    path = world_bible_path()
    wb: Any = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                wb = json.load(f)
        except (OSError, json.JSONDecodeError):
            wb = {}
    world_text = render_world_summary(wb if isinstance(wb, dict) else {})
    if not world_text:
        raise ValueError("当前小说没有世界设定，请先「构建世界观」")
    return {"world_text": world_text}
