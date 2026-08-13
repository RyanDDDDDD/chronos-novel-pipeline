"""export_chat_messages_for_ui: Filter the intermediate state between memory and tool."""
from __future__ import annotations

from engine.setup_chat.history import export_chat_messages_for_ui
from engine.setup_chat.memory import (
    MEMORY_DISPLAY_HEADER,
    strip_decision_echoes,
    strip_internal_for_display,
    strip_memory_for_display,
)


def _msg(role, content, *, id=None, tool_calls=None):
    attrs = {"type": role, "content": content}
    if id is not None:
        attrs["id"] = id
    if tool_calls is not None:
        attrs["tool_calls"] = tool_calls
    return type("M", (), attrs)()


def test_strip_memory_for_display():
    raw = f"{MEMORY_DISPLAY_HEADER}\n- 主角是剑客\n\n好的，继续。"
    assert strip_memory_for_display(raw) == "好的，继续。"


def test_strip_memory_only_returns_empty():
    raw = f"{MEMORY_DISPLAY_HEADER}\n- 主角是剑客"
    assert strip_memory_for_display(raw) == ""


def _decision(text: str) -> dict:
    return {"id": "d1", "domain": "misc", "text": text, "status": "active", "alert": None, "ts": 1.0}


def test_strip_decision_echoes_fuzzy_substring():
    decisions = [_decision("爱丽丝感染原因改为意外（非因自身设定）")]
    echoed = "爱丽丝感染原因改为意外（非因自身设定）"
    assert strip_decision_echoes(echoed, decisions) == ""
    mixed = "用户确认：爱丽丝感染原因改为意外（非因自身设定），请同步梗概。"
    assert "请同步梗概" in strip_decision_echoes(mixed, decisions)


def test_strip_decision_echoes_without_header():
    decisions = [
        _decision("星黏液简化为「粘液/史莱姆」，并连带精简描述"),
        {**_decision("否决爱丽丝作为起源体对其他感染体的潜意识指令权"), "id": "d2"},
    ]
    body = (
        "星黏液简化为「粘液/史莱姆」，并连带精简描述\n"
        "否决爱丽丝作为起源体对其他感染体的潜意识指令权\n\n"
        "好的，已按你的要求调整。"
    )
    assert strip_decision_echoes(body, decisions) == "好的，已按你的要求调整。"


def test_strip_internal_for_display_combines_header_and_decisions():
    decisions = [_decision("已定 X")]
    raw = f"{MEMORY_DISPLAY_HEADER}\n- 已定 X\n\n已定 X\n\n收到。"
    assert strip_internal_for_display(raw, decisions) == "收到。"


def test_export_strips_decision_echo_from_ai(tmp_path):
    from engine.setup_chat.memory import save_memory

    novel_dir = tmp_path / "default"
    persist = novel_dir / "setup_chat"
    persist.mkdir(parents=True)
    decisions = ["爱丽丝感染原因改为意外（非因自身设定）"]
    save_memory(str(persist), {"decisions": decisions})
    echo = "爱丽丝感染原因改为意外（非因自身设定）\n\n明白了。"
    msgs = [_msg("ai", echo, id="a1")]
    out = export_chat_messages_for_ui(msgs, persist_dir=str(persist))
    assert out == [{"id": "a1", "role": "assistant", "content": "明白了。"}]


def test_export_skips_system_and_tool():
    msgs = [
        _msg("system", "secret"),
        _msg("human", "hi", id="h1"),
        _msg("ai", "", tool_calls=[{"id": "t1"}]),
        _msg("tool", "result"),
        _msg("ai", "reply", id="a1"),
    ]
    out = export_chat_messages_for_ui(msgs)
    assert out == [
        {"id": "h1", "role": "user", "content": "hi"},
        {"id": "a1", "role": "assistant", "content": "reply"},
    ]


def test_export_strips_memory_echo_from_ai():
    mem = f"{MEMORY_DISPLAY_HEADER}\n- 已定 X\n\n用户可见回复。"
    msgs = [_msg("ai", mem, id="a1")]
    out = export_chat_messages_for_ui(msgs)
    assert out == [{"id": "a1", "role": "assistant", "content": "用户可见回复。"}]


def test_export_skips_memory_only_ai():
    mem = f"{MEMORY_DISPLAY_HEADER}\n- 已定 X"
    msgs = [_msg("ai", mem, id="a1")]
    assert export_chat_messages_for_ui(msgs) == []


def test_export_folds_tool_call_narration_into_thinking():
    msgs = [
        _msg("human", "建世界观", id="h1"),
        _msg("ai", "好的，我先看看现状。", tool_calls=[{"id": "t1"}]),
        _msg("tool", "result"),
        _msg("ai", "世界观已写好。", id="a1"),
    ]
    out = export_chat_messages_for_ui(msgs)
    assert out == [
        {"id": "h1", "role": "user", "content": "建世界观"},
        {"id": "a1", "role": "assistant", "content": "世界观已写好。",
         "thinking": "好的，我先看看现状。"},
    ]


def test_export_joins_multi_round_narration():
    msgs = [
        _msg("ai", "第一步。", tool_calls=[{"id": "t1"}]),
        _msg("tool", "r1"),
        _msg("ai", "第二步。", tool_calls=[{"id": "t2"}]),
        _msg("tool", "r2"),
        _msg("ai", "完成。", id="a1"),
    ]
    out = export_chat_messages_for_ui(msgs)
    assert out[-1]["thinking"] == "第一步。\n\n第二步。"


def test_export_empty_narration_no_thinking_key():
    msgs = [
        _msg("ai", "", tool_calls=[{"id": "t1"}]),
        _msg("tool", "result"),
        _msg("ai", "reply", id="a1"),
    ]
    out = export_chat_messages_for_ui(msgs)
    assert out == [{"id": "a1", "role": "assistant", "content": "reply"}]
