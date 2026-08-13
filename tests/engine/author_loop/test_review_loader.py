from pathlib import Path

from engine.author_loop.review.review_loader import discover_review_hooks


def _write_hook(d: Path, name: str, body: str) -> None:
    sub = d / name
    sub.mkdir(parents=True)
    (sub / "hook.py").write_text(body, encoding="utf-8")


_GOOD = '''
from engine.author_loop.review.review_hook import ReviewHook, ReviewScore, ReviewContext


class Hook(ReviewHook):
    name = "good"
    display_name = "好判官"
    weight = 0.5
    floor = 6
    consumes = ["refined"]

    def build_prompt(self, ctx):
        return ("sys", "user")

    def parse(self, raw):
        return ReviewScore(score=9, feedback="")
'''


def test_discover_finds_valid_hook(tmp_path):
    _write_hook(tmp_path, "good", _GOOD)
    hooks = discover_review_hooks(tmp_path)
    assert [h.name for h in hooks] == ["good"]
    assert hooks[0].weight == 0.5 and hooks[0].floor == 6


def test_discover_skips_broken_hook(tmp_path):
    _write_hook(tmp_path, "good", _GOOD)
    _write_hook(tmp_path, "broken", "this is not valid python :::")
    hooks = discover_review_hooks(tmp_path)
    assert [h.name for h in hooks] == ["good"]  #Skip the bad ones and don’t throw them away


def test_discover_missing_dir_returns_empty(tmp_path):
    assert discover_review_hooks(tmp_path / "nope") == []


def test_discover_stable_sort_by_dirname(tmp_path):
    _write_hook(tmp_path, "b_hook", _GOOD.replace('name = "good"', 'name = "b"'))
    _write_hook(tmp_path, "a_hook", _GOOD.replace('name = "good"', 'name = "a"'))
    hooks = discover_review_hooks(tmp_path)
    assert [h.name for h in hooks] == ["a", "b"]  #By directory name a_hook < b_hook
