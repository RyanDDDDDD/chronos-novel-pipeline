"""Slider: per-character rubric loading, number<->label interchange, cross-chapter guardrail regression check.

Numbers are stored canonically; they are rendered into rubric text when fed to LLM (to prevent misreading of bare numbers);
LLM retrieves the digital storage when outputting the gear label."""
from __future__ import annotations


def character_rubrics(name: str) -> dict[str, dict[str, str]]:
    """This one character's own {axis: levels} ladder, read from its lore entry's sliders.
    Axes without a migrated `levels` ladder (legacy data) are omitted -- callers treat a
    missing axis as unconstrained, same as before."""
    from repositories import get_lore_repo

    char = next(
        (c for c in get_lore_repo().list_raw() if isinstance(c, dict) and c.get("name") == name),
        None,
    )
    sliders = (char or {}).get("sliders") or {}
    out: dict[str, dict[str, str]] = {}
    for axis, val in sliders.items():
        if isinstance(val, dict) and isinstance(val.get("levels"), dict):
            out[axis] = val["levels"]
    return out


def axes_of(rubrics: dict) -> list[str]:
    """This character's slider axis names (in dict insertion order)."""
    return list(rubrics.keys())


def _axis_levels(rubrics: dict, axis: str) -> dict[str, str]:
    return rubrics.get(axis) or {}


def valid_slider_value_shape(v: object) -> bool:
    """sliders 字典（每轴值须为 {"level": int-coercible, "text": 非空str}）的形状校验，D1。

    stage 级 delta 与 cast lore 的登场初值 sliders 共用这一份判定——两处都是同一种 {level,text} 形态。"""
    if not isinstance(v, dict):
        return False
    for axis_val in v.values():
        if not isinstance(axis_val, dict):
            return False
        level = axis_val.get("level")
        text = axis_val.get("text")
        if level is None:
            return False
        try:
            int(level)
        except (TypeError, ValueError):
            return False
        if not isinstance(text, str) or not text.strip():
            return False
    return True


def valid_levels(rubrics: dict, axis: str) -> set[int]:
    """该轴的合法档位号集合（levels 的整数 key）。axis 缺失 → 空集（视为"无约束"，
    调用方应据此跳过范围校验——与 render_slider/_clamp_to_axis 的"rubric 未配置则放行"一致）。"""
    levels = _axis_levels(rubrics, axis)
    return {int(k) for k in levels if str(k).lstrip("-").isdigit()}


def _clamp_to_axis(levels: dict[str, str], value: int) -> int:
    """Clamp by [min,max] of the levels integer key; levels empty → original value."""
    keys = [int(k) for k in levels if str(k).lstrip("-").isdigit()]
    if not keys:
        return int(value)
    return max(min(keys), min(max(keys), int(value)))


def _leading_tag(label: str) -> str:
    """Take the phrase before the rubric tag "." as a short tag that can be copied."""
    return (label or "").split("。")[0].strip()


def axis_tags(rubrics: dict, axis: str) -> list[str]:
    """Short labels for all gear levels of this axis, sorted by level value."""
    levels = _axis_levels(rubrics, axis)
    return [_leading_tag(levels[k]) for k in sorted(levels, key=lambda x: int(x))]


def render_axis_choices(rubrics: dict, axis: str) -> str:
    """Render the axis gear into a "short label - meaning" list for prompt to make a closed selection set for LLM."""
    levels = _axis_levels(rubrics, axis)
    lines = []
    for k in sorted(levels, key=lambda x: int(x), reverse=True):
        full = levels[k]
        tag = _leading_tag(full)
        lines.append(f"  - {tag}（{full}）")
    return f"{axis}：\n" + "\n".join(lines)


def render_slider(rubrics: dict, axis: str, value: int) -> str:
    """number -> gear text. Press the axis levels key range grip. Fallback to 'axis name: value' when rubric is missing."""
    levels = _axis_levels(rubrics, axis)
    if not levels:
        return f"{axis}:{int(value)}"
    v = _clamp_to_axis(levels, value)
    return str(levels.get(str(v), f"{axis}:{v}"))


def parse_slider_label(rubrics: dict, axis: str, label: str) -> int | None:
    """Gear label/text -> number. Exact matching of short tags is preferred -> pure numbers -> tag substrings -> whole sentence strings."""
    table = _axis_levels(rubrics, axis)
    s = (label or "").strip()
    if not s:
        return None
    tags = {k: _leading_tag(v) for k, v in table.items()}
    for k, tag in tags.items():
        if tag and s == tag:
            return int(k)
    if s.lstrip("-").isdigit():
        return _clamp_to_axis(table, int(s))
    for k, tag in tags.items():
        if tag and (tag in s or s in tag):
            return int(k)
    for k, text in table.items():
        if text and (text in s or s in text):
            return int(k)
    return None


def check_slider_regression(
    rubrics: dict,
    prev: dict[str, int],
    new: dict[str, int],
    reverse_threshold: int = 2,
) -> list[str]:
    """Soft guardrail: Detect the big "fallback" jump of the slider. Returns a list of alert strings (empty = passed).

    The slider is unified **gradually increasing** (the higher the value, the more advanced/deeper it is); the value of this guardrail has dropped significantly (new is lower than prev and exceeds the threshold)."""
    alerts: list[str] = []
    for axis in axes_of(rubrics):
        if axis not in prev or axis not in new:
            continue
        dropped = prev[axis] - new[axis]
        if dropped > reverse_threshold:
            alerts.append(
                f"[护栏] {axis} 回落跳变 {prev[axis]}→{new[axis]}"
                f"（回落 {dropped} 档 > 阈值 {reverse_threshold}），"
                f"须确认 delta 是否给出剧情理由"
            )
    return alerts
