import hashlib
import json
import os
import subprocess
from datetime import datetime

from loguru import logger as _logger
from utils.paths import PROJECT_ROOT


def _now_local() -> datetime:
    """The current time in the local time zone (with tz offset). Log ts uses local time to facilitate comparison with product files mtime
    Direct comparison and troubleshooting (the log ownership was misjudged because ts is UTC and is 8/10 hours different from the local mtime)."""
    return datetime.now().astimezone()


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unknown"

_DEFAULT_LOGS_DIR = os.path.join(PROJECT_ROOT, "logs", "engine_server")


class PromptLogger:
    """
Each step is appended to write NDJSON, recording the complete prompt/response/token/time consumption.

    The bottom layer is driven by loguru: each instance registers a dedicated sink and is isolated by _ndjson_id.
    Multiple instances (multiple chapters, test concurrency) do not interfere with each other."""


    def __init__(self, chapter: int, logs_dir: str | None = None) -> None:
        if logs_dir is None:
            logs_dir = _DEFAULT_LOGS_DIR
        os.makedirs(logs_dir, exist_ok=True)
        self.chapter = chapter
        ts = _now_local().strftime("%Y%m%d_%H%M%S")
        self.log_path = os.path.join(logs_dir, f"chapter_{chapter:03d}_{ts}.json")
        # Write run header so we can trace which code version produced this log
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "type": "run_header",
                "ts": _now_local().isoformat(),
                "chapter": chapter,
                "git_commit": _git_commit(),
            }, ensure_ascii=False) + "\n")
        _id = id(self)

        def _sink(message: object) -> None:
            extra = message.record["extra"]  # type: ignore[attr-defined]
            if extra.get("_ndjson_id") != _id:
                return
            system_text = extra["system"]
            entry: dict = {
                "ts": extra["ts"],
                "step": extra["step"],
                "agent": extra["agent"],
                "model": extra["model"],
                "duration_s": extra["duration_s"],
                "tokens_in": extra["tokens_in"],
                "tokens_out": extra["tokens_out"],
                "tokens_cached": extra.get("tokens_cached", 0),
                "prompt_hash": hashlib.md5(system_text.encode()).hexdigest()[:8],
                "system": system_text,
                "user": extra["user"],
                "reasoning": extra.get("reasoning", ""),
                "response": extra["response"],
            }
            if extra.get("tool_messages") is not None:
                entry["tool_messages"] = extra["tool_messages"]
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        self._sink_id = _logger.add(_sink, level="DEBUG")

    def log_llm_call(
        self,
        *,
        step: int,
        agent: str,
        model: str,
        system: str,
        user: str,
        response: str,
        tokens_in: int,
        tokens_out: int,
        duration_s: float,
        tokens_cached: int = 0,
        reasoning: str = "",
        tool_messages: list | None = None,
    ) -> None:
        _logger.bind(
            _ndjson_id=id(self),
            ts=_now_local().isoformat(),
            step=step,
            agent=agent,
            model=model,
            duration_s=round(duration_s, 3),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_cached=tokens_cached,
            reasoning=reasoning,
            system=system,
            user=user,
            response=response,
            tool_messages=tool_messages,
        ).debug("llm_call")

    def log_event(self, event_type: str, **kwargs) -> None:
        """
Record business logic events (step start/completion, staged progress, REFINE stage, etc.)."""
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "type": event_type,
                "ts": _now_local().isoformat(),
                **kwargs,
            }, ensure_ascii=False) + "\n")

    def log_error(
        self,
        *,
        step: int,
        agent: str,
        error: str,
    ) -> None:
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "type": "error",
                "ts": _now_local().isoformat(),
                "step": step,
                "agent": agent,
                "error": error,
            }, ensure_ascii=False) + "\n")

    def load_historical_tokens(
        self,
        *,
        only_steps: set[int] | frozenset[int] | None = None,
        latest_prior_run_only: bool = True,
    ) -> dict[int, tuple[int, int, int]]:
        """Scan the historical logs of this chapter for token consumption (excluding the current run log file).

        latest_prior_run_only: Read only the latest prior log to avoid accumulation of multiple rounds of runs.
        only_steps: Only return the specified steps (for playback after breakpoint, the new process should be empty and skip the call)."""

        log_dir = os.path.dirname(self.log_path)
        prefix = f"chapter_{self.chapter:03d}_"
        current_name = os.path.basename(self.log_path)
        result: dict[int, tuple[int, int, int]] = {}
        try:
            files = sorted(
                f for f in os.listdir(log_dir)
                if f.startswith(prefix) and f.endswith(".json") and f != current_name
            )
        except OSError:
            return result
        if latest_prior_run_only and files:
            files = [files[-1]]
        for fname in files:
            fpath = os.path.join(log_dir, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        step = entry.get("step")
                        in_tok = entry.get("tokens_in")
                        out_tok = entry.get("tokens_out")
                        cached_tok = entry.get("tokens_cached", 0)
                        if step is None or in_tok is None or out_tok is None:
                            continue
                        step = int(step)
                        if only_steps is not None and step not in only_steps:
                            continue
                        cur = result.get(step, (0, 0, 0))
                        result[step] = (
                            cur[0] + int(in_tok),
                            cur[1] + int(out_tok),
                            cur[2] + int(cached_tok or 0),
                        )
            except OSError:
                continue
        return result

    def close(self) -> None:
        """
Explicitly remove the sink (resident process or callable in tests)."""
        _logger.remove(self._sink_id)
