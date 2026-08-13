"""Lightweight connectivity checks for the novel-rail status icons: verify the
currently configured cloud LLM and search provider are reachable. The LLM
check never spends completion tokens (list-models / auth-only endpoints);
the search check does spend one real query (see ping_search).

Callers should go through service_ping_status.py so results are stored for
GET /api/health/service-status; do not invoke these directly from routes."""
from __future__ import annotations

import httpx
from domain.model_catalog import resolve_model_entry

_ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"
_ANTHROPIC_VERSION = "2023-06-01"


async def _ping_openai_compatible(base_url: str, api_key: str) -> dict:
    from api.services.openai_models_list import fetch_openai_compatible_models

    result = await fetch_openai_compatible_models(
        base_url, api_key=api_key, connection_error_prefix="LLM 连接失败",
    )
    if result.get("error"):
        return {"ok": False, "error": result["error"]}
    return {"ok": True, "error": None}


async def _ping_anthropic(api_key: str) -> dict:
    if not api_key:
        return {"ok": False, "error": "未配置 API key"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                _ANTHROPIC_MODELS_URL,
                headers={"x-api-key": api_key, "anthropic-version": _ANTHROPIC_VERSION},
            )
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "error": None}


async def ping_llm(cfg: dict) -> dict:
    """Ping whichever cloud model llm.cloud_model_id currently resolves to
    (catalog entry or custom_models entry) -- mirrors llm/factory.py::_make_cloud_llm's
    resolution branch (shared entry-lookup logic, entry's own api_key takes priority
    over the model_api_keys fallback). Local-tab models are out of scope; that tab
    already has its own "重新连接" reachability check in the UI."""
    llm_cfg = cfg.get("llm") or {}
    api_cfg = cfg.get("api") or {}
    model_id = llm_cfg.get("cloud_model_id", "")
    custom_models = llm_cfg.get("custom_models", [])
    if not isinstance(custom_models, list):
        custom_models = []
    entry = resolve_model_entry(model_id, custom_models=custom_models) if model_id else None

    if entry is None:
        return {"ok": False, "error": f"未知的 cloud_model_id: {model_id!r}"}

    base_url = entry.get("base_url", "")
    provider = entry.get("provider") or "openai_compatible"
    api_key = entry.get("api_key") or (api_cfg.get("model_api_keys") or {}).get(entry["id"], "")

    if provider == "anthropic":
        return await _ping_anthropic(api_key)
    return await _ping_openai_compatible(base_url, api_key)


async def ping_search(cfg: dict) -> dict:
    """Real minimal search call via the configured provider -- consumes one
    real quota unit. Bounded by call frequency (novel-rail startup gate +
    explicit config saves), never polled."""
    from domain.search_provider import build_search_provider

    try:
        provider = build_search_provider(cfg)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        await provider.search("连通性检测")
    except Exception as exc:  # noqa: BLE001 -- any provider/network failure just means "not ok"
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "error": None}
