"""Human-readable trace of setup_chat agent tool calls, grouped by conversation
turn (spec discussed inline 2026-07-10: gated/rejected calls count too, so the
trace reflects what the model *attempted*, not just what actually ran).

Module-global state is safe here for the same reason skeleton_pipeline.py's
process-global stores are: setup_chat drives exactly one turn at a time (single
resident agent, single background task per process) -- there is no concurrent
turn to clobber this state.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from loguru import logger
from utils.paths import setup_chat_tool_analysis_log_path

_TOOL_LOG_LIMIT = 500
_REPEAT_THRESHOLD = 3

_turn_id = 0
_novel_id = ""
_novel_label = ""
_user_text = ""
_next_seq = 0
_rejected_in_turn = 0
_calls: list[dict] = []


def _preview(obj: object) -> str:
    s = obj if isinstance(obj, str) else repr(obj)
    if len(s) <= _TOOL_LOG_LIMIT:
        return s
    return s[:_TOOL_LOG_LIMIT] + f"…(+{len(s) - _TOOL_LOG_LIMIT})"


def _log(msg: str, *args: object) -> None:
    logger.bind(setup_tool=True).info(msg, *args)


def start_turn(novel_id: str, user_text: str) -> None:
    """Call once at the top of a conversation turn (run_turn/run_recovery)."""
    from api.services.novels import get_novel_name

    global _turn_id, _novel_id, _novel_label, _user_text, _next_seq, _rejected_in_turn, _calls
    _turn_id += 1
    _novel_id = novel_id
    _novel_label = get_novel_name(novel_id)
    _user_text = _preview(user_text)
    _next_seq = 0
    _rejected_in_turn = 0
    _calls = []
    _log("[{}] ══ 回合 #{} 开始 ══ 用户：{}", _novel_label, _turn_id, _user_text)


def next_call(name: str, args: object) -> int:
    """Assign the next call sequence number within the current turn and log the
    attempt. Shared by both real tool dispatch (agent.py) and gate rejections
    (transactional_tools.py) so the sequence is continuous across both."""
    global _next_seq
    _next_seq += 1
    seq = _next_seq
    _calls.append({"seq": seq, "name": name, "args": args, "status": "pending", "result": None})
    _log("[{}][#{}] → {}({})", _novel_label, seq, name, _preview(args))
    return seq


def _update_call(seq: int, status: str, result: object) -> None:
    for call in _calls:
        if call["seq"] == seq:
            call["status"] = status
            call["result"] = _preview(result)
            return


def log_call_ok(seq: int, name: str, result: object) -> None:
    _log("[{}][#{}] ← OK {}：{}", _novel_label, seq, name, _preview(result))
    _update_call(seq, "ok", result)


def log_call_error(seq: int, name: str, error: object) -> None:
    _log("[{}][#{}] ⚠ 出错 {}：{}", _novel_label, seq, name, _preview(error))
    _update_call(seq, "error", error)


def log_call_rejected(seq: int, name: str, reason: str) -> None:
    """Gate (plan_runner.gate_tool_call) blocked this call before it ever reached
    the tool body -- still counts as an attempt in the turn's flow."""
    global _rejected_in_turn
    _rejected_in_turn += 1
    _log("[{}][#{}] ✗ 被拒 {}：{}", _novel_label, seq, name, _preview(reason))
    _update_call(seq, "rejected", reason)


def _canonical_args(args: object) -> str:
    try:
        return json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    except TypeError:
        return repr(args)


def _compute_flags(calls: list[dict]) -> list[dict]:
    """Same tool + same args called >= _REPEAT_THRESHOLD times within one turn --
    the signature of a ReAct loop stuck retrying the identical call (status is
    irrelevant: a rejected call retried unchanged is the same stuck pattern as
    an erroring one)."""
    groups: dict[tuple[str, str], dict] = {}
    for call in calls:
        key = (call["name"], _canonical_args(call["args"]))
        group = groups.setdefault(key, {"tool": call["name"], "args": call["args"], "seqs": []})
        group["seqs"].append(call["seq"])
    return [
        {"tool": g["tool"], "args": g["args"], "count": len(g["seqs"]), "seqs": g["seqs"]}
        for g in groups.values()
        if len(g["seqs"]) >= _REPEAT_THRESHOLD
    ]


def _write_analysis_record(record: dict) -> None:
    """Append a line of NDJSON; silent on failure -- instrumentation must not
    block turn teardown (mirrors dialogue_mode.alarm._append)."""
    path = setup_chat_tool_analysis_log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def end_turn() -> None:
    """Call once at the end of a conversation turn, whatever the outcome."""
    _log(
        "[{}] ══ 回合 #{} 结束（{} 次调用，{} 次被拒）══",
        _novel_label, _turn_id, _next_seq, _rejected_in_turn,
    )
    _write_analysis_record({
        "ts": datetime.now().astimezone().isoformat(),
        "novel_id": _novel_id,
        "novel_label": _novel_label,
        "turn_id": _turn_id,
        "user_text": _user_text,
        "calls": _calls,
        "total_calls": _next_seq,
        "rejected_count": _rejected_in_turn,
        "flags": _compute_flags(_calls),
    })
