"""Human-readable trace of setup_chat agent tool calls, grouped by conversation
turn (spec discussed inline 2026-07-10: gated/rejected calls count too, so the
trace reflects what the model *attempted*, not just what actually ran).

Module-global state is safe here for the same reason skeleton_pipeline.py's
process-global stores are: setup_chat drives exactly one turn at a time (single
resident agent, single background task per process) -- there is no concurrent
turn to clobber this state.
"""
from __future__ import annotations

from loguru import logger

_TOOL_LOG_LIMIT = 500

_turn_id = 0
_novel_label = ""
_next_seq = 0
_rejected_in_turn = 0


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

    global _turn_id, _novel_label, _next_seq, _rejected_in_turn
    _turn_id += 1
    _novel_label = get_novel_name(novel_id)
    _next_seq = 0
    _rejected_in_turn = 0
    _log("[{}] ══ 回合 #{} 开始 ══ 用户：{}", _novel_label, _turn_id, _preview(user_text))


def next_call(name: str, args: object) -> int:
    """Assign the next call sequence number within the current turn and log the
    attempt. Shared by both real tool dispatch (agent.py) and gate rejections
    (transactional_tools.py) so the sequence is continuous across both."""
    global _next_seq
    _next_seq += 1
    seq = _next_seq
    _log("[{}][#{}] → {}({})", _novel_label, seq, name, _preview(args))
    return seq


def log_call_ok(seq: int, name: str, result: object) -> None:
    _log("[{}][#{}] ← OK {}：{}", _novel_label, seq, name, _preview(result))


def log_call_error(seq: int, name: str, error: object) -> None:
    _log("[{}][#{}] ⚠ 出错 {}：{}", _novel_label, seq, name, _preview(error))


def log_call_rejected(seq: int, name: str, reason: str) -> None:
    """Gate (plan_runner.gate_tool_call) blocked this call before it ever reached
    the tool body -- still counts as an attempt in the turn's flow."""
    global _rejected_in_turn
    _rejected_in_turn += 1
    _log("[{}][#{}] ✗ 被拒 {}：{}", _novel_label, seq, name, _preview(reason))


def end_turn() -> None:
    """Call once at the end of a conversation turn, whatever the outcome."""
    _log(
        "[{}] ══ 回合 #{} 结束（{} 次调用，{} 次被拒）══",
        _novel_label, _turn_id, _next_seq, _rejected_in_turn,
    )
