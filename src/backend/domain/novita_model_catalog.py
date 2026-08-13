"""Process-in-memory cache of Novita's checkpoint model catalog. Cleared on every process
restart by design (a fresh pull each boot, not a persisted/TTL cache) -- refreshed via
three triggers, all async via SCHEDULER: startup warmup, image_gen api_key save, and
frontend search-miss. See api/hub.py::register_startup_warmup, routes.py's
PUT /api/config, and POST /api/image-gen/novita-models/refresh.

Alongside the flat sd_name list (used by the frontend's ModelRadioList, which only ever
takes string[]), also caches each checkpoint's base_model string where Novita reports one
-- consumed once, at checkpoint-selection time, to stamp a custom_models entry (see
routes.py's image-gen endpoints), not re-queried per generation."""
from __future__ import annotations

_CHECKPOINT_LIST_URL = "https://api.novita.ai/v3/model"
_PAGE_LIMIT = 100

_cache: list[str] = []
_base_model_cache: dict[str, str] = {}


def get_cached_novita_models() -> list[str]:
    """Read-only; never triggers a network call."""
    return list(_cache)


def get_cached_base_models() -> dict[str, str]:
    """Read-only; sd_name -> Novita's raw base_model string (only entries where Novita
    actually returned one)."""
    return dict(_base_model_cache)


async def refresh_novita_model_catalog(api_key: str) -> list[str]:
    """Page through Novita's full checkpoint catalog and replace the cache. Raises on
    HTTP failure (caller -- a SCHEDULER job -- logs and gives up this cycle rather than
    retrying, same policy as this codebase's other fire-and-forget warmup jobs)."""
    import httpx

    headers = {"Authorization": f"Bearer {api_key}"}
    sd_names: list[str] = []
    base_models: dict[str, str] = {}
    cursor: str | None = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params: dict[str, str | int] = {"filter.types": "checkpoint", "pagination.limit": _PAGE_LIMIT}
            if cursor:
                params["pagination.cursor"] = cursor
            resp = await client.get(_CHECKPOINT_LIST_URL, headers=headers, params=params)
            resp.raise_for_status()
            body = resp.json()
            page_models = body.get("models", [])
            for m in page_models:
                name = m.get("sd_name")
                if not isinstance(name, str):
                    continue
                sd_names.append(name)
                if isinstance(m.get("base_model"), str):
                    base_models[name] = m["base_model"]
            # Novita's API keeps returning a non-empty next_cursor past the real end of
            # data (reproduced live 2026-08-10) -- an empty page always means "done",
            # regardless of what next_cursor claims, or this loops forever.
            if not page_models:
                break
            cursor = (body.get("pagination") or {}).get("next_cursor")
            if not cursor:
                break

    global _cache, _base_model_cache
    _cache = sd_names
    _base_model_cache = base_models
    return sd_names
