"""Code-triggered internal LLM call that generates a stage's beat-by-beat skeleton prose --
replaces the chat agent composing this prose itself inside the long-lived setup_chat
conversation. Mirrors timeline_auto.py's shape: a stateless system prompt, a non-streaming
get_cloud_llm() call, JSON-only output, parse-and-validate with retry.

See docs/superpowers/specs/2026-07-25-skeleton-beat-internal-generation-design.md."""
from __future__ import annotations

import time

from loguru import logger

_SKELETON_WRITER_SYS = (
    "你是剧情架构师，负责把某章某个 stage 的粗大纲扩写成【分拍结构底稿】——按叙事节奏切成若干"
    "「拍」(beat)，每拍交代场景/动作/情绪走向、指代落具体全名（不用\"他们/众人\"等模糊代称）、"
    "织入给定的伏笔召回，但只搭结构、不上血肉——拟声/神情/感官等细节留给写作期主笔，这里不写。"
    "全程第三人称视角；默认不写人物台词/对白口白（台词走独立的联合起草步骤，不在这层生成）。\n"
    "底稿写法：只写可观察的动作/事件/画面锚点，不写情绪总结与体感结论（\"她觉得/她感到/心跳加速\""
    "这类内在状态判词不要写，那是台词该喊出来的东西）。\n"
    "切拍规矩（拍数直接乘写作期成本，别切碎）：每拍 200–500 字、一个叙事单元（一次动作节奏或一次"
    "情绪转折）；3–6 拍软上限，过场段 1–2 拍即可；拍与拍之间时间顺承，不重叠不倒叙。\n"
    "写回的是纯净底稿正文：绝不把选项编号/情景标签/分镜标注/转折点标记（如「〔角度2〕」「『信任到"
    "恐惧』转折点：」这类）写进拍文——那些只是生成依据，不进底稿；每拍 text 里只有可直接读的叙事"
    "正文。\n"
    "禁涉及具体体位/姿势；禁用 AI 腔句式（如「不是【】，是【】」「仿佛【】又像【】」）。\n"
    "本章各段的高潮转折与核心冲突须精准触碰/撞击在场角色的因果锚点（创伤/执念/渴望等，见角色"
    "档案 grounding）——冲突不是泛泛的外部事件，而是迫使角色面对或违背其底线的时刻。\n"
    "只输出 JSON，形如 {\"beats\": [{\"text\": \"拍正文\", \"sensation_notes\": [\"...\"]}, ...]}，"
    "sensation_notes 只在给定的情景拓展本身带对应生理感受、且该拍确实用上时才给，没有就给空列表；"
    "不要输出任何 JSON 以外的文字。"
)

_MAX_ATTEMPTS = 3  # first try + 2 retries, matching timeline_auto.py's convention


async def _call_llm(system: str, user: str, *, meta: dict | None = None) -> str:
    """Stateless, non-streaming, no session binding -- routed through the
    "skeleton_writer" import_llm_params node (对话 tab) like timeline_auto._call_llm."""
    from domain.token_usage import extract_usage
    from langchain_core.messages import HumanMessage, SystemMessage
    from llm.factory import get_cloud_llm

    from engine.modes.author_loop_skill_prefs import bind_node_llm, load_dialogue_prefs

    llm = bind_node_llm(
        get_cloud_llm(), "skeleton_writer", load_dialogue_prefs()["import_llm_params"],
    )
    t0 = time.perf_counter()
    resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    elapsed_ms = (time.perf_counter() - t0) * 1000
    text = str(resp.content)
    tin, tout, tcached = extract_usage(resp)
    logger.info(
        "[setup_chat_perf] skeleton_writer LLM | elapsed_ms={:.2f} | tokens_in={} "
        "tokens_out={} tokens_cached={} | meta={}",
        elapsed_ms, tin, tout, tcached, meta or {},
    )
    return text


