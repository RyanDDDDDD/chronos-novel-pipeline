"""Deterministic Python orchestration for AUTO mode's whole-chapter skeleton expansion
(auto_expand_skeleton tool). Not an agent tool-calling loop -- one LLM call plans the whole
chapter (direction + per-stage lens/extensions/overview), validated, then a plain sequential
control flow calls set_chapter_direction/set_stage_lens/set_stage_extensions/
write_chapter_skeleton directly. See
docs/superpowers/specs/2026-08-09-auto-mode-skeleton-expansion-design.md."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field, ValidationError, ValidationInfo, model_validator

CallLLM = Callable[[str, str], Awaitable[str]]

_DEFAULT_MAX_REDO = 2


def _skill_body(name: str) -> str:
    from engine.setup_chat.skills import load_skill_body, setup_chat_skill_dirs

    return load_skill_body(name, setup_chat_skill_dirs()) or ""


def _parse_one_object(raw: str) -> dict[str, Any] | None:
    from engine.execution.embed_json import parse_embed_json

    items = parse_embed_json(raw)
    return items[0] if items else None


class SkeletonAutoStageArgs(BaseModel):
    stage_num: int
    lens_angles: list[str] = Field(min_length=1, description="本段分镜/突出角度")
    extensions: list[str] = Field(default_factory=list, description="本段情景拓展，可空")
    overview: str = Field(default="", description="本段概述，可留空")


class SkeletonAutoExpandArgs(BaseModel):
    """model_validate must be called with context={"stage_nums": set[int]} -- the stage-num
    coverage check below has nothing to check against otherwise."""

    direction: str = Field(min_length=1, description="本章整体叙事走向")
    stages: list[SkeletonAutoStageArgs] = Field(min_length=1)

    @model_validator(mode="after")
    def _stage_nums_match(self, info: ValidationInfo) -> SkeletonAutoExpandArgs:
        expected: set[int] = (info.context or {}).get("stage_nums", set()) if info.context else set()
        got = {s.stage_num for s in self.stages}
        if expected and got != expected:
            missing = expected - got
            extra = got - expected
            errs = []
            if missing:
                errs.append(f"缺少 stage：{sorted(missing)}")
            if extra:
                errs.append(f"出现了未知 stage：{sorted(extra)}")
            raise ValueError("；".join(errs))
        return self


_AUTO_SUFFIX_TEMPLATE = (
    "\n\n## AUTO 模式：一次性结构化输出（覆盖整章，不调用 present_choices）\n"
    "不提问、不等待用户确认、不调用 present_choices——按上面这份指南给出的判断标准（分镜呼应"
    "全局走向、情景拓展贴合因果锚点、切拍规矩等），为本章一次性决定整体走向 + 以下每一段的"
    "分镜角度/情景拓展/概述：stage {stage_nums}。\n\n"
    "只输出一个 JSON 对象：\n"
    '{{"direction": "...", "stages": [{{"stage_num": N, "lens_angles": ["...", "..."], '
    '"extensions": ["...", "..."], "overview": "..."}}, ...]}}\n\n'
    "stages 数组必须恰好覆盖 {stage_nums} 这些段、不漏不多，顺序不限；overview 可留空字符串"
    "（分镜+拓展已经够用时不必硬凑）。不要输出这个 JSON 对象以外的任何文字。"
)


async def draft_skeleton_plan(
    chapter: int, stage_nums: list[int], call_llm: CallLLM, *, max_redo: int = _DEFAULT_MAX_REDO,
) -> tuple[dict[str, Any] | None, list[str]]:
    """One-shot whole-chapter plan: direction + per-stage lens/extensions/overview, LLM-drafted
    then Pydantic-validated (SkeletonAutoExpandArgs, stage-num set must exactly match
    stage_nums), retried up to max_redo times with the previous attempt's validation errors fed
    back. Returns (plan_dict, []) on success, (None, errors) once retries are exhausted -- there
    is no partial-plan concept, the whole chapter's plan succeeds or fails as one unit."""
    from engine.setup_chat.skeleton_seed import build_skeleton_seed, render_skeleton_seed

    system = _skill_body("skeleton-expansion") + _AUTO_SUFFIX_TEMPLATE.format(stage_nums=stage_nums)
    seed_text = render_skeleton_seed(build_skeleton_seed(chapter))
    expected = set(stage_nums)
    feedback = ""
    last_errors: list[str] = []
    for _ in range(max_redo + 1):
        user = f"{seed_text}{feedback}"
        raw = await call_llm(system, user)
        parsed = _parse_one_object(raw)
        if parsed is None:
            last_errors = ["未能解析出合法 JSON"]
            feedback = "\n\n## 上一轮未通过，请修正：\n- 未能解析出合法 JSON，请只输出 JSON 对象"
            continue
        try:
            args = SkeletonAutoExpandArgs.model_validate(parsed, context={"stage_nums": expected})
        except ValidationError as exc:
            last_errors = [str(e["msg"]) for e in exc.errors()]
            feedback = "\n\n## 上一轮未通过，请修正：\n" + "\n".join(f"- {m}" for m in last_errors)
            continue
        return args.model_dump(), []
    return None, last_errors


