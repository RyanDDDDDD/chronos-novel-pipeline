from engine.setup_chat.hooks import make_post_model_hook
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def test_failed_terminal_tool_does_not_block_retry():
    """After the guard is deleted: Even if there is a ToolMessage (success or failure) of the final tool in this round, post_model_hook
    It also never strips off newly initiated tool_calls from the model. Fix "Tool failed → retry was blocked as a chain call of the same wheel →"
    It says to try again but it doesn’t. You have to send the message manually.”"""
    msgs = [
        HumanMessage(content="加个角色"),
        AIMessage(content="", tool_calls=[{"name": "add_character", "args": {}, "id": "1"}]),
        ToolMessage(content="群像校验未通过，未写入：……", name="add_character", tool_call_id="1"),
        AIMessage(content="我重试一下", tool_calls=[{"name": "add_character", "args": {}, "id": "2"}]),
    ]
    hook = make_post_model_hook(None)
    assert hook({"messages": msgs}) == {}


def test_terminal_tool_then_other_construct_not_blocked():
    """
Stop and return to prompt soft constraint: the engine layer no longer blocks the second construct in the same round."""
    msgs = [
        HumanMessage(content="建世界和角色"),
        AIMessage(content="", tool_calls=[{"name": "construct_world", "args": {}, "id": "1"}]),
        ToolMessage(content="已写入世界观。", name="construct_world", tool_call_id="1"),
        AIMessage(content="", tool_calls=[{"name": "add_character", "args": {}, "id": "2"}]),
    ]
    hook = make_post_model_hook(None)
    assert hook({"messages": msgs}) == {}
