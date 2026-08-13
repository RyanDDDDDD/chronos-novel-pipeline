"""dialogue_mode test isolation: redirect guard/self-review alarm placement to tmp to prevent contamination of real alarms.ndjson.

Integration tests that run real graphs (such as test_chapter_graph) will trigger report_alarm/record_census to write to disk - if it points to the real path,
The test will append garbage lines to logs/engine_server/alarms.ndjson and interfere with alarm_report statistics."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_alarms_log(tmp_path, monkeypatch):
    import engine.author_loop.dialogue_mode.alarm as alarm
    monkeypatch.setattr(alarm, "alarms_log_path", lambda: str(tmp_path / "alarms.ndjson"))
