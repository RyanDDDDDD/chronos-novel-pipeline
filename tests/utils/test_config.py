from __future__ import annotations

import json


def test_default_config_includes_novel_import_group():
    from utils.config import get_config

    cfg = get_config()
    assert cfg["novel_import"] == {
        "chunk_size": 10000,
        "concurrency": None,
        "warn_threshold_chars": 100000,
        "compaction_interval": 5,
        "image_batch_size": 10,
        "image_batch_overlap": 2,
    }


def test_default_config_includes_novels_trash_retention(tmp_path):
    from utils import config as config_mod

    p = tmp_path / "config.json"
    p.write_text("{}", encoding="utf-8")
    cfg = config_mod._load(str(p))
    assert cfg["novels"]["trash_retention_days"] == 30


def test_trash_retention_days_clamps_invalid_and_negative(tmp_path, monkeypatch):
    from utils import config as config_mod

    p = tmp_path / "config.json"
    p.write_text(json.dumps({"novels": {"trash_retention_days": -5}}), encoding="utf-8")
    monkeypatch.setattr(config_mod, "_config_cache", config_mod.LazyCache(lambda: config_mod._load(config_mod._CONFIG_PATH)))
    assert config_mod.trash_retention_days(config_mod.get_config(str(p))) == 0

    p.write_text(json.dumps({"novels": {"trash_retention_days": "nope"}}), encoding="utf-8")
    monkeypatch.setattr(config_mod, "_config_cache", config_mod.LazyCache(lambda: config_mod._load(config_mod._CONFIG_PATH)))
    assert config_mod.trash_retention_days(config_mod.get_config(str(p))) == 30


def test_load_empty_config_keeps_default_cloud_model_id(tmp_path):
    """Regression: empty raw must not force cloud_model_id=custom or mutate _DEFAULTS."""
    from utils import config as config_mod

    p = tmp_path / "config.json"
    p.write_text("{}", encoding="utf-8")
    cfg = config_mod._load(str(p))
    assert cfg["llm"]["cloud_model_id"] == "claude-opus-4-7"
    assert config_mod._DEFAULTS["llm"]["cloud_model_id"] == "claude-opus-4-7"
    assert config_mod._DEFAULTS["llm"]["custom_cloud"]["provider"] == "openai_compatible"


def test_load_migrates_old_cloud_model_matching_catalog_entry(tmp_path, monkeypatch):
    from utils.config import _load

    p = tmp_path / "config.json"
    p.write_text(json.dumps({"llm": {"cloud_model": "deepseek-v4-flash", "cloud_base_url": "https://api.deepseek.com/v1"}}), encoding="utf-8")
    cfg = _load(str(p))
    assert cfg["llm"]["cloud_model_id"] == "deepseek-v4-flash"
    assert "cloud_model" not in cfg["llm"]
    assert "cloud_base_url" not in cfg["llm"]


def test_load_migrates_unknown_cloud_model_to_custom(tmp_path, monkeypatch):
    from utils.config import _load

    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "llm": {"cloud_model": "my-private-model", "cloud_base_url": "https://my-proxy.example.com/v1"},
    }), encoding="utf-8")
    cfg = _load(str(p))
    assert cfg["llm"]["cloud_model_id"] == "custom"
    assert "custom_cloud" not in cfg["llm"]
    custom = cfg["llm"]["custom_models"][0]
    assert custom["id"] == "custom"
    assert custom["model"] == "my-private-model"
    assert custom["base_url"] == "https://my-proxy.example.com/v1"
    assert custom["client_kwargs"] == {
        "extra_body": {"thinking": {"type": "enabled"}}, "reasoning_effort": "high",
    }


def test_load_leaves_already_migrated_config_untouched(tmp_path, monkeypatch):
    from utils.config import _load

    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "llm": {"cloud_model_id": "claude-opus-4-7"},
    }), encoding="utf-8")
    cfg = _load(str(p))
    assert cfg["llm"]["cloud_model_id"] == "claude-opus-4-7"
    assert "custom_cloud" not in cfg["llm"]
    assert cfg["llm"]["custom_models"] == []


def test_migrates_legacy_anthropic_key_to_all_anthropic_catalog_entries(tmp_path):
    from utils.config import _load

    p = tmp_path / "config.json"
    p.write_text(json.dumps({"api": {"anthropic_api_key": "sk-ant-legacy"}}), encoding="utf-8")
    cfg = _load(str(p))
    assert cfg["api"]["model_api_keys"]["claude-opus-4-7"] == "sk-ant-legacy"
    assert "anthropic_api_key" not in cfg["api"]


def test_migrates_legacy_cloud_key_to_all_openai_compatible_catalog_entries(tmp_path):
    from utils.config import _load

    p = tmp_path / "config.json"
    p.write_text(json.dumps({"api": {"cloud_api_key": "sk-cloud-legacy"}}), encoding="utf-8")
    cfg = _load(str(p))
    assert cfg["api"]["model_api_keys"]["deepseek-v4-flash"] == "sk-cloud-legacy"
    assert cfg["api"]["model_api_keys"]["qwen3.7-flash"] == "sk-cloud-legacy"
    assert "cloud_api_key" not in cfg["api"]


def test_migrates_legacy_cloud_key_into_custom_slot_when_custom_defaults_openai_compatible(tmp_path):
    from utils.config import _load

    p = tmp_path / "config.json"
    p.write_text(json.dumps({"api": {"cloud_api_key": "sk-cloud-legacy"}}), encoding="utf-8")
    cfg = _load(str(p))
    # custom_cloud.provider defaults to "openai_compatible" per _DEFAULTS
    assert cfg["api"]["model_api_keys"]["custom"] == "sk-cloud-legacy"


