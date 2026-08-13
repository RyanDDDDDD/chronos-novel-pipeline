"""resolve_thinking_kwargs: dispatch by the bound LLM's concrete class, one
resolver per provider. Uses real (locally-constructed, no network call)
ChatAnthropic/ChatOpenAI instances rather than fakes, since the function under
test does a real isinstance() check against those classes."""
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from llm.thinking import ThinkingEffort, resolve_thinking_kwargs


def _anthropic() -> ChatAnthropic:
    return ChatAnthropic(model="claude-3-5-haiku-latest", api_key="test-key")


def _openai_compatible(model: str = "deepseek-v4-flash") -> ChatOpenAI:
    return ChatOpenAI(model=model, api_key="test-key")


def test_anthropic_resolver_maps_effort_to_budget_tokens():
    assert resolve_thinking_kwargs(_anthropic(), ThinkingEffort.LOW) == {
        "thinking": {"type": "enabled", "budget_tokens": 1024},
    }
    assert resolve_thinking_kwargs(_anthropic(), ThinkingEffort.MEDIUM) == {
        "thinking": {"type": "enabled", "budget_tokens": 4096},
    }
    assert resolve_thinking_kwargs(_anthropic(), ThinkingEffort.HIGH) == {
        "thinking": {"type": "enabled", "budget_tokens": 16000},
    }


def test_openai_compatible_deepseek_resolver_passes_effort_and_extra_body():
    assert resolve_thinking_kwargs(_openai_compatible("deepseek-v4-flash"), ThinkingEffort.HIGH) == {
        "extra_body": {"thinking": {"type": "enabled"}},
        "reasoning_effort": "high",
    }


def test_openai_compatible_unknown_model_id_falls_back_to_reasoning_effort():
    """Not in the catalog at all (e.g. a custom_cloud endpoint) -> same default
    behavior as before this change, no regression."""
    assert resolve_thinking_kwargs(_openai_compatible("some-custom-model"), ThinkingEffort.LOW) == {
        "reasoning_effort": "low",
    }


def test_qwen_thinking_budget_resolver_maps_effort_to_thinking_budget():
    llm = _openai_compatible("qwen3.7-flash")
    assert resolve_thinking_kwargs(llm, ThinkingEffort.LOW) == {
        "extra_body": {"enable_thinking": True, "thinking_budget": 1024},
    }
    assert resolve_thinking_kwargs(llm, ThinkingEffort.MEDIUM) == {
        "extra_body": {"enable_thinking": True, "thinking_budget": 4096},
    }
    assert resolve_thinking_kwargs(llm, ThinkingEffort.HIGH) == {
        "extra_body": {"enable_thinking": True, "thinking_budget": 16000},
    }


def test_unknown_llm_type_returns_empty_dict():
    assert resolve_thinking_kwargs(object(), ThinkingEffort.HIGH) == {}


def test_anthropic_bind_actually_carries_thinking_kwarg_into_request_payload():
    """Guards the core feasibility assumption this design relies on: ChatAnthropic.thinking
    defaults to None (never set in factory.py), so a bind-time `thinking=` kwarg reaches
    the request payload untouched rather than being overridden by a constructor default."""
    llm = _anthropic()
    bound = llm.bind(**resolve_thinking_kwargs(llm, ThinkingEffort.MEDIUM))
    assert bound.kwargs == {"thinking": {"type": "enabled", "budget_tokens": 4096}}
