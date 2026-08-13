"""model_catalog.py: load/lookup for the curated cloud-model catalog (config/model_catalog.json)."""
import json


def test_load_model_catalog_returns_seed_entries():
    from domain.model_catalog import load_model_catalog

    entries = load_model_catalog()
    ids = {e["id"] for e in entries}
    assert "claude-opus-4-7" in ids
    assert "deepseek-v4-flash" in ids
    assert "qwen3.7-flash" in ids
    assert "gemini-3-flash-preview" in ids


def test_catalog_entry_found():
    from domain.model_catalog import catalog_entry

    entry = catalog_entry("deepseek-v4-flash")
    assert entry is not None
    assert entry["provider"] == "openai_compatible"
    assert entry["base_url"] == "https://api.deepseek.com/v1"
    assert entry["model_profile"] == "deepseek"


def test_catalog_entry_not_found_returns_none():
    from domain.model_catalog import catalog_entry

    assert catalog_entry("not-a-real-model") is None


def test_catalog_entry_gemini_found():
    from domain.model_catalog import catalog_entry

    entry = catalog_entry("gemini-3-flash-preview")
    assert entry is not None
    assert entry["provider"] == "openai_compatible"
    assert entry["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai/"


def test_load_model_catalog_missing_file_returns_empty(monkeypatch, tmp_path):
    import domain.model_catalog as m

    monkeypatch.setattr(m, "MODEL_CATALOG_PATH", str(tmp_path / "nope.json"))
    assert m.load_model_catalog() == []


def test_load_model_catalog_bad_json_returns_empty(monkeypatch, tmp_path):
    import domain.model_catalog as m

    p = tmp_path / "bad.json"
    p.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(m, "MODEL_CATALOG_PATH", str(p))
    assert m.load_model_catalog() == []


def test_load_model_catalog_non_list_cloud_models_returns_empty(monkeypatch, tmp_path):
    import domain.model_catalog as m

    p = tmp_path / "wrong_shape.json"
    p.write_text(json.dumps({"cloud_models": "not-a-list"}), encoding="utf-8")
    monkeypatch.setattr(m, "MODEL_CATALOG_PATH", str(p))
    assert m.load_model_catalog() == []


def test_catalog_entry_qwen_found():
    from domain.model_catalog import catalog_entry

    entry = catalog_entry("qwen3.7-flash")
    assert entry is not None
    assert entry["provider"] == "openai_compatible"
    assert entry["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert entry["model_profile"] == "qwen"


def test_load_custom_models_returns_configured_list(monkeypatch):
    from domain.model_catalog import load_custom_models

    monkeypatch.setattr(
        "utils.config.get_config",
        lambda: {"llm": {"custom_models": [{"id": "a", "label": "A"}]}},
    )
    assert load_custom_models() == [{"id": "a", "label": "A"}]


def test_load_custom_models_missing_key_returns_empty(monkeypatch):
    from domain.model_catalog import load_custom_models

    monkeypatch.setattr("utils.config.get_config", lambda: {"llm": {}})
    assert load_custom_models() == []


def test_load_custom_models_bad_shape_returns_empty(monkeypatch):
    from domain.model_catalog import load_custom_models

    monkeypatch.setattr("utils.config.get_config", lambda: {"llm": {"custom_models": "not-a-list"}})
    assert load_custom_models() == []


def test_load_custom_models_drops_entries_without_string_id(monkeypatch):
    from domain.model_catalog import load_custom_models

    monkeypatch.setattr(
        "utils.config.get_config",
        lambda: {"llm": {"custom_models": [{"id": "a"}, {"label": "no id"}, "not-a-dict"]}},
    )
    assert load_custom_models() == [{"id": "a"}]


def test_resolve_model_entry_catalog_hit():
    from domain.model_catalog import resolve_model_entry

    entry = resolve_model_entry("deepseek-v4-flash")
    assert entry is not None
    assert entry["provider"] == "openai_compatible"


def test_resolve_model_entry_custom_hit_via_explicit_param():
    from domain.model_catalog import resolve_model_entry

    entry = resolve_model_entry("my-custom-id", custom_models=[{"id": "my-custom-id", "label": "X"}])
    assert entry == {"id": "my-custom-id", "label": "X"}


def test_resolve_model_entry_custom_hit_via_config_default(monkeypatch):
    from domain.model_catalog import resolve_model_entry

    monkeypatch.setattr(
        "utils.config.get_config",
        lambda: {"llm": {"custom_models": [{"id": "my-custom-id", "label": "X"}]}},
    )
    assert resolve_model_entry("my-custom-id") == {"id": "my-custom-id", "label": "X"}


def test_resolve_model_entry_not_found_returns_none(monkeypatch):
    from domain.model_catalog import resolve_model_entry

    monkeypatch.setattr("utils.config.get_config", lambda: {"llm": {"custom_models": []}})
    assert resolve_model_entry("nope") is None
