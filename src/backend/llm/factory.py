"""LLM instance factory function."""
from __future__ import annotations

import httpx
from domain.model_catalog import resolve_model_entry
from domain.model_profile import (
    ModelProfileKind,
    construction_client_kwargs_for_entry,
    profile_kind_for_entry,
)
from langchain_openai import ChatOpenAI
from utils.cache import KeyedCache, LazyCache

from llm.deepseek_chat import DeepSeekChatOpenAI
from llm.retry import RetryingChatModel


#── Stateless cloud LLM singleton (dedicated to Utility tasks such as file builder)────────────────────────
def _load_cloud_llm():
    from utils.config import get_config
    cfg = get_config()
    return _make_cloud_llm(cfg.get("llm", {}), cfg.get("api", {}))


_cloud_llm_cache: LazyCache[object] = LazyCache(_load_cloud_llm)


def get_cloud_llm():
    """Returns the global stateless cloud LLM singleton. Lazy loading, the configuration is read from ConfigManager when called for the first time.

    Applicable scenarios: Pure API calls without streaming, no token tracking, and no pipeline binding (such as profile builder).
    For calls that require streaming/Token tracking such as the main cycle, go to `llm/caller.py`."""
    return _cloud_llm_cache.get()


def reset_cloud_llm_cache() -> None:
    """Drop the cloud LLM singleton so the next get_cloud_llm() call rebuilds from
    current config. Must run after PUT /api/config persists a changed model/key --
    otherwise a process that already built the singleton keeps using the stale
    client until restart."""
    _cloud_llm_cache.invalidate()
    reset_style_guard_llm_cache()


def _make_local_llm(llm_cfg: dict):
    """
Reserved for use in scenarios such as generate_with_tools that still require a langchain LLM object."""
    kwargs: dict = {
        "base_url": llm_cfg.get("local_base_url", "http://127.0.0.1:1234/v1"),
        "api_key": "lm-studio",
        "model": llm_cfg.get("local_model", "local-model"),
        "max_tokens": llm_cfg.get("local_max_tokens", llm_cfg.get("max_tokens", 8000)),
        "request_timeout": llm_cfg.get("local_request_timeout", llm_cfg.get("stream_timeout", 600)),
    }
    for key in ("temperature", "top_p"):
        if key in llm_cfg:
            kwargs[key] = llm_cfg[key]
    model_kwargs = {
        k: llm_cfg[k]
        for k in ("top_k", "repetition_penalty", "repeat_last_n", "min_p")
        if k in llm_cfg
    }
    model_kwargs.setdefault("enable_thinking", False)
    kwargs["model_kwargs"] = model_kwargs
    # hedge_enabled intentionally omitted: a local single-instance inference server can't
    # serve two concurrent requests without both slowing down -- see hedge design spec.
    return RetryingChatModel(bound=ChatOpenAI(**kwargs))  # type: ignore[call-arg]


def _make_local_openai_params(llm_cfg: dict) -> dict:
    """Returns a dictionary of parameters required to call openai.AsyncOpenAI directly.

    Bypass langchain_openai.ChatOpenAI and solve the problem under Windows ProactorEventLoop
    The deadlock issue between astream/ainvoke and LangGraph event loop inside langchain."""

    extra: dict = {}
    for key in ("temperature", "top_p", "top_k", "repetition_penalty", "min_p"):
        if key in llm_cfg:
            extra[key] = llm_cfg[key]
    extra["enable_thinking"] = False  #Close Qwen3 thinking mode
    return {
        "base_url": llm_cfg.get("local_base_url", "http://127.0.0.1:1234/v1"),
        "api_key": "lm-studio",
        "model": llm_cfg.get("local_model", "local-model"),
        "max_tokens": llm_cfg.get("local_max_tokens", llm_cfg.get("max_tokens", 8000)),
        "timeout": llm_cfg.get("local_request_timeout", llm_cfg.get("stream_timeout", 600)),
        "extra_body": extra,
    }


_local_node_llm_cache: KeyedCache[tuple[str, str], RetryingChatModel] = KeyedCache()


def get_node_local_llm(base_url: str, model: str) -> RetryingChatModel:
    """Per-(base_url, model) cached ChatOpenAI client for node-level provider
    override (e.g. sandbox prose -> local LMStudio). Mirrors get_cloud_llm's
    process-lifetime singleton-cache approach so repeated calls don't rebuild
    the underlying connection pool; a config change only takes effect after
    restart, same trade-off as the existing cloud singleton."""
    def _load() -> RetryingChatModel:
        from utils.config import get_config
        llm_cfg = get_config().get("llm", {})
        # hedge_enabled intentionally omitted: a local single-instance inference server can't
        # serve two concurrent requests without both slowing down -- see hedge design spec.
        return RetryingChatModel(bound=ChatOpenAI(  # type: ignore[call-arg]
            base_url=base_url,
            api_key="lm-studio",  # type: ignore[arg-type]
            model=model,
            max_tokens=llm_cfg.get("local_max_tokens", llm_cfg.get("max_tokens", 8000)),
            request_timeout=llm_cfg.get("local_request_timeout", llm_cfg.get("stream_timeout", 600)),
        ))
    return _local_node_llm_cache.get((base_url, model), _load)


def _make_cloud_http_client(llm_cfg: dict) -> httpx.AsyncClient:
    max_conc = int(llm_cfg.get("max_concurrency", 32))
    return httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=max_conc,
            max_keepalive_connections=max_conc,
            keepalive_expiry=120,
        ),
    )