def _render_user_prompt(
    chapter: int, stage_num: int, *, overview: str, is_revision: bool,
) -> str | None:
    """None when the (chapter, stage_num) can't be found in plot -- caller turns this into an
    error string without ever calling the LLM."""
    from engine.setup_chat.construction_plan import _stage_beats
    from engine.setup_chat.skeleton_seed import build_skeleton_seed, render_skeleton_seed

    seed = build_skeleton_seed(chapter)
    stage = next((s for s in seed.get("stages") or [] if s.get("stage_num") == stage_num), None)
    if stage is None:
        return None

    lines = [render_skeleton_seed(seed), "", f"现在只扩写 stage{stage_num}：{stage['description']}"]

    prev_beats = _stage_beats(chapter, stage_num - 1)
    if prev_beats:
        prev_text = "\n".join(b.get("text", "") for b in prev_beats if isinstance(b, dict))
        lines.append(f"\n上一段（stage{stage_num - 1}）已写的拍文，供承接语气/进度参考：\n{prev_text}")

    if is_revision:
        existing = _stage_beats(chapter, stage_num) or []
        existing_text = "\n".join(
            f"拍{i}：{b.get('text', '')}" for i, b in enumerate(existing) if isinstance(b, dict)
        )
        lines.append(f"\n本段现有拍文（待修改）：\n{existing_text}")
        lines.append(f"\n用户的修改意见：{overview}")
    else:
        from engine.setup_chat import skeleton_pipeline

        angles = skeleton_pipeline._LENS_CHOSEN.get((chapter, stage_num), [])
        extensions = skeleton_pipeline._EXT_CHOSEN.get((chapter, stage_num), [])
        lines.append(f"\n本段选定的分镜/突出角度：{'、'.join(angles) or '（无）'}")
        lines.append(f"本段选定的情景拓展：{'、'.join(extensions) or '（都不用，自由构思情景拓展）'}")
        if overview.strip():
            lines.append(f"\n补充概述：{overview}")

    return "\n".join(lines)


async def generate_stage_beats(
    chapter: int, stage_num: int, *, overview: str, is_revision: bool,
) -> list[dict] | str:
    """Returns a list of beat dicts ({"text": ..., "sensation_notes": [...]}) on success, or
    an error message string on failure. Never persists anything itself -- persistence is
    write_chapter_skeleton's job."""
    if is_revision and not overview.strip():
        return "改这段需要先说明修改意见，overview 不能为空。"

    user_prompt = _render_user_prompt(
        chapter, stage_num, overview=overview, is_revision=is_revision,
    )
    if user_prompt is None:
        return f"第 {chapter} 章无 stage {stage_num}，无法生成。"

    from pydantic import ValidationError
    from utils.timer import setup_chat_step_timer

    from engine.setup_chat.tool_args import BeatArgs
    from engine.story_sandbox.llm_json import extract_json_dict

    llm_meta = {"chapter": chapter, "stage_num": stage_num, "is_revision": is_revision}
    async with setup_chat_step_timer(
        "skeleton_writer.generate_stage_beats",
        extra_meta={**llm_meta, "max_attempts": _MAX_ATTEMPTS},
    ):
        last_error = ""
        for attempt in range(_MAX_ATTEMPTS):
            attempt_meta = {**llm_meta, "attempt": attempt + 1}
            try:
                raw = await _call_llm(_SKELETON_WRITER_SYS, user_prompt, meta=attempt_meta)
            except Exception as exc:  # noqa: BLE001 -- network/provider errors are retry candidates
                last_error = str(exc)
                logger.warning(
                    "[setup_chat_perf] skeleton_writer attempt failed | meta={} error={!r}",
                    attempt_meta, last_error,
                )
                continue
            parsed = extract_json_dict(raw)
            if parsed is None or not isinstance(parsed.get("beats"), list) or not parsed["beats"]:
                last_error = f"unparseable/empty beats JSON: {raw[:200]!r}"
                logger.warning(
                    "[setup_chat_perf] skeleton_writer attempt rejected | meta={} reason={}",
                    attempt_meta, last_error,
                )
                continue
            try:
                beats = [BeatArgs.model_validate(b) for b in parsed["beats"]]
            except ValidationError as exc:
                last_error = f"beat validation failed: {exc}"
                logger.warning(
                    "[setup_chat_perf] skeleton_writer attempt rejected | meta={} reason={}",
                    attempt_meta, last_error,
                )
                continue
            logger.info(
                "[setup_chat_perf] skeleton_writer.generate_stage_beats succeeded | "
                "beat_count={} meta={}",
                len(beats), attempt_meta,
            )
            return [b.model_dump() for b in beats]

    logger.error(
        "[skeleton_writer] generation failed for chapter={} stage_num={} after {} attempts: {}",
        chapter, stage_num, _MAX_ATTEMPTS, last_error,
    )
    return f"生成失败（已重试 {_MAX_ATTEMPTS} 次）：{last_error}"
