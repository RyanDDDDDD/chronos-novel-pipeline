"""plot_library structure verification layer (fail-fast verification before setting layer construction).

Independent directory, reserved for future expansion (role setting verification, etc.). This issue only checks the plot.
Pure function, no I/O, no LLM; data source injected by caller (builder loaded _plot_map/char_map)."""
from __future__ import annotations

_REQUIRED_STAGE_FIELDS = ("stage_num", "location", "description")


class ValidationError:
    __slots__ = ("location", "message")

    def __init__(self, location: str, message: str):
        self.location = location
        self.message = message

    def __str__(self) -> str:
        return f"[{self.location}] {self.message}"


class PlotValidationError(Exception):
    """
plot verification failed (all errors summarized)."""

def validate_plot(
    plot_map: dict,
    char_map: dict,
    *,
    up_to_chapter: int | None = None,
) -> list[ValidationError]:
    """Scan plot_map (within up_to_chapter range) to collect all structural errors. Not fail-on-first."""
    errors: list[ValidationError] = []
    chapters = sorted(
        c for c in plot_map
        if up_to_chapter is None or c <= up_to_chapter
    )
    for ch in chapters:
        ch_data = plot_map[ch] or {}
        stages = ch_data.get("stages") or []
        seen_nums: list[int] = []
        for idx, stage in enumerate(stages):
            sid = stage.get("stage_num", idx + 1)
            loc = f"ch{ch}.stage{sid}"
            #1. stage required field
            for f in _REQUIRED_STAGE_FIELDS:
                if not stage.get(f):
                    errors.append(ValidationError(loc, f"缺少或为空字段 '{f}'"))
            if isinstance(stage.get("stage_num"), int):
                seen_nums.append(stage["stage_num"])
        #4. stage_num continuity (1..N, no repetitions, no jumps)
        if seen_nums:
            expected = list(range(1, len(seen_nums) + 1))
            if sorted(seen_nums) != expected:
                errors.append(ValidationError(
                    f"ch{ch}", f"stage_num 不连续/有重复：{sorted(seen_nums)}，期望 {expected}"))
    return errors


def assert_plot_valid(
    plot_map: dict,
    char_map: dict,
    *,
    up_to_chapter: int | None = None,
) -> None:
    errs = validate_plot(plot_map, char_map, up_to_chapter=up_to_chapter)
    if errs:
        detail = "\n".join(f"  {e}" for e in errs)
        raise PlotValidationError(f"plot_library 校验未通过（{len(errs)} 项）：\n{detail}")
