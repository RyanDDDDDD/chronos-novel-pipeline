"""Tests for engine.setup_chat.tool_trace: turn-grouped tool-call logging."""
import json

from engine.setup_chat import tool_trace
from loguru import logger


def _capture():
    captured: list[str] = []
    sink_id = logger.add(lambda m: captured.append(str(m)), level="INFO")
    return captured, sink_id


class TestTurnGrouping:
    def test_start_turn_bumps_turn_id_and_resets_sequence(self):
        tool_trace.start_turn("novelA", "第一句话")
        tool_trace.next_call("tool_x", {})
        tool_trace.next_call("tool_y", {})
        first_turn_id = tool_trace._turn_id  # noqa: SLF001 -- internal state, test-only peek

        tool_trace.start_turn("novelA", "第二句话")
        assert tool_trace._turn_id == first_turn_id + 1  # noqa: SLF001
        assert tool_trace._next_seq == 0  # noqa: SLF001
        assert tool_trace._rejected_in_turn == 0  # noqa: SLF001

    def test_next_call_assigns_increasing_sequence(self):
        tool_trace.start_turn("novelA", "hi")
        s1 = tool_trace.next_call("tool_a", {"x": 1})
        s2 = tool_trace.next_call("tool_b", {"y": 2})
        s3 = tool_trace.next_call("tool_c", {})
        assert (s1, s2, s3) == (1, 2, 3)

    def test_rejected_call_shares_sequence_with_real_calls(self):
        """Gate-rejected calls (transactional_tools.py) and real dispatched calls
        (agent.py) must share one continuous per-turn counter -- the trace should
        read as one ordered flow regardless of which path logged each entry."""
        tool_trace.start_turn("novelA", "hi")
        s1 = tool_trace.next_call("read_x", {})
        s2 = tool_trace.next_call("write_chapter_skeleton", {"chapter": 3})
        tool_trace.log_call_rejected(s2, "write_chapter_skeleton", "前置未完成")
        s3 = tool_trace.next_call("read_y", {})
        assert (s1, s2, s3) == (1, 2, 3)
        assert tool_trace._rejected_in_turn == 1  # noqa: SLF001


class TestLogContent:
    def test_full_flow_is_readable_in_order(self):
        captured, sink_id = _capture()
        try:
            tool_trace.start_turn("novelB", "扩写第3章 stage2")
            seq = tool_trace.next_call("set_stage_lens", {"chapter": 3, "stage_num": 2})
            tool_trace.log_call_ok(seq, "set_stage_lens", None)
            seq = tool_trace.next_call("write_chapter_skeleton", {"chapter": 3})
            tool_trace.log_call_rejected(seq, "write_chapter_skeleton", "缺 EXTENSIONS 阶段")
            tool_trace.end_turn()
        finally:
            logger.remove(sink_id)

        lines = [c for c in captured if c.strip()]
        joined = "\n".join(lines)
        assert "novelB" in joined
        assert "开始" in joined and "结束" in joined
        assert "set_stage_lens" in joined
        assert "write_chapter_skeleton" in joined
        assert "被拒" in joined
        assert "缺 EXTENSIONS 阶段" in joined
        # Order preserved: start marker before both calls, end marker after both.
        start_i = next(i for i, line in enumerate(lines) if "开始" in line)
        end_i = next(i for i, line in enumerate(lines) if "结束" in line)
        lens_i = next(i for i, line in enumerate(lines) if "set_stage_lens" in line)
        assert start_i < lens_i < end_i

    def test_long_args_are_truncated(self):
        captured, sink_id = _capture()
        try:
            tool_trace.start_turn("novelC", "hi")
            tool_trace.next_call("write_plot", {"text": "x" * 1000})
        finally:
            logger.remove(sink_id)
        joined = "\n".join(captured)
        assert "…(+" in joined


