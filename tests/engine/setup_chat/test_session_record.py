from engine.setup_chat.session_record import (
    append_assistant,
    append_user,
    load_messages,
    next_seq,
)


def test_load_missing_returns_empty(tmp_path):
    assert load_messages(str(tmp_path)) == []


def test_load_bad_json_degrades(tmp_path):
    (tmp_path / "messages.json").write_text("{bad", encoding="utf-8")
    assert load_messages(str(tmp_path)) == []


def test_next_seq_increments():
    assert next_seq([]) == 0
    assert next_seq([{"seq": 0}, {"seq": 1}]) == 2
    assert next_seq([{"seq": 5}]) == 6


def test_append_user_then_assistant_roundtrip(tmp_path):
    u = append_user(str(tmp_path), "你好")
    a = append_assistant(str(tmp_path), "您好，请问设定方向？", msg_id="ai-1")
    assert u["role"] == "user" and u["content"] == "你好" and u["seq"] == 0
    assert u["id"].startswith("u-") and isinstance(u["ts"], int)
    assert a["role"] == "assistant" and a["seq"] == 1 and a["id"] == "ai-1"
    msgs = load_messages(str(tmp_path))
    assert [m["content"] for m in msgs] == ["你好", "您好，请问设定方向？"]
    assert [m["seq"] for m in msgs] == [0, 1]


def test_append_assistant_generates_id_when_absent(tmp_path):
    a = append_assistant(str(tmp_path), "x")
    assert a["id"].startswith("a-")


def test_append_assistant_persists_thinking(tmp_path):
    """The folded thinking block must be persisted with the assistant message and can still be rendered after refreshing (root cause: the old path only stores content)."""
    a = append_assistant(str(tmp_path), "答案", thinking="我先查了查资料")
    assert a["thinking"] == "我先查了查资料"
    loaded = load_messages(str(tmp_path))[-1]
    assert loaded["thinking"] == "我先查了查资料"


def test_append_assistant_omits_empty_thinking(tmp_path):
    """
No thinking → Do not write the thinking key (backward compatibility, no empty collapse blocks)."""
    a = append_assistant(str(tmp_path), "答案")
    assert "thinking" not in a
    a2 = append_assistant(str(tmp_path), "答案2", thinking="")
    assert "thinking" not in a2


def test_append_system(tmp_path):
    from engine.setup_chat.session_record import append_system, load_messages

    rec = append_system(str(tmp_path), "上轮操作已回滚")
    msgs = load_messages(str(tmp_path))
    assert msgs[-1]["role"] == "system"
    assert msgs[-1]["content"] == "上轮操作已回滚"
    assert rec["id"].startswith("s-")


def test_remove_message_removes_matching_id(tmp_path):
    from engine.setup_chat.session_record import remove_message

    u = append_user(str(tmp_path), "会被撤销的草稿")
    a = append_assistant(str(tmp_path), "保留")
    assert remove_message(str(tmp_path), u["id"]) is True
    msgs = load_messages(str(tmp_path))
    assert [m["id"] for m in msgs] == [a["id"]]


def test_remove_message_missing_id_returns_false(tmp_path):
    from engine.setup_chat.session_record import remove_message

    append_user(str(tmp_path), "留着")
    assert remove_message(str(tmp_path), "does-not-exist") is False
    assert len(load_messages(str(tmp_path))) == 1


def test_remove_message_on_empty_store_returns_false(tmp_path):
    from engine.setup_chat.session_record import remove_message

    assert remove_message(str(tmp_path), "u-1") is False


def test_append_choice(tmp_path):
    from engine.setup_chat.session_record import append_choice

    rec = append_choice(str(tmp_path), "继续吗？", ["是", "否"])
    assert rec["role"] == "choice"
    assert rec["content"] == "继续吗？"
    assert rec["options"] == ["是", "否"]
    assert rec["id"].startswith("c-")
    msgs = load_messages(str(tmp_path))
    assert msgs[-1] == rec


def test_append_choice_shares_seq_counter_with_other_roles(tmp_path):
    from engine.setup_chat.session_record import append_choice

    append_user(str(tmp_path), "你好")
    rec = append_choice(str(tmp_path), "继续吗？", ["是", "否"])
    assert rec["seq"] == 1


def test_clear_messages_empties_the_table(tmp_path):
    from engine.setup_chat.session_record import clear_messages

    append_user(str(tmp_path), "你好")
    append_assistant(str(tmp_path), "您好，请问设定方向？")
    assert load_messages(str(tmp_path)) != []

    clear_messages(str(tmp_path))

    assert load_messages(str(tmp_path)) == []


def test_clear_messages_on_empty_store_does_not_raise(tmp_path):
    from engine.setup_chat.session_record import clear_messages

    clear_messages(str(tmp_path))  # must not raise
    assert load_messages(str(tmp_path)) == []


def test_append_after_clear_messages_starts_seq_over(tmp_path):
    from engine.setup_chat.session_record import clear_messages

    append_user(str(tmp_path), "旧消息")
    clear_messages(str(tmp_path))

    rec = append_user(str(tmp_path), "新消息")
    assert rec["seq"] == 0
    assert [m["content"] for m in load_messages(str(tmp_path))] == ["新消息"]