def _chapter_stage_nums(chapter: int) -> list[int]:
    from engine.setup_chat.skeleton_pipeline import _chapter_stage_nums as _real
    return _real(chapter)


def _set_chapter_direction(chapter: int, direction: str) -> None:
    from engine.setup_chat.skeleton_pipeline import set_chapter_direction as _real
    _real(chapter, direction)


def _set_stage_lens(chapter: int, stage_num: int, angles: list[str]) -> None:
    from engine.setup_chat.skeleton_pipeline import set_stage_lens as _real
    _real(chapter, stage_num, angles)


def _set_stage_extensions(chapter: int, stage_num: int, extensions: list[str]) -> None:
    from engine.setup_chat.skeleton_pipeline import set_stage_extensions as _real
    _real(chapter, stage_num, extensions)


async def _write_chapter_skeleton_core(chapter: int, stage_num: int, overview: str) -> str:
    """Thin re-export so tests can monkeypatch without reaching into tools.py -- same reasoning
    as auto_construct.py's _add_character_core/_generate_one_chapter_core. Lazy import avoids a
    top-level circular import (tools.py imports skeleton_auto_construct in the next step)."""
    from engine.setup_chat.tools import write_chapter_skeleton as _real
    result = await _real.ainvoke({"chapter": chapter, "stages": [
        {"stage_num": stage_num, "overview": overview},
    ]})
    return result if isinstance(result, str) else str(result)


def _chapter_remaining_stage_nums(chapter: int) -> list[int]:
    from engine.setup_chat.skeleton_pipeline import chapter_remaining_stage_nums as _real
    return _real(chapter)


def _is_direction_set(chapter: int) -> bool:
    from engine.setup_chat.skeleton_pipeline import is_direction_set as _real
    return _real(chapter)


async def run_auto_expand_skeleton(chapter: int, call_llm: CallLLM) -> str:
    """Top-level entry point -- the only thing tools.py::auto_expand_skeleton calls. Resumable:
    only plans/writes stages that don't have beats yet (chapter_remaining_stage_nums), so a
    chapter with existing progress -- from manual work before an in-turn switch into AUTO, or
    from an earlier partial auto run -- picks up where it left off instead of re-planning (and
    silently overwriting) already-written stages. Direction is only (re)recorded if not already
    set, for the same reason. Planning failure aborts with no stages written (there is no
    partial-plan concept). A single stage's write_chapter_skeleton failure is skipped, recorded,
    and the rest of the chapter's stages still proceed (best-effort, same philosophy as
    auto_construct.py's build_characters/build_chapters)."""
    from engine.setup_chat.skeleton_pipeline import mark_chapter_active

    if not _chapter_stage_nums(chapter):
        return f"第 {chapter} 章不存在于 plot 或无 stage，无法扩写骨架（请先写本章 plot）。"

    mark_chapter_active(chapter)
    stage_nums = _chapter_remaining_stage_nums(chapter)
    if not stage_nums:
        return f"第 {chapter} 章骨架已全部展开完成，无需再扩写。"

    plan, errors = await draft_skeleton_plan(chapter, stage_nums, call_llm)
    if plan is None:
        return f"第 {chapter} 章骨架规划生成失败：" + "、".join(errors)

    already_had_direction = _is_direction_set(chapter)
    if not already_had_direction:
        _set_chapter_direction(chapter, plan["direction"])
    direction_note = plan["direction"] if not already_had_direction else "（沿用已确定的整体走向，未覆盖）"

    written: list[int] = []
    failed: list[str] = []
    for stage in sorted(plan["stages"], key=lambda s: s["stage_num"]):
        stage_num = stage["stage_num"]
        _set_stage_lens(chapter, stage_num, stage["lens_angles"])
        _set_stage_extensions(chapter, stage_num, stage["extensions"])
        result = await _write_chapter_skeleton_core(chapter, stage_num, stage["overview"])
        if "失败" in result:
            failed.append(f"stage {stage_num}：{result}")
            continue
        written.append(stage_num)

    lines = [f"第 {chapter} 章整体走向：{direction_note}", f"已扩段：{written or '（无）'}"]
    if failed:
        lines.append("失败段：" + "；".join(failed))
    return "\n".join(lines)
