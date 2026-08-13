"""Main interaction/event journal: append-only NDJSON. Provides service restart and remount + front-end full scroll playback + audit.

Separate functions from checkpoint: checkpoint=engine continued running state (overwriting), journal=display/audit (append writing).
If writing fails, only a warning will be issued and writing will never be blocked (journal will lose the most front-end playback, but the main text will not be damaged)."""
from __future__ import annotations

import json
import os

from loguru import logger


def append_event(path: str, event: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError as e:  #Writing failure does not block writing
        logger.warning("[journal] append 失败 path={}：{}", path, e)


def load_events(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  #Jump bad lines (partially written/truncated)
    except OSError as e:
        logger.warning("[journal] load 失败 path={}：{}", path, e)
    return out
