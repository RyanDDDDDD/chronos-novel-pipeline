"""_make_cloud_llm: builds the LangChain client from cloud_model_id (catalog hit) or
custom_cloud (catalog miss / explicit "custom"), no longer hardcodes DeepSeek-specific
client_kwargs for every base_url."""
import llm.factory as factory
from langchain_core.runnables.base import Runnable
from utils.cache import KeyedCache, LazyCache


class _FakeChatOpenAI(Runnable):
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError


class _FakeChatAnthropic(Runnable):
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError


def _patch_openai_chat_classes(monkeypatch):
    monkeypatch.setattr(factory, "ChatOpenAI", _FakeChatOpenAI)
    monkeypatch.setattr(factory, "DeepSeekChatOpenAI", _FakeChatOpenAI)


def _catalog_entry(monkeypatch, entry):
    monkeypatch.setattr(
        "domain.model_catalog.catalog_entry",
        lambda model_id: entry if entry and entry["id"] == model_id else None,
    )


def test_make_cloud_llm_catalog_hit_anthropic(monkeypatch):
    monkeypatch.setattr("langchain_anthropic.ChatAnthropic", _FakeChatAnthropic)
    _catalog_entry(monkeypatch, {"id": "claude-opus-4-7", "provider": "anthropic"})
    llm = factory._make_cloud_llm({"cloud_model_id": "claude-opus-4-7"}, {})
    assert llm.bound.kwargs["model"] == "claude-opus-4-7"


def test_make_cloud_llm_catalog_hit_openai_compatible_applies_client_kwargs(monkeypatch):
    _patch_openai_chat_classes(monkeypatch)
    monkeypatch.setattr(factory, "_make_cloud_http_client", lambda cfg: object())
    _catalog_entry(monkeypatch, {
        "id": "deepseek-v4-flash", "provider": "openai_compatible",
        "base_url": "https://api.deepseek.com/v1",
        "model_profile": "deepseek",
    })
    llm = factory._make_cloud_llm({"cloud_model_id": "deepseek-v4-flash"}, {"model_api_keys": {"deepseek-v4-flash": "k"}})
    assert llm.bound.kwargs["model"] == "deepseek-v4-flash"
    assert llm.bound.kwargs["api_key"] == "k"
    assert llm.bound.kwargs["base_url"] == "https://api.deepseek.com/v1"
    assert "reasoning_effort" not in llm.bound.kwargs
    assert "extra_body" not in llm.bound.kwargs


