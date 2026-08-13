"""Scene-state derivation for story-sandbox: mirrors state_derive.py's two-call split
(derive_initial_states/derive_character_states) for the *scene* itself rather than characters
-- 4 fixed fields (description/objects/atmosphere/disruption) instead of the character
schema's 5. derive_initial_scene_state runs once, on a chapter's opening turn, grounded in the
stage's plot-library location name (a bare place name, not a full description) + the opening
premise + this turn's actual instruction + world summary. derive_scene_state runs every turn after prose is finalized, updating
whatever derive_initial_scene_state (or a prior turn) last reported -- same "no interaction ->
copy the field forward unchanged" contract as the character derivation."""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from engine.story_sandbox.derivation_retry import SandboxErrorCode, call_llm_with_retry
from engine.story_sandbox.llm_json import extract_json_dict
from engine.story_sandbox.state import SceneState

CallLLM = Callable[[str, str], Awaitable[str]]

_FIELDS_SCHEMA = "环境描写 description／物件与陈设变化 objects／氛围与感官 atmosphere／损坏或异常状况 disruption"

_INIT_SYS = (
    f"根据这一章的地点名称、开场剧情梗概、世界观，为这个场景推演出开场时的初始状态，"
    f"只包含以下 4 个字段：{_FIELDS_SCHEMA}，每项一句话概括，要贴合地点性质和即将发生的剧情，"
    "不能空泛。只输出 JSON，形如 "
    '{"description": "...", "objects": "...", "atmosphere": "...", "disruption": "..."}，'
    "不要输出这 4 个字段之外的任何字段，不要输出任何 JSON 以外的文字。"
)

_DERIVE_SYS = (
    f"根据这段新写的正文，输出场景当前的状态，只包含以下 4 个字段：{_FIELDS_SCHEMA}，"
    "每项一句话概括。你会收到场景此前的状态；没有变化的字段照抄原值，不能因为正文没提到就"
    "留空。只输出 JSON，形如 "
    '{"description": "...", "objects": "...", "atmosphere": "...", "disruption": "..."}，'
    "不要输出这 4 个字段之外的任何字段，不要输出任何 JSON 以外的文字。"
)


def _parse_scene_or_none(raw: str) -> SceneState | None:
    parsed = extract_json_dict(raw)
    return dict(parsed) if parsed is not None else None


async def derive_initial_scene_state(
    instruction: str, world_summary: str, known_locations: list[str], call_llm: CallLLM,
) -> SceneState:
    """One-time initialization, run only on a chapter's opening turn before any prose exists.
    Grounds solely on this turn's actual instruction (chapter mode's frontend prefills the
    composer with plot-outline location/description on a fresh chapter, but whatever the
    director actually sends is what this reads) plus the novel's world summary. `known_locations`
    is a soft guardrail (no separate identify LLM call, unlike cast_identify.py's closed-set
    roster) against the model inventing a brand-new place name when the instruction doesn't
    name one -- free mode only (see graph.py::_build_init_scene_node), always [] in chapter
    mode. Returns {} without calling the LLM only when there is truly nothing to ground on
    (instruction empty)."""
    if not instruction:
        return {}
    user = f"导演这一轮发送的开场指令：{instruction}\n\n世界观：{world_summary}"
    if known_locations:
        user += "\n\n已知地点（没有更合适的已知地点时才新造地名）：" + "、".join(known_locations)
    return await call_llm_with_retry(
        _INIT_SYS, user, call_llm,
        parse=_parse_scene_or_none, code=SandboxErrorCode.INIT_SCENE_FAILED,
    )


async def derive_scene_state(
    prior_scene_state: SceneState, finalized_text: str, call_llm: CallLLM,
) -> SceneState:
    """Returns the full 4-field scene state as reported by this call (the prompt asks the model
    to echo unchanged fields itself, unlike derive_character_states' partial-report contract --
    there's only one scene, no per-name filtering to do)."""
    import json

    user = f"此前场景状态：{json.dumps(prior_scene_state, ensure_ascii=False)}\n\n新正文：{finalized_text}"
    return await call_llm_with_retry(
        _DERIVE_SYS, user, call_llm,
        parse=_parse_scene_or_none, code=SandboxErrorCode.SCENE_DERIVE_FAILED,
    )