def test_migrates_legacy_anthropic_key_into_custom_slot_when_custom_provider_is_anthropic(tmp_path):
    from utils.config import _load

    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "llm": {"custom_cloud": {"provider": "anthropic"}},
        "api": {"anthropic_api_key": "sk-ant-legacy"},
    }), encoding="utf-8")
    cfg = _load(str(p))
    assert cfg["api"]["model_api_keys"]["custom"] == "sk-ant-legacy"


def test_already_migrated_model_api_keys_are_not_overwritten(tmp_path):
    from utils.config import _load

    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "api": {
            "anthropic_api_key": "sk-ant-legacy-should-be-ignored",
            "model_api_keys": {"claude-opus-4-7": "sk-ant-user-edited"},
        },
    }), encoding="utf-8")
    cfg = _load(str(p))
    assert cfg["api"]["model_api_keys"]["claude-opus-4-7"] == "sk-ant-user-edited"


def test_default_config_has_empty_model_api_keys_dict(tmp_path, monkeypatch):
    from utils import config as config_mod

    p = tmp_path / "config.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config_mod, "_config_cache", config_mod.LazyCache(lambda: config_mod._load(config_mod._CONFIG_PATH)))
    cfg = config_mod.get_config(str(p))
    assert cfg["api"]["model_api_keys"] == {}


def test_anthropic_env_var_is_no_longer_injected(tmp_path, monkeypatch):
    import os

    from utils.config import _load

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"api": {"anthropic_api_key": "sk-ant-legacy"}}), encoding="utf-8")
    _load(str(p))
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_default_config_includes_search_provider_fields(tmp_path):
    from utils import config as config_mod

    p = tmp_path / "config.json"
    p.write_text("{}", encoding="utf-8")
    cfg = config_mod._load(str(p))
    assert cfg["api"]["qianfan_api_key"] == ""
    assert cfg["api"]["search_provider"] == "tavily"
    assert cfg["api"]["search_top_k"] == 5


def test_migrates_non_empty_custom_cloud_into_custom_models_list(tmp_path):
    from utils.config import _load

    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "llm": {
            "cloud_model_id": "custom",
            "custom_cloud": {
                "model": "my-model", "base_url": "https://proxy.example.com/v1",
                "provider": "openai_compatible", "client_kwargs": {},
            },
        },
        "api": {"model_api_keys": {"custom": "sk-legacy"}},
    }), encoding="utf-8")
    cfg = _load(str(p))
    assert "custom_cloud" not in cfg["llm"]
    assert cfg["llm"]["custom_models"] == [{
        "id": "custom", "label": "自定义（迁移）", "provider": "openai_compatible",
        "base_url": "https://proxy.example.com/v1", "model": "my-model",
        "api_key": "sk-legacy", "client_kwargs": {},
    }]
    assert cfg["llm"]["cloud_model_id"] == "custom"


def test_migrates_empty_custom_cloud_to_empty_list_without_entry(tmp_path):
    from utils.config import _load

    p = tmp_path / "config.json"
    p.write_text(json.dumps({"llm": {"cloud_model_id": "claude-opus-4-7"}}), encoding="utf-8")
    cfg = _load(str(p))
    assert cfg["llm"]["custom_models"] == []


def test_custom_models_migration_is_idempotent_when_already_present(tmp_path):
    from utils.config import _load

    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "llm": {
            "cloud_model_id": "abc123",
            "custom_models": [{
                "id": "abc123", "label": "手动加的", "provider": "openai_compatible",
                "base_url": "https://x.example.com/v1", "model": "m", "api_key": "k",
                "client_kwargs": {},
            }],
        },
    }), encoding="utf-8")
    cfg = _load(str(p))
    assert cfg["llm"]["custom_models"] == [{
        "id": "abc123", "label": "手动加的", "provider": "openai_compatible",
        "base_url": "https://x.example.com/v1", "model": "m", "api_key": "k", "client_kwargs": {},
    }]


def test_default_config_search_ping_enabled_defaults_false(tmp_path):
    from utils import config as config_mod

    p = tmp_path / "config.json"
    p.write_text("{}", encoding="utf-8")
    cfg = config_mod._load(str(p))
    assert cfg["api"]["search_ping_enabled"] is False


def test_get_config_ignores_path_on_subsequent_calls(tmp_path, monkeypatch):
    """Regression: once _config is loaded, later get_config(path) calls with a DIFFERENT
    path are silently ignored and the first-loaded value keeps winning. This is a
    pre-existing quirk (tests elsewhere work around it via
    monkeypatch.setattr(config_mod, "_config", None)) -- not something this migration
    fixes, just something it must not accidentally change."""
    from utils import config as config_mod

    monkeypatch.setattr(config_mod, "_config_cache", config_mod.LazyCache(lambda: config_mod._load(config_mod._CONFIG_PATH)))

    p1 = tmp_path / "config1.json"
    p1.write_text('{"novels": {"trash_retention_days": 1}}', encoding="utf-8")
    p2 = tmp_path / "config2.json"
    p2.write_text('{"novels": {"trash_retention_days": 2}}', encoding="utf-8")

    first = config_mod.get_config(str(p1))
    second = config_mod.get_config(str(p2))

    assert first["novels"]["trash_retention_days"] == 1
    assert second["novels"]["trash_retention_days"] == 1  # still p1's value, p2 ignored
