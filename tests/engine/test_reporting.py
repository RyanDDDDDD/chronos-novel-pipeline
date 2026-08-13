"""Unit tests for utils.reporting (NDJSON log → token report)."""
import json

from utils.reporting import (
    CallRecord,
    PhaseSummary,
    aggregate_by_phase,
    build_token_report,
    build_token_report_from_log,
    format_run_table,
    load_call_records,
)


def _write_log(path: str, entries: list[dict], *, git_commit: str = "") -> None:
    with open(path, "w", encoding="utf-8") as f:
        header: dict = {"type": "run_header", "chapter": 1}
        if git_commit:
            header["git_commit"] = git_commit
        f.write(json.dumps(header) + "\n")
        for e in entries:
            f.write(json.dumps(e) + "\n")


def test_load_and_aggregate_by_phase(tmp_path):
    log = tmp_path / "chapter_003_20260101_120000.json"
    _write_log(str(log), [
        {"step": 0, "agent": "decide:b0", "tokens_in": 100, "tokens_out": 20, "model": "m1"},
        {"step": 0, "agent": "write:b0:narrative", "tokens_in": 200, "tokens_out": 80, "model": "m1"},
        {"step": 1, "agent": "decide:b0", "tokens_in": 50, "tokens_out": 10, "model": "m1"},
    ])
    records = load_call_records(str(log))
    summaries = aggregate_by_phase(records)
    assert len(summaries) == 3
    assert summaries[0].agent == "decide:b0"
    assert summaries[0].tokens_in == 100
    assert summaries[1].agent == "write:b0:narrative"
    assert summaries[1].tokens_in == 200


def test_build_token_report_markdown_structure():
    summaries = [
        PhaseSummary(
            step=0, agent="decide:b0", models={"claude-sonnet"},
            tokens_in=1000, tokens_out=400, call_count=1,
        ),
        PhaseSummary(
            step=0, agent="write:b0:dialogue", models={"claude-sonnet"},
            tokens_in=800, tokens_out=300, call_count=2,
        ),
    ]
    result = build_token_report(3, summaries, model_hint="claude-sonnet", log_name="test.json")
    assert "# 第3章 Token 消耗报告" in result
    assert "decide:b0" in result
    assert "write:b0:dialogue" in result
    assert "×2" in result
    assert "1,000" in result
    assert "**合计**" in result


def test_build_token_report_from_log(tmp_path):
    log = tmp_path / "chapter_001_20260101_120000.json"
    _write_log(str(log), [
        {"step": 0, "agent": "decide:b0", "tokens_in": 100, "tokens_out": 50, "model": "m"},
    ], git_commit="abc1234")
    report = build_token_report_from_log(str(log))
    assert "# 第1章 Token 消耗报告" in report
    assert "decide:b0" in report
    assert "abc1234" in report
    assert "chapter_001_20260101_120000.json" in report


def test_format_run_table_empty():
    assert "(空日志)" in format_run_table("chapter_001_x.json", [])


def test_format_run_table_highlights_max_load():
    records = [
        CallRecord("t", 0, "decide:b0", "m", 1.0, 100, 10, 0),
        CallRecord("t", 0, "write:b0:x", "m", 2.0, 900, 200, 0),
    ]
    out = format_run_table("chapter_001_20260101_120000.json", records, show_header=False)
    assert "write:b0:x" in out
    assert "◄" in out
