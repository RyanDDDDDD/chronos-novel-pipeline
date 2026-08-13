"""StateCoreHook now declares and parses self_ref (self-proclaimed pool list), LLM deduces the output."""
from __future__ import annotations


def _hook():
    from engine.archive.hook_loader import DELTA_HOOKS

    return next(h for h in DELTA_HOOKS if h.name == "state")


def test_self_ref_in_fields():
    assert "self_ref" in _hook().fields


def test_parse_self_ref_dict_passthrough():
    h = _hook()
    out = h.parse("self_ref", {"_default": ["我"], "甲": ["奴婢", ""]}, None)
    assert out == {"_default": ["我"], "甲": ["奴婢"]}  #Go empty


def test_parse_self_ref_legacy_list_to_default():
    #Old single pool list → _default baseline (fault-tolerant compilation)
    h = _hook()
    assert h.parse("self_ref", ["我", "奴家"], None) == {"_default": ["我", "奴家"]}


def test_parse_self_ref_legacy_scalar_to_default():
    h = _hook()
    assert h.parse("self_ref", "我", None) == {"_default": ["我"]}


def test_parse_self_ref_empty():
    h = _hook()
    assert h.parse("self_ref", None, None) == {}


def test_parse_address_ref_dict():
    h = _hook()
    out = h.parse("address_ref", {"甲": ["主人"], "乙": "姐姐"}, None)
    assert out == {"甲": ["主人"], "乙": ["姐姐"]}  #The values ​​are unified into list[str]


def test_parse_address_ref_null_preserved_for_fold():
    #null (delete signal) must be retained and consumed by deep_remove_none of fold
    h = _hook()
    assert h.parse("address_ref", {"甲": None}, None) == {"甲": None}


def test_parse_address_ref_legacy_scalar_dropped():
    #Old bare str has no target → discard (old files need to be regenerated)
    h = _hook()
    assert h.parse("address_ref", "主人", None) == {}


def _fresh_state_core_hook():
    """Create a new StateCoreHook (__init__ reads world_bible; DELTA_HOOKS singleton is not suitable for monkeypatch testing)."""
    import importlib.util
    import os

    from utils.paths import ARCHIVE_HOOKS_DIR

    path = os.path.join(ARCHIVE_HOOKS_DIR, "state_core", "hook.py")
    spec = importlib.util.spec_from_file_location("_tst_state_core_hook", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.StateCoreHook()


def test_tone_grounding_present(monkeypatch, tmp_path):
    import json

    p = tmp_path / "wb.json"
    p.write_text(
        json.dumps({
            "tone": "测试基调X",
            "core_themes": [{"name": "主题A", "desc": "d"}, {"name": "主题B", "desc": "d"}],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr("utils.paths.world_bible_path", lambda: str(p))
    g = _fresh_state_core_hook()._tone_grounding()
    assert "测试基调X" in g and "主题A" in g and "本作基调" in g


def test_tone_grounding_empty_when_no_world_bible(monkeypatch, tmp_path):
    monkeypatch.setattr("utils.paths.world_bible_path", lambda: str(tmp_path / "missing.json"))
    assert _fresh_state_core_hook()._tone_grounding() == ""


def test_prompts_mention_self_ref():
    from pathlib import Path

    from utils.paths import ARCHIVE_HOOKS_DIR

    base = Path(ARCHIVE_HOOKS_DIR) / "state_core"
    sb = (base / "state_builder.md").read_text(encoding="utf-8")
    cs = (base / "cold_start.md").read_text(encoding="utf-8")
    assert "self_ref" in sb and "推演" in sb
    assert "self_ref" in cs
    #per-target contract: address_ref per object, self_ref with _default baseline key
    assert "_default" in sb and "_default" in cs
    assert "对象名" in sb
    #The subject matter is gender-neutral: no specific reference to "male protagonist" is allowed.
    assert "男主" not in sb and "男主" not in cs