def _read_ndjson_lines(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class TestAnalysisRecord:
    def test_end_turn_writes_full_call_list(self, tmp_path, monkeypatch):
        path = tmp_path / "analysis.ndjson"
        monkeypatch.setattr(tool_trace, "setup_chat_tool_analysis_log_path", lambda: str(path))

        tool_trace.start_turn("novelD", "写第3章")
        seq = tool_trace.next_call("set_stage_lens", {"chapter": 3})
        tool_trace.log_call_ok(seq, "set_stage_lens", "done")
        tool_trace.end_turn()

        records = _read_ndjson_lines(path)
        assert len(records) == 1
        record = records[0]
        assert record["novel_id"] == "novelD"
        assert record["total_calls"] == 1
        assert record["calls"][0]["name"] == "set_stage_lens"
        assert record["calls"][0]["status"] == "ok"

    def test_repeated_same_args_call_triggers_flag(self, tmp_path, monkeypatch):
        path = tmp_path / "analysis.ndjson"
        monkeypatch.setattr(tool_trace, "setup_chat_tool_analysis_log_path", lambda: str(path))

        tool_trace.start_turn("novelE", "改个设定")
        for _ in range(3):
            seq = tool_trace.next_call("edit_character", {"name": "A"})
            tool_trace.log_call_error(seq, "edit_character", "字段有误")
        tool_trace.end_turn()

        record = _read_ndjson_lines(path)[0]
        assert len(record["flags"]) == 1
        assert record["flags"][0]["tool"] == "edit_character"
        assert record["flags"][0]["count"] == 3

    def test_two_repeats_do_not_trigger_flag(self, tmp_path, monkeypatch):
        path = tmp_path / "analysis.ndjson"
        monkeypatch.setattr(tool_trace, "setup_chat_tool_analysis_log_path", lambda: str(path))

        tool_trace.start_turn("novelF", "改个设定")
        for _ in range(2):
            seq = tool_trace.next_call("edit_character", {"name": "A"})
            tool_trace.log_call_error(seq, "edit_character", "字段有误")
        tool_trace.end_turn()

        record = _read_ndjson_lines(path)[0]
        assert record["flags"] == []

    def test_same_tool_different_args_does_not_trigger_flag(self, tmp_path, monkeypatch):
        path = tmp_path / "analysis.ndjson"
        monkeypatch.setattr(tool_trace, "setup_chat_tool_analysis_log_path", lambda: str(path))

        tool_trace.start_turn("novelG", "改设定")
        for name in ("A", "B", "C"):
            seq = tool_trace.next_call("edit_character", {"name": name})
            tool_trace.log_call_ok(seq, "edit_character", "ok")
        tool_trace.end_turn()

        record = _read_ndjson_lines(path)[0]
        assert record["flags"] == []

    def test_rejected_repeats_also_count_toward_flag(self, tmp_path, monkeypatch):
        """Gate-rejected retries with identical args are exactly the stuck-loop
        pattern this feature exists to surface -- they must count too."""
        path = tmp_path / "analysis.ndjson"
        monkeypatch.setattr(tool_trace, "setup_chat_tool_analysis_log_path", lambda: str(path))

        tool_trace.start_turn("novelH", "写章纲")
        for _ in range(3):
            seq = tool_trace.next_call("write_chapter_skeleton", {"chapter": 3})
            tool_trace.log_call_rejected(seq, "write_chapter_skeleton", "前置未完成")
        tool_trace.end_turn()

        record = _read_ndjson_lines(path)[0]
        assert len(record["flags"]) == 1
        assert record["flags"][0]["count"] == 3

    def test_write_failure_is_swallowed(self, tmp_path, monkeypatch):
        dir_as_path = tmp_path / "is_a_dir"
        dir_as_path.mkdir()
        monkeypatch.setattr(tool_trace, "setup_chat_tool_analysis_log_path", lambda: str(dir_as_path))

        tool_trace.start_turn("novelI", "hi")
        tool_trace.next_call("read_x", {})
        tool_trace.end_turn()  # must not raise
