"""Character-specific profile (chapter level) structure validator."""

from __future__ import annotations

#The top level only retains the identity/base fields that really do not change with the stage.
#physique has been dropped to stages[] (collapsed from the timeline piece by piece) and no longer requires the top level to exist.
_BASE_LORE_FIELDS = [
    "name", "role",
]


class ArchiveError:
    __slots__ = ("field", "message")

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message

    def __str__(self) -> str:
        return f"[{self.field}] {self.message}"


def validate_archive(archive: dict) -> list[ArchiveError]:
    errors: list[ArchiveError] = []

    #── Basic fields ──
    for field in _BASE_LORE_FIELDS:
        if field not in archive:
            errors.append(ArchiveError(field, "缺少基础档案字段"))

    if "extensions" not in archive:
        errors.append(ArchiveError("extensions", "缺少 extensions"))
    elif not isinstance(archive["extensions"], dict):
        errors.append(ArchiveError("extensions", "extensions 必须是 dict"))

    #── resolved profile fields (flat, no per-stage nesting) ──
    #The stage marker requirement for thought_process / phase_name / personality has been retired (the foreground process does not produce these markers).
    #The old builder can still produce thought_process, so its type guard (presence must be an object) is retained, but is no longer required.
    tp = archive.get("thought_process")
    if tp is not None and not isinstance(tp, dict):
        errors.append(ArchiveError("thought_process", "须为对象"))
    sl = archive.get("sliders")
    if sl is not None and not isinstance(sl, dict):
        errors.append(ArchiveError("sliders", "须为对象"))

    return errors


def assert_valid(archive: dict) -> None:
    errors = validate_archive(archive)
    if errors:
        name = archive.get("name", "?")
        detail = "\n  ".join(str(e) for e in errors)
        raise ValueError(f"档案验证失败（{name}）:\n  {detail}")


def validate_state_presence(parsed_stages: dict, relevant_stages: list[dict]) -> list[ArchiveError]:
    """state 不受 slider 门控（见 state_builder.md 红线），run_state_delta_call 的原始输出里
    每个出场 stage 都必须自带非空 state.physiology/psychology——不同于 assemble 后的 resolved 快照，
    这里查的是本 stage 自己的 delta，不会被 resolve_from 的滚动继承掩盖成"其实是更早 stage 的旧值"。"""

    errors: list[ArchiveError] = []
    for s in relevant_stages:
        sid = str(s["stage_num"])
        prefix = f"stages.{sid}.state"
        delta = parsed_stages.get(sid, {}).get("delta", {})
        state = delta.get("state")
        if not isinstance(state, dict):
            errors.append(ArchiveError(prefix, "本 stage 的 delta 缺少 state（每个出场 stage 都必须重新推演并输出）"))
            continue
        if not state.get("physiology"):
            errors.append(ArchiveError(f"{prefix}.physiology", "为空"))
        if not state.get("psychology"):
            errors.append(ArchiveError(f"{prefix}.psychology", "为空"))
    return errors


def assert_state_presence(parsed_stages: dict, relevant_stages: list[dict]) -> None:
    errors = validate_state_presence(parsed_stages, relevant_stages)
    if errors:
        detail = "\n  ".join(str(e) for e in errors)
        raise ValueError(f"state delta 校验失败：\n  {detail}")
