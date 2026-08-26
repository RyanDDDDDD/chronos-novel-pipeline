"""ConfigManager - global configuration singleton, all configuration access is unified through this module."""
from __future__ import annotations

import json
import os
import sys

from utils.cache import LazyCache
from utils.paths import CONFIG_PATH as _CONFIG_PATH

_DEFAULTS: dict = {
    "llm": {
        "cloud_model_id": "claude-opus-4-7",
        # Optional dedicated model for style_guard sentence rewrites; empty = cloud default.
        "style_guard_model_ref": "",
        "custom_cloud": {
            "model": "", "base_url": "", "provider": "openai_compatible",
            "client_kwargs": {},
        },
        "custom_models": [],
        "local_base_url": "http://localhost:1234/v1",
        "local_model": "local-model",
        "max_tokens": 8000,
    },
    "api": {
        "model_api_keys": {},
        "tavily_api_key": "",
        "qianfan_api_key": "",
        "search_provider": "tavily",
        "search_top_k": 5,
        "cloud_auth_base_url": "",
        "cloud_search_base_url": "",
    },
    "server": {
        "engine_port": 8776,
    },
    "novel_import": {
        "chunk_size": 10000,
        "concurrency": None,
        "warn_threshold_chars": 100000,
        "compaction_interval": 5,
        "image_batch_size": 10,
        "image_batch_overlap": 2,
    },
    "novels": {
        "trash_retention_days": 30,
    },
}

_config_cache: LazyCache[dict] = LazyCache(lambda: _load(_CONFIG_PATH))


def get_config(path: str = _CONFIG_PATH) -> dict:
    """Returns the global configuration (loaded from disk when called for the first time, and
    returned directly to the cache in subsequent calls -- `path` only takes effect on that
    first call, exactly like before this migration)."""
    return _config_cache.get(lambda: _load(path))


def reload_config(path: str = _CONFIG_PATH) -> dict:
    """
Force configuration reload from disk (used for cache flushing and environment variable injection after writing back)."""
    _config_cache.invalidate()
    return _config_cache.get(lambda: _load(path))


def save_config(raw: dict, path: str = _CONFIG_PATH) -> dict:
    """Write the raw configuration to disk and reload, returning the effective configuration after merging defaults.

    Note: What is written to the disk is raw (user input), and what is read during runtime is the merged result of defaults+raw (_load)."""

    import tempfile

    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = json.dumps(raw, ensure_ascii=False, indent=2)
    parent = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return reload_config(path)


_LEGACY_CLIENT_KWARGS = {
    "extra_body": {"thinking": {"type": "enabled"}}, "reasoning_effort": "high",
}


def _migrate_legacy_cloud_model(cfg: dict, raw: dict) -> None:
    """One-time in-memory migration for configs written before cloud_model_id/custom_cloud
    existed. Mutates cfg in place; nothing is written back to disk here -- the next
    save_config() call naturally persists the new shape (same self-healing pattern as
    author_loop_skill_prefs.py's dead-key cleanup)."""
    raw_llm_val = raw.get("llm")
    raw_llm: dict = raw_llm_val if isinstance(raw_llm_val, dict) else {}
    cfg["llm"].pop("cloud_model", None)
    cfg["llm"].pop("cloud_base_url", None)
    if "cloud_model_id" in raw_llm:
        return  # already migrated

    from domain.model_catalog import catalog_entry

    old_model = raw_llm.get("cloud_model", "")
    old_base_url = raw_llm.get("cloud_base_url", "")
    # No legacy fields at all (e.g. fresh {} / example already on new schema) —
    # keep _DEFAULTS cloud_model_id rather than forcing the custom escape hatch.
    if not old_model and not old_base_url:
        return

    if old_model and catalog_entry(old_model) is not None:
        cfg["llm"]["cloud_model_id"] = old_model
        return

    cfg["llm"]["cloud_model_id"] = "custom"
    custom: dict = {
        "model": old_model,
        "base_url": old_base_url,
        "provider": "openai_compatible" if old_base_url else "anthropic",
        "client_kwargs": dict(_LEGACY_CLIENT_KWARGS) if old_base_url else {},
    }
    cfg["llm"]["custom_cloud"] = custom


def _migrate_legacy_api_keys(cfg: dict, raw: dict) -> None:
    """Seed per-model model_api_keys from legacy global anthropic/cloud key slots."""
    raw_api_val = raw.get("api")
    raw_api: dict = raw_api_val if isinstance(raw_api_val, dict) else {}
    if "model_api_keys" in raw_api:
        return

    from domain.model_catalog import load_model_catalog

    custom = cfg["llm"].get("custom_cloud", {})
    custom_provider = custom.get("provider") or (
        "openai_compatible" if custom.get("base_url") else "anthropic"
    )
    model_api_keys = cfg["api"]["model_api_keys"]

    legacy_anthropic = raw_api.get("anthropic_api_key", "")
    if legacy_anthropic:
        for entry in load_model_catalog():
            if entry.get("provider") == "anthropic":
                model_api_keys[entry["id"]] = legacy_anthropic
        if custom_provider == "anthropic":
            model_api_keys["custom"] = legacy_anthropic

    legacy_cloud = raw_api.get("cloud_api_key", "")
    if legacy_cloud:
        for entry in load_model_catalog():
            if entry.get("provider") == "openai_compatible":
                model_api_keys[entry["id"]] = legacy_cloud
        if custom_provider == "openai_compatible":
            model_api_keys["custom"] = legacy_cloud

    cfg["api"].pop("anthropic_api_key", None)
    cfg["api"].pop("cloud_api_key", None)


