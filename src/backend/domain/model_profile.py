"""Per-model connection profiles: catalog entries delegate thinking enable/disable
shapes to profile subclasses instead of baking provider-specific kwargs into JSON.

Construction-time client kwargs stay neutral; per-node enable_thinking drives bind-time
overrides via bind_thinking_enabled / bind_thinking_disabled."""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.runnables.base import RunnableBindingBase
from langchain_openai import ChatOpenAI

from domain.model_catalog import catalog_entry


class ThinkingEffort(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ModelProfileKind(StrEnum):
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"
    QWEN = "qwen"
    OPENAI_COMPATIBLE = "openai_compatible"


_ANTHROPIC_BUDGET: dict[ThinkingEffort, int] = {
    ThinkingEffort.LOW: 1024,
    ThinkingEffort.MEDIUM: 4096,
    ThinkingEffort.HIGH: 16000,
}

_QWEN_BUDGET: dict[ThinkingEffort, int] = {
    ThinkingEffort.LOW: 1024,
    ThinkingEffort.MEDIUM: 4096,
    ThinkingEffort.HIGH: 16000,
}

# Backward compat: legacy catalog field thinking_resolver → profile kind.
_LEGACY_RESOLVER_TO_PROFILE: dict[str, ModelProfileKind] = {
    "qwen_thinking_budget": ModelProfileKind.QWEN,
    "openai_reasoning_effort": ModelProfileKind.DEEPSEEK,
}


class CloudModelProfile(ABC):
    """Base profile for a cloud model family. Subclasses own provider-specific
    construction defaults and per-call thinking bind shapes."""

    @property
    def default_thinking_enabled(self) -> bool:
        """When a node omits enable_thinking, bind enabled kwargs if True."""
        return False

    @abstractmethod
    def construction_client_kwargs(self) -> dict[str, Any]:
        """Neutral kwargs for ChatOpenAI/ChatAnthropic construction — no forced thinking."""

    @abstractmethod
    def bind_thinking_enabled(self, effort: ThinkingEffort) -> dict[str, Any]:
        """Per-call bind kwargs when the node turns thinking on."""

    @abstractmethod
    def bind_thinking_disabled(self) -> dict[str, Any]:
        """Per-call bind kwargs when the node explicitly turns thinking off."""


class AnthropicModelProfile(CloudModelProfile):
    def construction_client_kwargs(self) -> dict[str, Any]:
        return {}

    def bind_thinking_enabled(self, effort: ThinkingEffort) -> dict[str, Any]:
        return {"thinking": {"type": "enabled", "budget_tokens": _ANTHROPIC_BUDGET[effort]}}

    def bind_thinking_disabled(self) -> dict[str, Any]:
        return {"thinking": {"type": "disabled"}}


class DeepSeekModelProfile(CloudModelProfile):
    @property
    def default_thinking_enabled(self) -> bool:
        return True

    def construction_client_kwargs(self) -> dict[str, Any]:
        return {}

    def bind_thinking_enabled(self, effort: ThinkingEffort) -> dict[str, Any]:
        return {
            "extra_body": {"thinking": {"type": "enabled"}},
            "reasoning_effort": effort.value,
        }

    def bind_thinking_disabled(self) -> dict[str, Any]:
        return {
            "extra_body": {"thinking": {"type": "disabled"}},
            "reasoning_effort": "none",
        }


class QwenModelProfile(CloudModelProfile):
    def construction_client_kwargs(self) -> dict[str, Any]:
        return {}

    def bind_thinking_enabled(self, effort: ThinkingEffort) -> dict[str, Any]:
        return {"extra_body": {"enable_thinking": True, "thinking_budget": _QWEN_BUDGET[effort]}}

    def bind_thinking_disabled(self) -> dict[str, Any]:
        return {"extra_body": {"enable_thinking": False}}


class OpenAICompatibleModelProfile(CloudModelProfile):
    """Generic OpenAI-compatible endpoint with no provider-specific thinking API."""

    def construction_client_kwargs(self) -> dict[str, Any]:
        return {}

    def bind_thinking_enabled(self, effort: ThinkingEffort) -> dict[str, Any]:
        return {"reasoning_effort": effort.value}

    def bind_thinking_disabled(self) -> dict[str, Any]:
        return {"reasoning_effort": "none"}


class _NullModelProfile(CloudModelProfile):
    def construction_client_kwargs(self) -> dict[str, Any]:
        return {}

    def bind_thinking_enabled(self, effort: ThinkingEffort) -> dict[str, Any]:
        return {}

    def bind_thinking_disabled(self) -> dict[str, Any]:
        return {}


_PROFILES: dict[ModelProfileKind, CloudModelProfile] = {
    ModelProfileKind.ANTHROPIC: AnthropicModelProfile(),
    ModelProfileKind.DEEPSEEK: DeepSeekModelProfile(),
    ModelProfileKind.QWEN: QwenModelProfile(),
    ModelProfileKind.OPENAI_COMPATIBLE: OpenAICompatibleModelProfile(),
}


def profile_kind_for_entry(entry: dict | None) -> ModelProfileKind:
    if not entry:
        return ModelProfileKind.OPENAI_COMPATIBLE
    raw = entry.get("model_profile")
    if isinstance(raw, str):
        try:
            return ModelProfileKind(raw)
        except ValueError:
            pass
    legacy = entry.get("thinking_resolver")
    if isinstance(legacy, str) and legacy in _LEGACY_RESOLVER_TO_PROFILE:
        return _LEGACY_RESOLVER_TO_PROFILE[legacy]
    if entry.get("provider") == "anthropic":
        return ModelProfileKind.ANTHROPIC
    model_id = str(entry.get("id", ""))
    if model_id.startswith("deepseek"):
        return ModelProfileKind.DEEPSEEK
    if model_id.startswith("qwen"):
        return ModelProfileKind.QWEN
    return ModelProfileKind.OPENAI_COMPATIBLE


def profile_for_entry(entry: dict | None) -> CloudModelProfile:
    return _PROFILES[profile_kind_for_entry(entry)]


def profile_for_llm(llm: object) -> CloudModelProfile:
    # RetryingChatModel (and any other .bind()/.bind_tools() wrapper) is a
    # RunnableBindingBase, not the underlying ChatOpenAI/ChatAnthropic client itself --
    # unwrap .bound so provider dispatch below still matches the real client instead of
    # silently falling through to _NullModelProfile (get_cloud_llm/get_registry_llm always
    # hand back a RetryingChatModel, so every production caller was hitting this).
    if isinstance(llm, RunnableBindingBase):
        return profile_for_llm(llm.bound)
    if isinstance(llm, ChatAnthropic):
        return _PROFILES[ModelProfileKind.ANTHROPIC]
    if isinstance(llm, ChatOpenAI):
        model_id = getattr(llm, "model_name", None)
        entry = catalog_entry(model_id) if model_id else None
        return profile_for_entry(entry)
    return _NullModelProfile()


def construction_client_kwargs_for_entry(entry: dict | None) -> dict[str, Any]:
    """Profile-owned construction kwargs; legacy catalog client_kwargs are ignored
    when model_profile is set, otherwise merged as escape hatch for custom entries."""
    if not entry:
        return {}
    if entry.get("model_profile") or entry.get("thinking_resolver"):
        return profile_for_entry(entry).construction_client_kwargs()
    legacy = entry.get("client_kwargs")
    return dict(legacy) if isinstance(legacy, dict) else {}


def resolve_thinking_bind(
    llm: object,
    *,
    enable_thinking: bool | None,
    effort: ThinkingEffort,
) -> dict[str, Any]:
    """Map node enable_thinking tri-state + effort to per-call bind kwargs."""
    profile = profile_for_llm(llm)
    if enable_thinking is True:
        return profile.bind_thinking_enabled(effort)
    if enable_thinking is False:
        return profile.bind_thinking_disabled()
    if profile.default_thinking_enabled:
        return profile.bind_thinking_enabled(effort)
    return {}
