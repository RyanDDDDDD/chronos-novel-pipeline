"""CloudModelProfile: per-model thinking enable/disable + construction kwargs."""
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from domain.model_profile import (
    ThinkingEffort,
    construction_client_kwargs_for_entry,
    profile_for_llm,
    resolve_thinking_bind,
)


def test_deepseek_construction_is_neutral():
    entry = {"id": "deepseek-v4-flash", "provider": "openai_compatible", "model_profile": "deepseek"}
    assert construction_client_kwargs_for_entry(entry) == {}


def test_legacy_client_kwargs_used_when_no_model_profile():
    entry = {"id": "custom-x", "client_kwargs": {"temperature": 0.5}}
    assert construction_client_kwargs_for_entry(entry) == {"temperature": 0.5}


def test_deepseek_bind_disabled():
    llm = ChatOpenAI(model="deepseek-v4-flash", api_key="k")
    assert resolve_thinking_bind(llm, enable_thinking=False, effort=ThinkingEffort.HIGH) == {
        "extra_body": {"thinking": {"type": "disabled"}},
        "reasoning_effort": "none",
    }


def test_deepseek_default_enabled_when_unset():
    llm = ChatOpenAI(model="deepseek-v4-flash", api_key="k")
    assert resolve_thinking_bind(llm, enable_thinking=None, effort=ThinkingEffort.LOW) == {
        "extra_body": {"thinking": {"type": "enabled"}},
        "reasoning_effort": "low",
    }


def test_qwen_bind_disabled():
    llm = ChatOpenAI(model="qwen3.7-flash", api_key="k")
    assert resolve_thinking_bind(llm, enable_thinking=False, effort=ThinkingEffort.MEDIUM) == {
        "extra_body": {"enable_thinking": False},
    }


def test_anthropic_bind_disabled():
    llm = ChatAnthropic(model="claude-opus-4-7", api_key="k")
    assert resolve_thinking_bind(llm, enable_thinking=False, effort=ThinkingEffort.HIGH) == {
        "thinking": {"type": "disabled"},
    }


def test_openai_compatible_gemini_unset_returns_empty():
    llm = ChatOpenAI(model="gemini-2.5-flash", api_key="k")
    assert resolve_thinking_bind(llm, enable_thinking=None, effort=ThinkingEffort.MEDIUM) == {}


def test_profile_for_llm_dispatches_by_catalog_entry():
    llm = ChatOpenAI(model="qwen3.7-flash", api_key="k")
    assert profile_for_llm(llm).bind_thinking_enabled(ThinkingEffort.LOW) == {
        "extra_body": {"enable_thinking": True, "thinking_budget": 1024},
    }


def test_profile_for_llm_unwraps_retrying_chat_model():
    """get_cloud_llm/get_registry_llm always hand back a RetryingChatModel
    (RunnableBindingBase), not the raw ChatOpenAI/ChatAnthropic client -- profile
    dispatch must see through that wrapper or thinking-bind silently no-ops."""
    from llm.retry import RetryingChatModel

    inner = ChatOpenAI(model="deepseek-v4-flash", api_key="k")
    wrapped = RetryingChatModel(bound=inner)
    assert resolve_thinking_bind(wrapped, enable_thinking=None, effort=ThinkingEffort.LOW) == {
        "extra_body": {"thinking": {"type": "enabled"}},
        "reasoning_effort": "low",
    }
