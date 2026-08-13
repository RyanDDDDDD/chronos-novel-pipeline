from engine.setup_chat.agent import split_turn_answer_and_thinking


class _M:
    def __init__(self, type_, content, tool_calls=None):
        self.type = type_
        self.content = content
        self.tool_calls = tool_calls


def test_split_collects_thinking_and_answer():
    msgs = [
        _M("human", "hi"),
        _M("ai", "我先查一下。", tool_calls=[{"id": "t1"}]),
        _M("tool", "r"),
        _M("ai", "查完了，结论如下。"),
    ]
    answer, thinking = split_turn_answer_and_thinking(msgs, last_human=0, persist_dir="")
    assert answer == "查完了，结论如下。"
    assert thinking == "我先查一下。"


def test_split_empty_thinking_when_no_narration():
    msgs = [
        _M("human", "hi"),
        _M("ai", "", tool_calls=[{"id": "t1"}]),
        _M("tool", "r"),
        _M("ai", "结论。"),
    ]
    answer, thinking = split_turn_answer_and_thinking(msgs, last_human=0, persist_dir="")
    assert answer == "结论。"
    assert thinking == ""
