import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "backend"))

from engine.validator.plot_validator import (
    PlotValidationError,
    assert_plot_valid,
    validate_plot,
)

_CHAR_MAP = {"女主丙": {"name": "女主丙"}, "女主乙": {"name": "女主乙"}}


def _clean_plot():
    return {
        6: {
            "chapter": 6,
            "stages": [
                {"stage_num": 1, "location": "茶苑", "description": "事件"},
                {"stage_num": 2, "location": "卧房", "description": "事件"},
            ],
        }
    }


def test_clean_plot_passes():
    assert validate_plot(_clean_plot(), _CHAR_MAP) == []


def test_missing_location():
    p = _clean_plot()
    p[6]["stages"][0]["location"] = ""
    errs = validate_plot(p, _CHAR_MAP)
    assert any("location" in e.message and "ch6" in e.location and "stage1" in e.location for e in errs)


def test_stage_num_gap():
    p = _clean_plot()
    p[6]["stages"][1]["stage_num"] = 4  #Jump number 1 -> 4
    errs = validate_plot(p, _CHAR_MAP)
    assert any("stage_num" in e.message or "连续" in e.message for e in errs)


def test_collects_all_errors():
    p = _clean_plot()
    p[6]["stages"][0]["location"] = ""      #Error 1: location is empty
    p[6]["stages"][1]["description"] = ""   #Error 2: description is empty
    errs = validate_plot(p, _CHAR_MAP)
    assert len(errs) >= 2  #No fail-on-first, collect all at once


def test_assert_raises_on_dirty():
    p = _clean_plot()
    p[6]["stages"][0]["location"] = ""
    with pytest.raises(PlotValidationError):
        assert_plot_valid(p, _CHAR_MAP)


def test_up_to_chapter_limits_scope():
    p = _clean_plot()
    p[7] = {"chapter": 7, "stages": [{"stage_num": 1, "location": "", "description": "x"}]}
    #There is an error in Chapter 7, but it is only checked up to Chapter 6 → No error
    assert validate_plot(p, _CHAR_MAP, up_to_chapter=6) == []
