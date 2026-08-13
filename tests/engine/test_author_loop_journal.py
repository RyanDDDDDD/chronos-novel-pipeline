"""Main author of journal NDJSON reading and writing."""
from __future__ import annotations

from engine.author_loop.journal import append_event, load_events


def test_append_and_load(tmp_path):
    p = str(tmp_path / "j.ndjson")
    append_event(p, {"type": "author_loop_skeleton", "total": 2})
    append_event(p, {"type": "author_loop_prompt", "prompt_id": 1})
    assert load_events(p) == [
        {"type": "author_loop_skeleton", "total": 2},
        {"type": "author_loop_prompt", "prompt_id": 1},
    ]


def test_load_missing_returns_empty(tmp_path):
    assert load_events(str(tmp_path / "nope.ndjson")) == []


def test_load_skips_corrupt_lines(tmp_path):
    p = tmp_path / "j.ndjson"
    p.write_text('{"type":"a"}\n坏行不是json\n{"type":"b"}\n', encoding="utf-8")
    assert load_events(str(p)) == [{"type": "a"}, {"type": "b"}]
