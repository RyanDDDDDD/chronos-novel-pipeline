"""SearchProvider: multi-vendor web search (Tavily / Baidu Qianfan AppBuilder)."""
import json as json_mod

import httpx
import pytest
from domain.search_provider import (
    SearchHit,
    SearchProviderKind,
    SearchResult,
    _collect_images,
    _normalize_image_entry,
)


def test_search_provider_kind_values():
    assert SearchProviderKind.TAVILY == "tavily"
    assert SearchProviderKind.BAIDU_QIANFAN == "baidu_qianfan"
    assert SearchProviderKind.CHRONOS_CLOUD == "chronos_cloud"


def test_search_provider_kind_includes_chronos_cloud():
    assert SearchProviderKind.CHRONOS_CLOUD == "chronos_cloud"


def test_search_hit_defaults_to_no_images():
    hit = SearchHit(text="x", url="http://a")
    assert hit.images == []


def test_search_result_defaults_to_no_top_images():
    result = SearchResult(answer="a", hits=[])
    assert result.top_images == []


def test_normalize_image_entry_from_str():
    assert _normalize_image_entry("http://img/a.png") == ("http://img/a.png", None)


def test_normalize_image_entry_from_dict_with_description():
    entry = {"url": "http://img/b.png", "description": "角色立绘"}
    assert _normalize_image_entry(entry) == ("http://img/b.png", "角色立绘")


def test_normalize_image_entry_rejects_blank_str():
    assert _normalize_image_entry("   ") is None


def test_normalize_image_entry_rejects_dict_without_url():
    assert _normalize_image_entry({"description": "无 url"}) is None


def test_collect_images_dedupes_but_does_not_cap():
    """No cap at this layer -- the final display cap (_MAX_IMAGES) is applied once,
    by research.py::_format_search_text, after merging top_images + all hits' images.
    Capping here too would make research.py's cap ineffective (each source could
    independently contribute up to the cap)."""
    top_level = [f"http://img/{i}.png" for i in range(3)]
    results = [
        {"images": [f"http://img/{i}.png" for i in range(3, 7)]},
    ]
    out = _collect_images(top_level, results)
    assert len(out) == 7
    urls = [u for u, _ in out]
    assert urls == [f"http://img/{i}.png" for i in range(7)]


def test_collect_images_skips_duplicate_urls():
    top_level = ["http://img/a.png"]
    results = [{"images": ["http://img/a.png", "http://img/b.png"]}]
    out = _collect_images(top_level, results)
    assert [u for u, _ in out] == ["http://img/a.png", "http://img/b.png"]


@pytest.mark.asyncio
async def test_tavily_provider_maps_answer_hits_and_images(monkeypatch):
    from domain.search_provider import TavilySearchProvider

    class _FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key

        async def search(self, query, **kw):
            captured.update(kw)
            return {
                "answer": "七大企业统治",
                "images": ["http://img/top.jpg"],
                "results": [{
                    "url": "http://a",
                    "content": "企业A 内容",
                    "images": [{"url": "http://img/char.png", "description": "主角立绘"}],
                }],
            }

    captured: dict = {}
    monkeypatch.setattr("domain.search_provider.AsyncTavilyClient", _FakeClient)

    provider = TavilySearchProvider(api_key="k", top_k=5)
    result = await provider.search("谁统治")

    assert captured["max_results"] == 5
    assert result.answer == "七大企业统治"
    assert result.hits == [
        __import__("domain.search_provider", fromlist=["SearchHit"]).SearchHit(
            text="企业A 内容", url="http://a", images=[("http://img/char.png", "主角立绘")],
        )
    ]
    assert result.top_images == [("http://img/top.jpg", None)]


@pytest.mark.asyncio
async def test_tavily_provider_clamps_top_k_to_twenty(monkeypatch):
    from domain.search_provider import TavilySearchProvider

    captured: dict = {}

    class _FakeClient:
        def __init__(self, api_key): pass

        async def search(self, query, **kw):
            captured.update(kw)
            return {"answer": None, "results": []}

    monkeypatch.setattr("domain.search_provider.AsyncTavilyClient", _FakeClient)

    provider = TavilySearchProvider(api_key="k", top_k=999)
    await provider.search("x")
    assert captured["max_results"] == 20


@pytest.mark.asyncio
async def test_tavily_provider_answer_none_when_missing(monkeypatch):
    from domain.search_provider import TavilySearchProvider

    class _FakeClient:
        def __init__(self, api_key): pass

        async def search(self, query, **kw):
            return {"results": []}

    monkeypatch.setattr("domain.search_provider.AsyncTavilyClient", _FakeClient)

    provider = TavilySearchProvider(api_key="k", top_k=5)
    result = await provider.search("x")
    assert result.answer is None
    assert result.hits == []


