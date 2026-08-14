"""Multi-vendor web search: ABC base + subclasses (mirrors domain/model_profile.py's
pattern), so research.py's web_search tool stays a thin orchestrator that doesn't
know which vendor's response shape it's looking at."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum

import httpx
from tavily import AsyncTavilyClient


class SearchProviderKind(StrEnum):
    TAVILY = "tavily"
    BAIDU_QIANFAN = "baidu_qianfan"


@dataclass
class SearchHit:
    text: str
    url: str
    images: list[tuple[str, str | None]] = field(default_factory=list)


@dataclass
class SearchResult:
    answer: str | None
    hits: list[SearchHit]
    top_images: list[tuple[str, str | None]] = field(default_factory=list)


def _normalize_image_entry(entry: object) -> tuple[str, str | None] | None:
    """Tavily image item: str URL or {url, description}."""
    if isinstance(entry, str) and entry.strip():
        return entry.strip(), None
    if isinstance(entry, dict):
        url = entry.get("url") or entry.get("image_url")
        if isinstance(url, str) and url.strip():
            desc = entry.get("description")
            return url.strip(), desc if isinstance(desc, str) and desc.strip() else None
    return None


def _collect_images(top_level: object, results: list[dict]) -> list[tuple[str, str | None]]:
    """Collect + dedupe image URLs (top-level + within each result). No cap here --
    the caller applies the display cap once, after merging every source (see
    research.py::_format_search_text); capping per-call would let each source
    independently fill the cap and defeat the total limit."""
    seen: set[str] = set()
    out: list[tuple[str, str | None]] = []

    def _add(entries: object) -> None:
        if not isinstance(entries, list):
            return
        for entry in entries:
            norm = _normalize_image_entry(entry)
            if norm is None or norm[0] in seen:
                continue
            seen.add(norm[0])
            out.append(norm)

    _add(top_level)
    for row in results:
        _add(row.get("images"))
    return out


class SearchProvider(ABC):
    """Base for a web-search vendor. Subclasses own API auth/request/response parsing;
    callers only ever see the vendor-neutral SearchResult shape."""

    @abstractmethod
    async def search(self, topic: str) -> SearchResult: ...


def _result_text(row: dict) -> str:
    """Tavily result row's own text content (not including image captions --
    those get folded into SearchHit.images, formatted by the caller)."""
    text = row.get("content", "")
    return text if isinstance(text, str) else str(text)


class TavilySearchProvider(SearchProvider):
    def __init__(self, api_key: str, top_k: int) -> None:
        self._api_key = api_key
        self._top_k = max(1, min(top_k, 20))

    async def search(self, topic: str) -> SearchResult:
        client = AsyncTavilyClient(api_key=self._api_key)
        resp = await client.search(
            query=topic,
            max_results=self._top_k,
            include_answer=True,
            search_depth="advanced",
            include_images=True,
            include_image_descriptions=True,
        )
        results = [r for r in (resp.get("results") or []) if isinstance(r, dict)]
        hits = [
            SearchHit(
                text=_result_text(r),
                url=r.get("url", ""),
                images=_collect_images(None, [r]),
            )
            for r in results
        ]
        return SearchResult(
            answer=resp.get("answer") or None,
            hits=hits,
            top_images=_collect_images(resp.get("images"), []),
        )


_QIANFAN_WEB_SEARCH_URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"


class BaiduQianfanSearchProvider(SearchProvider):
    """POST /v2/ai_search/web_search. No synthesized answer field (unlike Tavily) --
    the agent reads hit text itself; see 2026-08-01 spec for the rationale."""

    def __init__(self, api_key: str, top_k: int, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._api_key = api_key
        self._top_k = max(1, min(top_k, 50))
        self._transport = transport

    async def search(self, topic: str) -> SearchResult:
        async with httpx.AsyncClient(transport=self._transport, timeout=30) as client:
            resp = await client.post(
                _QIANFAN_WEB_SEARCH_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "messages": [{"role": "user", "content": topic}],
                    "search_source": "baidu_search_v2",
                    "resource_type_filter": [{"type": "web", "top_k": self._top_k}],
                },
            )
            resp.raise_for_status()
            data = resp.json()

        hits = [
            SearchHit(text=f"{r.get('title', '')}\n{r.get('content', '')}".strip(), url=r.get("url", ""))
            for r in (data.get("references") or [])
            if isinstance(r, dict)
        ]
        return SearchResult(answer=None, hits=hits)


def search_provider_kind(cfg: dict) -> SearchProviderKind:
    api_cfg = cfg.get("api") or {}
    return SearchProviderKind(api_cfg.get("search_provider") or SearchProviderKind.TAVILY)


def build_search_provider(cfg: dict) -> SearchProvider:
    """Construct the configured search provider. Raises ValueError with a
    user-facing Chinese message when the selected provider's key is missing."""
    api_cfg = cfg.get("api") or {}
    top_k = api_cfg.get("search_top_k", 5)
    kind = search_provider_kind(cfg)

    if kind == SearchProviderKind.TAVILY:
        key = api_cfg.get("tavily_api_key", "")
        if not key:
            raise ValueError("未配置 Tavily key，无法联网检索。请在服务配置页填入 tavily_api_key。")
        return TavilySearchProvider(api_key=key, top_k=top_k)

    key = api_cfg.get("qianfan_api_key", "")
    if not key:
        raise ValueError("未配置百度千帆 key，无法联网检索。请在服务配置页填入 qianfan_api_key。")
    return BaiduQianfanSearchProvider(api_key=key, top_k=top_k)
