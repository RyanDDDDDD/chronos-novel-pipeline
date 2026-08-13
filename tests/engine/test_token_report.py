"""token_report CLI is integrated with the reporting module."""
import json

from utils.reporting import (
    aggregate_by_phase,
    build_token_report_from_log,
    latest_log_per_chapter,
    list_chapter_logs,
    load_call_records,
)


def _write_log(path: str, entries: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "run_header"}) + "\n")
        for e in entries:
            f.write(json.dumps(e) + "\n")


def test_list_and_latest_log_per_chapter(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    _write_log(str(d / "chapter_001_20260101_000000.json"), [
        {"step": 0, "agent": "a", "tokens_in": 1, "tokens_out": 1},
    ])
    _write_log(str(d / "chapter_001_20260102_000000.json"), [
        {"step": 0, "agent": "a", "tokens_in": 9, "tokens_out": 9},
    ])
    logs = list_chapter_logs(chapter=1, logs_dir=str(d))
    latest = latest_log_per_chapter(logs)
    assert latest[1].endswith("chapter_001_20260102_000000.json")
    summaries = aggregate_by_phase(load_call_records(latest[1]))
    assert summaries[0].tokens_in == 9


def test_build_token_report_from_log_totals(tmp_path):
    log = tmp_path / "chapter_002_20260101_120000.json"
    _write_log(str(log), [
        {"step": 0, "agent": "decide:b0", "tokens_in": 1000, "tokens_out": 400, "model": "m"},
        {"step": 1, "agent": "decide:b0", "tokens_in": 800, "tokens_out": 300, "model": "m"},
    ])
    report = build_token_report_from_log(str(log))
    assert "1,800" in report
    assert "700" in report