@pytest.mark.asyncio
async def test_baidu_qianfan_provider_maps_references_no_answer_no_images():
    from domain.search_provider import BaiduQianfanSearchProvider

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json_mod.loads(request.content)
        return httpx.Response(200, json={
            "request_id": "r1",
            "references": [
                {"title": "标题A", "url": "http://a", "content": "正文A"},
                {"title": "标题B", "url": "http://b", "content": "正文B"},
            ],
        })

    provider = BaiduQianfanSearchProvider(
        api_key="qk", top_k=5, transport=httpx.MockTransport(handler),
    )
    result = await provider.search("谁统治")

    assert captured["url"] == "https://qianfan.baidubce.com/v2/ai_search/web_search"
    assert captured["headers"]["authorization"] == "Bearer qk"
    assert captured["body"]["messages"] == [{"role": "user", "content": "谁统治"}]
    assert captured["body"]["resource_type_filter"] == [{"type": "web", "top_k": 5}]

    assert result.answer is None
    assert result.top_images == []
    assert result.hits == [
        SearchHitFor("标题A\n正文A", "http://a"),
        SearchHitFor("标题B\n正文B", "http://b"),
    ]


def SearchHitFor(text: str, url: str):
    from domain.search_provider import SearchHit
    return SearchHit(text=text, url=url)


@pytest.mark.asyncio
async def test_baidu_qianfan_provider_skips_non_dict_references():
    from domain.search_provider import BaiduQianfanSearchProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"references": ["not-a-dict", {"url": "http://ok", "content": "c"}]})

    provider = BaiduQianfanSearchProvider(api_key="qk", top_k=5, transport=httpx.MockTransport(handler))
    result = await provider.search("x")
    assert len(result.hits) == 1
    assert result.hits[0].url == "http://ok"


@pytest.mark.asyncio
async def test_baidu_qianfan_provider_clamps_top_k_to_fifty():
    from domain.search_provider import BaiduQianfanSearchProvider

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json_mod.loads(request.content)
        return httpx.Response(200, json={"references": []})

    provider = BaiduQianfanSearchProvider(api_key="qk", top_k=999, transport=httpx.MockTransport(handler))
    await provider.search("x")
    assert captured["body"]["resource_type_filter"] == [{"type": "web", "top_k": 50}]


@pytest.mark.asyncio
async def test_baidu_qianfan_provider_raises_on_http_error():
    from domain.search_provider import BaiduQianfanSearchProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"code": "InternalError", "message": "boom"})

    provider = BaiduQianfanSearchProvider(api_key="qk", top_k=5, transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await provider.search("x")


def test_build_search_provider_defaults_to_tavily():
    from domain.search_provider import TavilySearchProvider, build_search_provider

    cfg = {"api": {"tavily_api_key": "tk"}}
    provider = build_search_provider(cfg)
    assert isinstance(provider, TavilySearchProvider)


def test_build_search_provider_missing_tavily_key_raises():
    from domain.search_provider import build_search_provider

    cfg = {"api": {"search_provider": "tavily"}}
    with pytest.raises(ValueError, match="Tavily"):
        build_search_provider(cfg)


def test_build_search_provider_selects_baidu_qianfan():
    from domain.search_provider import BaiduQianfanSearchProvider, build_search_provider

    cfg = {"api": {"search_provider": "baidu_qianfan", "qianfan_api_key": "qk"}}
    provider = build_search_provider(cfg)
    assert isinstance(provider, BaiduQianfanSearchProvider)


def test_build_search_provider_missing_qianfan_key_raises():
    from domain.search_provider import build_search_provider

    cfg = {"api": {"search_provider": "baidu_qianfan"}}
    with pytest.raises(ValueError, match="千帆"):
        build_search_provider(cfg)


def test_build_search_provider_passes_configured_top_k():
    from domain.search_provider import build_search_provider

    cfg = {"api": {"tavily_api_key": "tk", "search_top_k": 3}}
    provider = build_search_provider(cfg)
    assert provider._top_k == 3


def test_build_search_provider_defaults_top_k_to_five_when_missing():
    from domain.search_provider import build_search_provider

    cfg = {"api": {"tavily_api_key": "tk"}}
    provider = build_search_provider(cfg)
    assert provider._top_k == 5


@pytest.mark.asyncio
async def test_chronos_cloud_search_provider_raises_when_not_logged_in(monkeypatch):
    from domain.search_provider import ChronosCloudSearchProvider

    monkeypatch.setattr("api.services.cloud_auth.is_logged_in", lambda: False)
    provider = ChronosCloudSearchProvider(base_url="https://search.example.com")

    with pytest.raises(ValueError, match="请先登录"):
        await provider.search("some topic")


@pytest.mark.asyncio
async def test_chronos_cloud_search_provider_maps_response_to_search_result(monkeypatch):
    from domain.search_provider import ChronosCloudSearchProvider

    monkeypatch.setattr("api.services.cloud_auth.is_logged_in", lambda: True)
    monkeypatch.setattr("api.services.cloud_auth.get_access_token", lambda: "the-access-token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer the-access-token"
        return httpx.Response(200, json={
            "answer": "cloud answer",
            "hits": [{"text": "hit text", "url": "http://x", "images": [{"url": "http://img", "description": None}]}],
            "top_images": [],
        })

    transport = httpx.MockTransport(handler)
    provider = ChronosCloudSearchProvider(base_url="https://search.example.com", transport=transport)

    result = await provider.search("some topic")

    assert result.answer == "cloud answer"
    assert result.hits[0].text == "hit text"
    assert result.hits[0].images == [("http://img", None)]


def test_build_search_provider_raises_for_chronos_cloud_when_base_url_missing():
    from domain.search_provider import build_search_provider

    cfg = {"api": {"search_provider": "chronos_cloud"}}

    with pytest.raises(ValueError, match="cloud_search_base_url"):
        build_search_provider(cfg)
