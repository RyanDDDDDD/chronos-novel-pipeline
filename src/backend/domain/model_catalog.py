"""Curated cloud-model catalog (config/model_catalog.json, version-controlled, not user
config): each entry pairs a model id with how to connect to it (provider/base_url/
client_kwargs) and its price, so picking a model from the UI no longer requires typing in
a base_url or a per-million-token price by hand. Local models have no catalog entries --
see api/services (GET /api/llm/local-models) for the live-queried alternative."""
from __future__ import annotations

import json

from utils.paths import MODEL_CATALOG_PATH


def load_model_catalog() -> list[dict]:
    """Missing file / bad JSON / wrong shape -> [] (same tolerance policy as other sidecars
    in this codebase, e.g. author_loop_skill_prefs.py's _read_raw)."""
    try:
        with open(MODEL_CATALOG_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, dict):
        return []
    models = raw.get("cloud_models")
    if not isinstance(models, list):
        return []
    return [m for m in models if isinstance(m, dict) and isinstance(m.get("id"), str)]


def catalog_entry(model_id: str) -> dict | None:
    """Exact-match lookup by id; None when not in the catalog (caller falls back to the
    custom_cloud escape hatch)."""
    for entry in load_model_catalog():
        if entry["id"] == model_id:
            return entry
    return None


def load_custom_models() -> list[dict]:
    """User-managed models (config.llm.custom_models); malformed/missing -> [] (same
    tolerance policy as load_model_catalog)."""
    from utils.config import get_config

    llm_cfg = get_config().get("llm", {})
    models = llm_cfg.get("custom_models") if isinstance(llm_cfg, dict) else None
    if not isinstance(models, list):
        return []
    return [m for m in models if isinstance(m, dict) and isinstance(m.get("id"), str)]


def resolve_model_entry(entry_id: str, custom_models: list[dict] | None = None) -> dict | None:
    """Catalog first, then custom_models. `custom_models` is an explicit override for
    callers that already have an llm_cfg dict in hand (e.g. _make_cloud_llm) so they
    don't need a real config file to test against; omitted, it lazily loads from the
    live config (e.g. bind_node_llm, which doesn't carry llm_cfg)."""
    entry = catalog_entry(entry_id)
    if entry is not None:
        return entry
    models = custom_models if custom_models is not None else load_custom_models()
    for m in models:
        if m.get("id") == entry_id:
            return m
    return None
