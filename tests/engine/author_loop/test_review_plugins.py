import importlib.util
import sys
from pathlib import Path

from engine.author_loop.review.review_hook import ReviewContext

ROOT = Path(__file__).resolve().parents[3]  #repository root


def _load(name):
    p = ROOT / "hooks" / "review" / name / "hook.py"
    d = str(p.parent)
    if d not in sys.path:
        sys.path.insert(0, d)
    spec = importlib.util.spec_from_file_location(f"_rv_{name}", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"_rv_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod.Hook()


def _ctx(prev="前一拍正文"):
    return ReviewContext("意图", "草稿原文", "定稿正文", prev, "指示")


def test_coherence_attrs_and_prompt():
    h = _load("coherence")
    assert h.name == "coherence" and h.weight == 0.4 and h.floor == 6
    assert h.consumes == ["prev_beat_text", "refined"]
    sys_p, user_p = h.build_prompt(_ctx())
    assert "前一拍正文" in user_p and "定稿正文" in user_p
