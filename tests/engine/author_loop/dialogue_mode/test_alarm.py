"""Guard/self-audit alarm instrumentation: terminal real-time + persistent NDJSON behavioral test."""
from __future__ import annotations

import json

from engine.author_loop.dialogue_mode import alarm


def _read_lines(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def test_report_alarm_appends_ndjson_with_fields(tmp_path, monkeypatch):
    path = tmp_path / "alarms.ndjson"
    monkeypatch.setattr(alarm, "alarms_log_path", lambda: str(path))

    alarm.report_alarm(
        "守卫", chapter=3, stage=2, beat=7, character="甲", note="正文已脱制服",
        clothing_before="制服", clothing_after="便装",
    )
    recs = _read_lines(path)
    assert len(recs) == 1
    r = recs[0]
    assert r["type"] == "alarm" and r["kind"] == "守卫"
    assert r["chapter"] == 3 and r["stage"] == 2 and r["beat"] == 7
    assert r["character"] == "甲" and r["note"] == "正文已脱制服"
    assert "ts" in r


def test_record_census_appends_ndjson(tmp_path, monkeypatch):
    path = tmp_path / "alarms.ndjson"
    monkeypatch.setattr(alarm, "alarms_log_path", lambda: str(path))

    alarm.record_census("自审", chapter=1, stage=1, beat=2, checks=3, fires=1)
    recs = _read_lines(path)
    assert len(recs) == 1
    r = recs[0]
    assert r["type"] == "census" and r["kind"] == "自审"
    assert r["beat"] == 2 and r["checks"] == 3 and r["fires"] == 1


def test_alarms_accumulate_across_calls(tmp_path, monkeypatch):
    path = tmp_path / "alarms.ndjson"
    monkeypatch.setattr(alarm, "alarms_log_path", lambda: str(path))

    alarm.report_alarm("守卫", chapter=1, stage=1, beat=0, character="甲", note="x")
    alarm.record_census("守卫", chapter=1, stage=1, beat=0, checks=2, fires=1)
    alarm.report_alarm("自审", chapter=1, stage=1, beat=1, feedback="台词太散")
    assert len(_read_lines(path)) == 3


def test_write_failure_swallowed(tmp_path, monkeypatch):
    #The alarm is an instrumentation, and failure to place the order must not interrupt the writing cycle.
    #Pointing the log "file" to an existing directory → open(..., "a") will throw OSError and the verification will be swallowed.
    dir_as_path = tmp_path / "is_a_dir"
    dir_as_path.mkdir()
    monkeypatch.setattr(alarm, "alarms_log_path", lambda: str(dir_as_path))
    alarm.report_alarm("守卫", chapter=1, stage=1, beat=0, character="甲")  #Don't throw


def test_report_alarm_beat_defaults_to_zero(tmp_path, monkeypatch):
    path = tmp_path / "alarms.ndjson"
    monkeypatch.setattr(alarm, "alarms_log_path", lambda: str(path))
    alarm.report_alarm("观察", chapter=1, stage=2, note="风格问题")
    recs = _read_lines(path)
    assert recs[0]["beat"] == 0


def test_record_census_beat_defaults_to_zero(tmp_path, monkeypatch):
    path = tmp_path / "alarms.ndjson"
    monkeypatch.setattr(alarm, "alarms_log_path", lambda: str(path))
    alarm.record_census("观察", chapter=1, stage=2, checks=1, fires=0)
    recs = _read_lines(path)
    assert recs[0]["beat"] == 0