def _migrate_custom_cloud_to_list(cfg: dict, raw: dict) -> None:
    """One-time in-memory migration: llm.custom_cloud (single slot) -> llm.custom_models
    (list). Mirrors _migrate_legacy_cloud_model's in-memory-only, self-heals-on-next-
    save_config pattern. Must run after _migrate_legacy_cloud_model/_migrate_legacy_api_keys
    so it sees their fully-resolved custom_cloud + model_api_keys output."""
    raw_llm_val = raw.get("llm")
    raw_llm: dict = raw_llm_val if isinstance(raw_llm_val, dict) else {}
    if "custom_models" in raw_llm:
        return  # already migrated

    custom = cfg["llm"].pop("custom_cloud", None)
    models = cfg["llm"].get("custom_models")
    cfg["llm"]["custom_models"] = list(models) if isinstance(models, list) else []
    if not isinstance(custom, dict) or not custom.get("model") or not custom.get("base_url"):
        return

    entry_id = "custom"  # fixed id, carries forward any existing cloud_model_id == "custom" reference
    cfg["llm"]["custom_models"].append({
        "id": entry_id, "label": "自定义（迁移）",
        "provider": custom.get("provider") or "openai_compatible",
        "base_url": custom["base_url"], "model": custom["model"],
        "api_key": cfg["api"].get("model_api_keys", {}).get("custom", ""),
        "client_kwargs": custom.get("client_kwargs", {}),
    })
    if cfg["llm"].get("cloud_model_id") == "custom":
        cfg["llm"]["cloud_model_id"] = entry_id


def _load(path: str) -> dict:
    if not os.path.exists(path):
        print(
            f"[config] 找不到 {path}，请复制 config/config.example.json 并填写参数。",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    cfg = _deep_merge(_DEFAULTS, raw)

    _migrate_legacy_cloud_model(cfg, raw)
    _migrate_legacy_api_keys(cfg, raw)
    _migrate_custom_cloud_to_list(cfg, raw)

    presets_path = os.path.join(os.path.dirname(path), "local_model_presets.json")
    if os.path.exists(presets_path):
        with open(presets_path, "r", encoding="utf-8") as f:
            presets_data = json.load(f)
        preset_name = cfg["llm"].get("local_preset", "A")
        preset = presets_data.get("presets", {}).get(preset_name, {})
        for key in ("temperature", "top_p", "top_k", "repetition_penalty", "repeat_last_n", "min_p"):
            if key in preset:
                cfg["llm"][key] = preset[key]

    return cfg


def _deep_merge(base: dict, override: dict) -> dict:
    # Deep-copy nested dicts from base so later in-place mutation of cfg
    # (migration, preset injection) cannot poison the module-level _DEFAULTS.
    result = {
        k: (_deep_merge(v, {}) if isinstance(v, dict) else v)
        for k, v in base.items()
    }
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def server_port() -> int:
    """
Backend WebUI listening port (consistent with main.py --port default).
Not user-configurable via config.json -- _find_free_port() already probes past
conflicts at startup, so a static override would just fight that. CHRONOS_SERVER_PORT
remains the only way to pin it (e.g. scripted/CI launches)."""
    env = os.environ.get("CHRONOS_SERVER_PORT")
    if env:
        return int(env)
    return 8775


def engine_port(cfg: dict | None = None) -> int:
    """引擎进程内网端口（双进程模式；仅本机）。CHRONOS_ENGINE_PORT 可覆盖。"""
    env = os.environ.get("CHRONOS_ENGINE_PORT")
    if env:
        return int(env)
    c = cfg if cfg is not None else get_config()
    return int(c.get("server", {}).get("engine_port", 8776))


def vite_dev_port() -> int:
    """Vite development server port (--dev mode). Not user-configurable via
config.json, same rationale as server_port()."""
    return 5173


def trash_retention_days(cfg: dict | None = None) -> int:
    """Days to keep deleted novels under novels/.trash/ before startup purge; 0 disables purge."""
    c = cfg if cfg is not None else get_config()
    raw = c.get("novels", {}).get("trash_retention_days", 30)
    try:
        days = int(raw)
    except (TypeError, ValueError):
        days = 30
    return max(0, days)


def cors_allow_origins() -> list[str]:
    """
CORS allowed origins: localhost/127.0.0.1 × backend port + Vite port."""
    hub = server_port()
    vite = vite_dev_port()
    origins: list[str] = []
    for host in ("localhost", "127.0.0.1"):
        origins.append(f"http://{host}:{hub}")
        origins.append(f"http://{host}:{vite}")
    return origins
