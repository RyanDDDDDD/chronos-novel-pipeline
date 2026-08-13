"""WS message log assistance: high-frequency event filtering + long content preview truncation (pure function)."""
from api.services.ws_logging import preview, should_log_event


def test_should_log_skips_high_frequency_events():
    #High frequency: segment by segment output / heartbeat → do not remember
    assert should_log_event("author_loop_segment") is False
    assert should_log_event("author_loop_progress") is False


def test_should_log_keeps_interactive_and_lifecycle_events():
    for t in (
        "author_loop_done", "author_loop_error",
        "author_loop_start", "author_loop_stopped", None,
    ):
        assert should_log_event(t) is True


def test_preview_truncates_long_strings():
    out = preview({"text": "字" * 500}, limit=100)
    assert "…(+400)" in out and len(out) < 200  #Truncate + mark omissions


def test_preview_recurses_dict_and_list():
    out = preview({"prompt_id": 3, "payload": {"choice": 2}, "options": [1, 2, 3]})
    assert "prompt_id=3" in out and "choice=2" in out and "[1, 2, 3]" in out


def test_preview_truncates_long_list():
    out = preview(list(range(50)))
    assert out.endswith("…]")  #Cutoff beyond 10 items
