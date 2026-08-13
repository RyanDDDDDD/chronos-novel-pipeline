import importlib.util
from pathlib import Path

_HOOK = Path(__file__).parents[3] / "hooks" / "archive" / "action" / "hook.py"


def _load():
    spec = importlib.util.spec_from_file_location("_action_hook", _HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_action_hook_declares_field_and_replace_merge():
    mod = _load()
    hook = mod.ActionHook()
    assert hook.fields == ["action"]
    assert hook.merge == {"action": "replace"}


def test_action_hook_parse_returns_text():
    mod = _load()
    hook = mod.ActionHook()
    assert hook.parse("action", "她跪坐在浴盆边缘", ctx=None) == "她跪坐在浴盆边缘"
    assert hook.parse("action", None, ctx=None) == ""


def test_action_prompt_fragment_nonempty():
    mod = _load()
    hook = mod.ActionHook()

    class _Ctx:  # minimal stand-in
        pass

    assert "动作" in hook.prompt_fragment(_Ctx())
