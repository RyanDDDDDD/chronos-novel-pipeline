"""Guard/self-audit alarm instrumentation: real-time terminal (loguru → stderr) + persistent NDJSON.

Why it exists: Under the new line-driven architecture, it is unknown whether physical guards and beat-by-beat self-examination still frequently catch text problems. Put here
Each "alarm" (physical contradiction of guard hit/self-judgment rewriting) is sent to the terminal in real time, along with the check/alarm of each beat
The counts are appended to alarms.ndjson across runs for subsequent statistics of alarm frequency - if there are almost no alarms reported, consider deleting these two layers.

Instrumentation must not backfire on writing: all placement exceptions will be swallowed, and loguru will not be thrown."""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from loguru import logger
from utils.paths import alarms_log_path


def report_alarm(kind: str, *, chapter: int, stage: int, beat: int = 0, **fields: Any) -> None:
    """
Single alarm (guard hit/self-trial rewrite): terminal realtime + append NDJSON. beat=beat sequence within the chapter (starting from 0)."""
    detail = " ".join(f"{k}={v!r}" for k, v in fields.items())
    logger.warning(f"[{kind}报警] ch{chapter} stage{stage} beat{beat} {detail}")
    _append({"type": "alarm", "kind": kind, "chapter": chapter, "stage": stage,
             "beat": beat, **fields})


def record_census(
    kind: str, *, chapter: int, stage: int, beat: int = 0, checks: int, fires: int,
) -> None:
    """Check/alarm count per beat: only enter NDJSON (do not refresh the terminal), leaving the denominator for frequency statistics. beat=beat sequence within the chapter."""
    _append({
        "type": "census", "kind": kind, "chapter": chapter, "stage": stage,
        "beat": beat, "checks": checks, "fires": fires,
    })


def _append(record: dict[str, Any]) -> None:
    """
Append a line of NDJSON; silent on failure - instrumentation must not block the writing loop."""
    path = alarms_log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(
                {**record, "ts": datetime.now().astimezone().isoformat()},
                ensure_ascii=False,
            ) + "\n")
    except OSError:
        pass