def test_make_cloud_llm_catalog_hit_qwen_thinking_extra_body(monkeypatch):
    monkeypatch.setattr(factory, "ChatOpenAI", _FakeChatOpenAI)
    monkeypatch.setattr(factory, "_make_cloud_http_client", lambda cfg: object())
    _catalog_entry(monkeypatch, {
        "id": "qwen3.7-flash", "provider": "openai_compatible",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model_profile": "qwen",
    })
    llm = factory._make_cloud_llm({"cloud_model_id": "qwen3.7-flash"}, {"model_api_keys": {"qwen3.7-flash": "k"}})
    assert llm.bound.kwargs["model"] == "qwen3.7-flash"
    assert llm.bound.kwargs["api_key"] == "k"
    assert llm.bound.kwargs["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert "extra_body" not in llm.bound.kwargs
    assert "reasoning_effort" not in llm.bound.kwargs


def test_make_cloud_llm_custom_openai_compatible_no_forced_client_kwargs(monkeypatch):
    """A custom entry with no client_kwargs configured must NOT get the DeepSeek-specific
    extra_body/reasoning_effort forced onto it -- that was the pre-catalog bug."""
    monkeypatch.setattr(factory, "ChatOpenAI", _FakeChatOpenAI)
    monkeypatch.setattr(factory, "_make_cloud_http_client", lambda cfg: object())
    _catalog_entry(monkeypatch, None)
    llm = factory._make_cloud_llm(
        {
            "cloud_model_id": "custom",
            "custom_models": [{
                "id": "custom", "model": "my-model", "base_url": "https://my-proxy.example.com/v1",
                "provider": "openai_compatible", "client_kwargs": {}, "api_key": "k",
            }],
        },
        {},
    )
    assert llm.bound.kwargs["model"] == "my-model"
    assert llm.bound.kwargs["api_key"] == "k"
    assert llm.bound.kwargs["base_url"] == "https://my-proxy.example.com/v1"
    assert "reasoning_effort" not in llm.bound.kwargs
    assert "extra_body" not in llm.bound.kwargs


def test_make_cloud_llm_custom_anthropic(monkeypatch):
    monkeypatch.setattr("langchain_anthropic.ChatAnthropic", _FakeChatAnthropic)
    _catalog_entry(monkeypatch, None)
    llm = factory._make_cloud_llm(
        {
            "cloud_model_id": "custom",
            "custom_models": [{
                "id": "custom", "model": "claude-3-haiku", "base_url": "",
                "provider": "anthropic", "client_kwargs": {}, "api_key": "sk-ant-custom",
            }],
        },
        {},
    )
    assert llm.bound.kwargs["model"] == "claude-3-haiku"
    assert llm.bound.kwargs["api_key"] == "sk-ant-custom"


def test_make_cloud_llm_missing_key_falls_back_to_placeholder(monkeypatch):
    _patch_openai_chat_classes(monkeypatch)
    monkeypatch.setattr(factory, "_make_cloud_http_client", lambda cfg: object())
    _catalog_entry(monkeypatch, {
        "id": "deepseek-v4-flash", "provider": "openai_compatible",
        "base_url": "https://api.deepseek.com/v1", "client_kwargs": {},
    })
    llm = factory._make_cloud_llm({"cloud_model_id": "deepseek-v4-flash"}, {"model_api_keys": {}})
    assert llm.bound.kwargs["api_key"] == "placeholder"


def test_make_cloud_llm_anthropic_omits_api_key_when_unconfigured(monkeypatch):
    monkeypatch.setattr("langchain_anthropic.ChatAnthropic", _FakeChatAnthropic)
    _catalog_entry(monkeypatch, {"id": "claude-opus-4-7", "provider": "anthropic"})
    llm = factory._make_cloud_llm({"cloud_model_id": "claude-opus-4-7"}, {"model_api_keys": {}})
    assert "api_key" not in llm.bound.kwargs


def test_make_cloud_llm_anthropic_passes_configured_key(monkeypatch):
    monkeypatch.setattr("langchain_anthropic.ChatAnthropic", _FakeChatAnthropic)
    _catalog_entry(monkeypatch, {"id": "claude-opus-4-7", "provider": "anthropic"})
    llm = factory._make_cloud_llm(
        {"cloud_model_id": "claude-opus-4-7"}, {"model_api_keys": {"claude-opus-4-7": "sk-ant-x"}},
    )
    assert llm.bound.kwargs["api_key"] == "sk-ant-x"


def test_make_cloud_llm_passes_temperature_and_top_p(monkeypatch):
    monkeypatch.setattr("langchain_anthropic.ChatAnthropic", _FakeChatAnthropic)
    _catalog_entry(monkeypatch, {"id": "claude-opus-4-7", "provider": "anthropic"})
    llm = factory._make_cloud_llm({"cloud_model_id": "claude-opus-4-7", "temperature": 0.5, "top_p": 0.9}, {})
    assert llm.bound.kwargs["temperature"] == 0.5
    assert llm.bound.kwargs["top_p"] == 0.9


def test_make_cloud_llm_omits_unset_sampling_params(monkeypatch):
    monkeypatch.setattr("langchain_anthropic.ChatAnthropic", _FakeChatAnthropic)
    _catalog_entry(monkeypatch, {"id": "claude-opus-4-7", "provider": "anthropic"})
    llm = factory._make_cloud_llm({"cloud_model_id": "claude-opus-4-7"}, {})
    assert "temperature" not in llm.bound.kwargs
    assert "top_p" not in llm.bound.kwargs


def test_reset_cloud_llm_cache_forces_rebuild(monkeypatch):
    monkeypatch.setattr("utils.config.get_config", lambda: {"llm": {}, "api": {}})
    monkeypatch.setattr(factory, "_make_cloud_llm", lambda llm_cfg, api_cfg: "stale")
    factory._cloud_llm_cache.invalidate()
    assert factory.get_cloud_llm() == "stale"

    monkeypatch.setattr(factory, "_make_cloud_llm", lambda llm_cfg, api_cfg: "fresh")
    factory.reset_cloud_llm_cache()
    assert factory.get_cloud_llm() == "fresh"


class _FakeChatOpenAILocal(Runnable):
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError


def test_get_node_local_llm_builds_with_lmstudio_defaults(monkeypatch):
    monkeypatch.setattr(factory, "_local_node_llm_cache", KeyedCache())
    monkeypatch.setattr(factory, "ChatOpenAI", _FakeChatOpenAILocal)
    monkeypatch.setattr(
        "utils.config.get_config",
        lambda: {"llm": {"local_max_tokens": 4096, "local_request_timeout": 120}},
    )
    llm = factory.get_node_local_llm("http://localhost:1234/v1", "qwen3-8b")
    assert llm.bound.kwargs["base_url"] == "http://localhost:1234/v1"
    assert llm.bound.kwargs["api_key"] == "lm-studio"
    assert llm.bound.kwargs["model"] == "qwen3-8b"
    assert llm.bound.kwargs["max_tokens"] == 4096
    assert llm.bound.kwargs["request_timeout"] == 120


def test_get_node_local_llm_falls_back_to_max_tokens_and_stream_timeout(monkeypatch):
    monkeypatch.setattr(factory, "_local_node_llm_cache", KeyedCache())
    monkeypatch.setattr(factory, "ChatOpenAI", _FakeChatOpenAILocal)
    monkeypatch.setattr("utils.config.get_config", lambda: {"llm": {"max_tokens": 6000, "stream_timeout": 300}})
    llm = factory.get_node_local_llm("http://localhost:1234/v1", "m1")
    assert llm.bound.kwargs["max_tokens"] == 6000
    assert llm.bound.kwargs["request_timeout"] == 300


def test_get_node_local_llm_caches_same_key(monkeypatch):
    monkeypatch.setattr(factory, "_local_node_llm_cache", KeyedCache())
    monkeypatch.setattr(factory, "ChatOpenAI", _FakeChatOpenAILocal)
    monkeypatch.setattr("utils.config.get_config", lambda: {"llm": {}})
    first = factory.get_node_local_llm("http://localhost:1234/v1", "m1")
    second = factory.get_node_local_llm("http://localhost:1234/v1", "m1")
    assert first is second


def test_get_node_local_llm_different_key_builds_new_instance(monkeypatch):
    monkeypatch.setattr(factory, "_local_node_llm_cache", KeyedCache())
    monkeypatch.setattr(factory, "ChatOpenAI", _FakeChatOpenAILocal)
    monkeypatch.setattr("utils.config.get_config", lambda: {"llm": {}})
    first = factory.get_node_local_llm("http://localhost:1234/v1", "m1")
    second = factory.get_node_local_llm("http://localhost:1234/v1", "m2")
    assert first is not second


def test_make_cloud_llm_unknown_model_id_raises(monkeypatch):
    _catalog_entry(monkeypatch, None)
    import pytest
    with pytest.raises(ValueError, match="nope"):
        factory._make_cloud_llm({"cloud_model_id": "nope", "custom_models": []}, {})


def test_make_cloud_llm_custom_entry_without_api_key_falls_back_to_model_api_keys(monkeypatch):
    monkeypatch.setattr(factory, "ChatOpenAI", _FakeChatOpenAI)
    monkeypatch.setattr(factory, "_make_cloud_http_client", lambda cfg: object())
    _catalog_entry(monkeypatch, None)
    llm = factory._make_cloud_llm(
        {
            "cloud_model_id": "custom",
            "custom_models": [{
                "id": "custom", "model": "my-model", "base_url": "https://x.example.com/v1",
                "provider": "openai_compatible", "client_kwargs": {},
            }],
        },
        {"model_api_keys": {"custom": "fallback-key"}},
    )
    assert llm.bound.kwargs["api_key"] == "fallback-key"


def test_get_registry_llm_caches_by_entry_id(monkeypatch):
    monkeypatch.setattr(factory, "_registry_llm_cache", KeyedCache())
    monkeypatch.setattr(factory, "ChatOpenAI", _FakeChatOpenAI)
    monkeypatch.setattr(factory, "_make_cloud_http_client", lambda cfg: object())
    monkeypatch.setattr(
        "utils.config.get_config",
        lambda: {"llm": {}, "api": {"model_api_keys": {}}},
    )
    entry = {
        "id": "custom-1", "model": "m1", "base_url": "https://x.example.com/v1",
        "provider": "openai_compatible", "client_kwargs": {}, "api_key": "k",
    }
    first = factory.get_registry_llm(entry)
    second = factory.get_registry_llm(entry)
    assert first is second
    assert first.bound.kwargs["model"] == "m1"


def test_get_registry_llm_different_entry_id_builds_new_instance(monkeypatch):
    monkeypatch.setattr(factory, "_registry_llm_cache", KeyedCache())
    monkeypatch.setattr(factory, "ChatOpenAI", _FakeChatOpenAI)
    monkeypatch.setattr(factory, "_make_cloud_http_client", lambda cfg: object())
    monkeypatch.setattr(
        "utils.config.get_config",
        lambda: {"llm": {}, "api": {"model_api_keys": {}}},
    )
    entry_a = {"id": "a", "model": "m1", "base_url": "https://x.example.com/v1", "provider": "openai_compatible", "client_kwargs": {}, "api_key": "k"}
    entry_b = {"id": "b", "model": "m2", "base_url": "https://x.example.com/v1", "provider": "openai_compatible", "client_kwargs": {}, "api_key": "k"}
    first = factory.get_registry_llm(entry_a)
    second = factory.get_registry_llm(entry_b)
    assert first is not second


class _BindableLLM:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.model_name = kwargs.get("model", "bound")

    def bind(self, **kwargs):
        merged = {**self.kwargs, **kwargs}
        bound = _BindableLLM(**merged)
        bound.bind_kwargs = kwargs
        return bound


def test_get_style_guard_llm_disables_thinking_on_cloud_default(monkeypatch):
    monkeypatch.setattr(factory, "_style_guard_llm_cache", LazyCache(factory._load_style_guard_llm))
    monkeypatch.setattr(factory, "_cloud_llm_cache", LazyCache(lambda: _BindableLLM(model="cloud-main")))
    captured: dict = {}

    def _capture_bind(llm, *, enable_thinking, effort):
        captured["enable_thinking"] = enable_thinking
        return {"thinking": {"type": "disabled"}}

    monkeypatch.setattr("domain.model_profile.resolve_thinking_bind", _capture_bind)
    monkeypatch.setattr(
        "utils.config.get_config",
        lambda: {"llm": {"style_guard_model_ref": ""}, "api": {}},
    )
    sg = factory.get_style_guard_llm()
    assert captured["enable_thinking"] is False
    assert getattr(sg, "bind_kwargs", {}).get("thinking") == {"type": "disabled"}


def test_get_style_guard_llm_uses_dedicated_model_ref(monkeypatch):
    monkeypatch.setattr(factory, "_style_guard_llm_cache", LazyCache(factory._load_style_guard_llm))
    monkeypatch.setattr(factory, "_cloud_llm_cache", LazyCache(lambda: _BindableLLM(model="cloud-main")))
    monkeypatch.setattr(
        factory,
        "resolve_model_entry",
        lambda entry_id, custom_models=None: {
            "id": "mini", "model": "gpt-4o-mini", "base_url": "https://x.example.com/v1",
            "provider": "openai_compatible", "client_kwargs": {}, "api_key": "k",
        } if entry_id == "mini" else None,
    )
    monkeypatch.setattr(
        factory,
        "get_registry_llm",
        lambda entry: _BindableLLM(model=entry["model"]),
    )
    monkeypatch.setattr(
        "domain.model_profile.resolve_thinking_bind",
        lambda llm, *, enable_thinking, effort: {"reasoning_effort": "none"},
    )
    monkeypatch.setattr(
        "utils.config.get_config",
        lambda: {"llm": {"style_guard_model_ref": "mini", "custom_models": []}, "api": {}},
    )
    sg = factory.get_style_guard_llm()
    assert sg.model_name == "gpt-4o-mini"


def test_reset_cloud_llm_cache_also_clears_style_guard(monkeypatch):
    monkeypatch.setattr(factory, "_cloud_llm_cache", LazyCache(lambda: "stale-cloud"))
    monkeypatch.setattr(factory, "_style_guard_llm_cache", LazyCache(lambda: "stale-guard"))
    factory._cloud_llm_cache.get()
    factory._style_guard_llm_cache.get()

    factory.reset_cloud_llm_cache()

    assert factory._cloud_llm_cache.peek() is None
    assert factory._style_guard_llm_cache.peek() is None


def test_make_cloud_llm_openai_compatible_hedge_enabled(monkeypatch):
    _patch_openai_chat_classes(monkeypatch)
    monkeypatch.setattr(factory, "_make_cloud_http_client", lambda cfg: object())
    _catalog_entry(monkeypatch, {
        "id": "deepseek-v4-flash", "provider": "openai_compatible",
        "base_url": "https://api.deepseek.com/v1",
    })
    llm = factory._make_cloud_llm({"cloud_model_id": "deepseek-v4-flash"}, {})
    assert llm.hedge_enabled is True


def test_make_cloud_llm_anthropic_hedge_enabled(monkeypatch):
    monkeypatch.setattr("langchain_anthropic.ChatAnthropic", _FakeChatAnthropic)
    _catalog_entry(monkeypatch, {"id": "claude-opus-4-7", "provider": "anthropic"})
    llm = factory._make_cloud_llm({"cloud_model_id": "claude-opus-4-7"}, {})
    assert llm.hedge_enabled is True


def test_make_cloud_llm_default_stream_timeout_is_60s(monkeypatch):
    _patch_openai_chat_classes(monkeypatch)
    monkeypatch.setattr(factory, "_make_cloud_http_client", lambda cfg: object())
    _catalog_entry(monkeypatch, {
        "id": "deepseek-v4-flash", "provider": "openai_compatible",
        "base_url": "https://api.deepseek.com/v1",
    })
    llm = factory._make_cloud_llm({"cloud_model_id": "deepseek-v4-flash"}, {})
    assert llm.bound.kwargs["request_timeout"] == 60


def test_make_cloud_llm_respects_explicit_stream_timeout_override(monkeypatch):
    _patch_openai_chat_classes(monkeypatch)
    monkeypatch.setattr(factory, "_make_cloud_http_client", lambda cfg: object())
    _catalog_entry(monkeypatch, {
        "id": "deepseek-v4-flash", "provider": "openai_compatible",
        "base_url": "https://api.deepseek.com/v1",
    })
    llm = factory._make_cloud_llm(
        {"cloud_model_id": "deepseek-v4-flash", "stream_timeout": 300}, {},
    )
    assert llm.bound.kwargs["request_timeout"] == 300


def test_get_node_local_llm_hedge_disabled(monkeypatch):
    monkeypatch.setattr(factory, "_local_node_llm_cache", KeyedCache())
    monkeypatch.setattr(factory, "ChatOpenAI", _FakeChatOpenAILocal)
    monkeypatch.setattr("utils.config.get_config", lambda: {"llm": {}})
    llm = factory.get_node_local_llm("http://localhost:1234/v1", "m1")
    assert llm.hedge_enabled is False


def test_make_local_llm_hedge_disabled(monkeypatch):
    monkeypatch.setattr(factory, "ChatOpenAI", _FakeChatOpenAILocal)
    llm = factory._make_local_llm({})
    assert llm.hedge_enabled is False
