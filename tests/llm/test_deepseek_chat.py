from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from llm.deepseek_chat import DeepSeekChatOpenAI
from llm.message_utils import clone_ai_message


def test_clone_ai_message_preserves_reasoning_content():
    ai = AIMessage(
        content="answer",
        id="a1",
        additional_kwargs={"reasoning_content": "chain of thought"},
    )
    cloned = clone_ai_message(ai, content="clean answer")
    assert cloned.content == "clean answer"
    assert cloned.additional_kwargs["reasoning_content"] == "chain of thought"


def test_clone_ai_message_clears_tool_calls_from_additional_kwargs():
    ai = AIMessage(
        content="ok",
        id="a1",
        additional_kwargs={
            "reasoning_content": "think",
            "tool_calls": [{"id": "1", "type": "function", "function": {"name": "x", "arguments": "{}"}}],
        },
        invalid_tool_calls=[{"id": "1"}],
    )
    cloned = clone_ai_message(ai, tool_calls=[])
    assert cloned.tool_calls == []
    assert cloned.invalid_tool_calls == []
    assert "tool_calls" not in cloned.additional_kwargs
    assert cloned.additional_kwargs["reasoning_content"] == "think"


def test_deepseek_chat_injects_reasoning_content_into_request_payload():
    llm = DeepSeekChatOpenAI(model="deepseek-v4-flash", api_key="test-key")
    ai = AIMessage(
        content="",
        tool_calls=[{"name": "x", "args": {}, "id": "1", "type": "tool_call"}],
        additional_kwargs={"reasoning_content": "plan step"},
    )
    payload = llm._get_request_payload([HumanMessage(content="hi"), ai, ToolMessage(content="ok", tool_call_id="1")])
    assistant = [m for m in payload["messages"] if m["role"] == "assistant"][0]
    assert assistant["reasoning_content"] == "plan step"


def test_deepseek_chat_injects_empty_reasoning_for_tool_calls_without_stored_reasoning():
    llm = DeepSeekChatOpenAI(model="deepseek-v4-flash", api_key="test-key")
    ai = AIMessage(
        content="",
        tool_calls=[{"name": "x", "args": {}, "id": "1", "type": "tool_call"}],
    )
    payload = llm._get_request_payload([HumanMessage(content="hi"), ai])
    assistant = [m for m in payload["messages"] if m["role"] == "assistant"][0]
    assert assistant["reasoning_content"] == ""


def test_deepseek_chat_create_chat_result_stores_reasoning_content():
    llm = DeepSeekChatOpenAI(model="deepseek-v4-flash", api_key="test-key")
    response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "done",
                "reasoning_content": "thought",
            },
            "finish_reason": "stop",
        }],
        "model": "deepseek-v4-flash",
    }
    result = llm._create_chat_result(response)
    msg = result.generations[0].message
    assert isinstance(msg, AIMessage)
    assert msg.additional_kwargs["reasoning_content"] == "thought"
