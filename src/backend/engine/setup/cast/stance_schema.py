"""gender schema reader: physique slots by gender constant."""
from __future__ import annotations


def physique_slots(gender: str) -> set[str]:
    """physique 基础部位槽（题材中性基线 + 已激活内容包的追加槽位）；
    未知 gender → female 基线（降级）。"""
    from context.content_packs import physique_slots as _merged_slots

    if gender not in (*_baseline_genders(), *_extra_genders()):
        gender = "female"
    return _merged_slots(gender)


def _baseline_genders() -> tuple[str, ...]:
    from context.content_packs import BASELINE_GENDERS
    return BASELINE_GENDERS


def _extra_genders() -> list[str]:
    from context.content_packs import get_gender_values
    return get_gender_values()
