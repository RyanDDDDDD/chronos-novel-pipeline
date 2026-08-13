"""PromptLogger unit test"""
import json
import os

import pytest
from llm.prompt_logger import PromptLogger


@pytest.fixture
def logger(tmp_path):
    return PromptLogger(chapter=1, logs_dir=str(tmp_path))


def _read_entries(logger: PromptLogger) -> list[dict]:
    """
Return the llm_call entry (filtered out run_header)."""
    with open(logger.log_path, encoding="utf-8") as f:
        return [
            json.loads(line)
            for line in f
            if line.strip() and json.loads(line).get("type") != "run_header"
        ]


def _read_header(logger: PromptLogger) -> dict | None:
    with open(logger.log_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                e = json.loads(line)
                if e.get("type") == "run_header":
                    return e
    return None


# ── run_header ───────────────────────────────────────────────────────────────


def test_run_header_written_on_init(logger):
    hdr = _read_header(logger)
    assert hdr is not None
    assert hdr["type"] == "run_header"
    assert "git_commit" in hdr
    assert "ts" in hdr
    assert hdr["chapter"] == 1


#── Basic fields ──────────────────────────────────────────────────────────


def test_log_creates_file_on_first_write(logger, tmp_path):
    logger.log_llm_call(
        step=1,
        agent="剧情逻辑审计师",
        model="deepseek-chat",
        system="sys",
        user="usr",
        response="resp",
        tokens_in=100,
        tokens_out=50,
        duration_s=1.23,
    )
    assert os.path.exists(logger.log_path)


def test_log_entry_has_required_fields(logger):
    logger.log_llm_call(
        step=3,
        agent="剧情架构师",
        model="deepseek-chat",
        system="系统提示",
        user="用户消息",
        response="输出内容",
        tokens_in=200,
        tokens_out=80,
        duration_s=2.5,
    )
    entries = _read_entries(logger)
    assert len(entries) == 1
    e = entries[0]
    assert e["step"] == 3
    assert e["agent"] == "剧情架构师"
    assert e["model"] == "deepseek-chat"
    assert e["tokens_in"] == 200
    assert e["tokens_out"] == 80
    assert e["duration_s"] == 2.5
    assert e["system"] == "系统提示"
    assert e["user"] == "用户消息"
    assert e["response"] == "输出内容"
    assert "ts" in e
    assert "prompt_hash" in e
    assert len(e["prompt_hash"]) == 8


def test_log_appends_multiple_entries(logger):
    for i in range(3):
        logger.log_llm_call(
            step=i,
            agent="测试Agent",
            model="m",
            system="s",
            user="u",
            response=f"r{i}",
            tokens_in=10,
            tokens_out=5,
            duration_s=0.1,
        )
    entries = _read_entries(logger)
    assert len(entries) == 3
    assert [e["response"] for e in entries] == ["r0", "r1", "r2"]


# ── tool_messages ────────────────────────────────────────────────────────────


def test_log_includes_tool_messages_when_provided(logger):
    tool_msgs = [
        {
            "type": "ai",
            "content": "",
            "tool_calls": [{"name": "get_chapter_outline", "args": {"chapter": 1}}],
        },
        {"type": "tool", "name": "get_chapter_outline", "content": "第一章大纲..."},
        {"type": "ai", "content": "最终回答"},
    ]
    logger.log_llm_call(
        step=1,
        agent="剧情逻辑审计师",
        model="deepseek-chat",
        system="s",
        user="u",
        response="最终回答",
        tokens_in=500,
        tokens_out=100,
        duration_s=5.0,
        tool_messages=tool_msgs,
    )
    e = _read_entries(logger)[0]
    assert "tool_messages" in e
    assert len(e["tool_messages"]) == 3
    assert e["tool_messages"][1]["name"] == "get_chapter_outline"


def test_log_omits_tool_messages_key_when_none(logger):
    logger.log_llm_call(
        step=2,
        agent="A",
        model="m",
        system="s",
        user="u",
        response="r",
        tokens_in=10,
        tokens_out=5,
        duration_s=0.1,
    )
    e = _read_entries(logger)[0]
    assert "tool_messages" not in e


#── File naming ──────────────────────────────────────────────────────────


def test_log_filename_contains_chapter(tmp_path):
    lg = PromptLogger(chapter=7, logs_dir=str(tmp_path))
    assert "chapter_007" in os.path.basename(lg.log_path)


def test_log_filename_ends_with_json(tmp_path):
    lg = PromptLogger(chapter=1, logs_dir=str(tmp_path))
    assert lg.log_path.endswith(".json")
