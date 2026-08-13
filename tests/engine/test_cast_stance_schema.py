"""role/gender schema reader test: physique_slots baseline behavior.
私处/生殖器（futa）专属断言见对应内容包自己的测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.setup.cast import stance_schema as ss


@pytest.fixture
def _isolate_baseline_packs(monkeypatch):
    import context.content_packs as cp

    monkeypatch.setattr(cp, "_packs_dir", lambda: Path("/nonexistent"))
    cp.reload_content_packs()
    yield
    # reload_content_packs() only invalidates (LazyCache is lazy, doesn't rebuild here) --
    # the actual rebuild happens on whichever test's _packs() call comes next, by which point
    # monkeypatch has already restored the real _packs_dir. Without this, the process-wide
    # cache stays poisoned with the empty scan this test forced onto it, silently breaking
    # every later test that reads content_packs data for the rest of the session (see
    # docs/TECHNICAL_JOURNEY.md #31).
    cp.reload_content_packs()


def test_physique_slots_baseline_male(_isolate_baseline_packs):
    assert ss.physique_slots("male") == {"体型", "肌肤", "面部", "体格", "手部"}


def test_physique_slots_baseline_female(_isolate_baseline_packs):
    assert ss.physique_slots("female") == {"体型", "肌肤", "面部", "胸部", "腰腹", "臀部", "四肢"}


def test_physique_slots_unknown_gender_returns_baseline_female():
    assert ss.physique_slots("unknown") == ss.physique_slots("female")