def _build_llm_from_entry(entry: dict, llm_cfg: dict, api_cfg: dict):
    """Shared construction logic for a resolved catalog-or-custom entry. Used by both
    _make_cloud_llm (global default singleton) and get_registry_llm (node-level
    model_ref override) so the two paths can't drift."""
    model = entry.get("model") or entry["id"]
    provider = entry.get("provider") or "openai_compatible"
    base_url = entry.get("base_url", "")
    api_key = entry.get("api_key") or (api_cfg.get("model_api_keys") or {}).get(entry["id"], "")
    client_kwargs = construction_client_kwargs_for_entry(entry)

    max_tokens = llm_cfg.get("max_tokens", 8000)
    timeout = llm_cfg.get("stream_timeout", 60)  # was 600 -- see 2026-08-12 hedge design spec
    sampling_kwargs: dict = {}
    for key in ("temperature", "top_p"):
        if key in llm_cfg:
            sampling_kwargs[key] = llm_cfg[key]

    if provider == "openai_compatible":
        http_client = _make_cloud_http_client(llm_cfg)
        chat_cls = (
            DeepSeekChatOpenAI
            if profile_kind_for_entry(entry) == ModelProfileKind.DEEPSEEK
            else ChatOpenAI
        )
        return RetryingChatModel(bound=chat_cls(  # type: ignore[call-arg]
            base_url=base_url,
            api_key=api_key or "placeholder",  # type: ignore[arg-type]
            model=model,
            max_tokens=max_tokens,
            request_timeout=timeout,
            http_async_client=http_client,
            **client_kwargs,
            **sampling_kwargs,
        ), hedge_enabled=True)

    from langchain_anthropic import ChatAnthropic
    anthropic_kwargs: dict = {
        "model": model, "max_tokens": max_tokens, "timeout": timeout, **sampling_kwargs,
    }
    if api_key:
        anthropic_kwargs["api_key"] = api_key
    return RetryingChatModel(bound=ChatAnthropic(**anthropic_kwargs), hedge_enabled=True)  # type: ignore[call-arg]


def _make_cloud_llm(llm_cfg: dict, api_cfg: dict):
    model_id = llm_cfg.get("cloud_model_id", "")
    custom_models = llm_cfg.get("custom_models", [])
    if not isinstance(custom_models, list):
        custom_models = []
    entry = resolve_model_entry(model_id, custom_models=custom_models) if model_id else None
    if entry is None:
        # A truthy but unresolvable model_id (typo, or a deleted custom_models entry
        # still referenced) is a real config error worth failing fast on. An empty/unset
        # model_id is different -- test isolation (tests/engine/conftest.py's autouse
        # isolate_config fixture) deliberately empties llm_cfg, and production configs
        # always carry a real cloud_model_id via _DEFAULTS -- so this falls back to the
        # same empty-but-constructible placeholder entry _make_cloud_llm used to build
        # from an empty custom_cloud, rather than raising.
        if model_id:
            raise ValueError(f"unknown cloud_model_id: {model_id!r}")
        entry = {"id": "", "model": "", "base_url": "", "provider": "anthropic"}
    return _build_llm_from_entry(entry, llm_cfg, api_cfg)


_registry_llm_cache: KeyedCache[str, object] = KeyedCache()


def get_registry_llm(entry: dict):
    """Per-entry-id cached LangChain client for a catalog or custom_models entry.
    Independent from get_cloud_llm's own singleton cache -- this one serves node-level
    model_ref overrides (author_loop_skill_prefs.bind_node_llm), where multiple distinct
    entries (and the global default) may all be in play within one process."""
    entry_id = entry["id"]

    def _load():
        from utils.config import get_config
        cfg = get_config()
        return _build_llm_from_entry(entry, cfg.get("llm", {}), cfg.get("api", {}))
    return _registry_llm_cache.get(entry_id, _load)


def _load_style_guard_llm():
    from domain.model_profile import ThinkingEffort, resolve_thinking_bind
    from utils.config import get_config

    cfg = get_config()
    llm_cfg = cfg.get("llm", {})
    model_ref = llm_cfg.get("style_guard_model_ref", "")
    base_llm = get_cloud_llm()
    if isinstance(model_ref, str) and model_ref.strip():
        custom_models = llm_cfg.get("custom_models", [])
        if not isinstance(custom_models, list):
            custom_models = []
        entry = resolve_model_entry(model_ref.strip(), custom_models=custom_models)
        if entry is not None:
            base_llm = get_registry_llm(entry)
    thinking_bind = resolve_thinking_bind(
        base_llm,
        enable_thinking=False,
        effort=ThinkingEffort.MEDIUM,
    )
    return base_llm.bind(**thinking_bind) if thinking_bind else base_llm


_style_guard_llm_cache: LazyCache[object] = LazyCache(_load_style_guard_llm)


def reset_style_guard_llm_cache() -> None:
    """Drop the style_guard rewrite singleton so the next get_style_guard_llm() rebuilds."""
    _style_guard_llm_cache.invalidate()


def get_style_guard_llm():
    """Global style_guard rewrite client: optional dedicated model_ref, thinking always off.

    Single process-wide instance shared by all guarded_stream/guard_text rewrite callbacks
    (author_loop, story_sandbox). Generation nodes keep their own bind_node_llm clients;
    only the short sentence rewrite path uses this middleware LLM."""
    return _style_guard_llm_cache.get()
