"""System prompt composition for story-sandbox turns: opening turn gets cast/world grounding;
every later turn is freeform off written history + core_xp only. Prose style leads every prompt
(see _lead()/build_sandbox_system_prompt) -- it governs the whole turn's voice, so it goes first
for primacy rather than tucked among the other static blocks. core_xp (chapter genre/tone anchor)
persists every turn like prose style, unlike the one-shot scene grounding, since it's a tone
anchor rather than a plot outline to free-improvise away from. Not a reuse of
dialogue_mode/turns.py::build_system_prompt, which contracts for *expanding a fixed skeleton* --
a different job from *improvising from loose anchors* with no skeleton at all.

Chapter mode's opening scene outline (stage1's description) is NOT rendered as a separate system
prompt block -- the frontend pre-fills the composer with it on a fresh chapter switch (see
StorySandboxPanel.tsx), so it arrives as the director's own instruction in the user turn instead
of a duplicate, invisible anchor the user never sees or edits. resolve_stage1_cast is still
called for cast cards / world summary / name-dedupe, just not for that scene-description text.

chapter == 0 is the reserved free-mode sentinel (real chapters are always >= 1) -- free mode
skips the stage/core_xp blocks entirely (there is no outline to ground them in) and gets its
world grounding from the novel's world bible directly, not through skeleton_seed's
chapter-scoped assembly. See
docs/superpowers/specs/2026-07-18-sandbox-free-mode-dynamic-cast-design.md.

The in-scene dynamic cast block (cast.py::render_dynamic_cast_block) and recall_block (see
memory_recall.recall.recall_relevant_context) do NOT render here -- both moved to
turn_packet.py::render_turn_packet so they sit right next to the director's instruction in the
user turn (attention-dispersion concern: a model may not reliably bind a system-prompt
setting/character to an entity the instruction names). See
docs/superpowers/specs/2026-07-25-sandbox-recall-cast-to-user-prompt-design.md.
build_sandbox_system_prompt returns (prompt, stage1_names) instead of a bare string so the caller
can dedupe the user-turn cast block against stage1's own names without a second (expensive)
resolve_stage1_cast call.

Every turn also gets a trailing progress block (_progress_block) -- rolling summary, recent-turn
history, current character/scene state, profile-mutation overlay -- placed right before where the
dynamic cast block/recall block/instruction now render in the user turn. _ANTI_CLOSING_BLOCK is
appended after that, i.e. it is the true last block in every branch, for max recency weight
against the model's default habit of wrapping up a turn with a scene-cutaway/summary flourish."""
from __future__ import annotations

from engine.story_sandbox.state import CharacterState, Round, SceneState

KEEP_FULL_TURNS = 2

# Output-format wording is byte-identical across the three framings below and mirrors the
# "【导演】.../【正文】..." shape _progress_block already renders for turn history (see
# recent_turns_block) -- the model sees its own required marker as a live few-shot example of
# the convention. Enforced in code, not just prompt: message_hub.py's write_turn wraps the raw
# token stream in engine.story_sandbox.prose_format.strip_prose_preamble, which discards
# anything before the marker (out-of-character acknowledgements like "好的，导演，以下是正文"
# survived this instruction alone) before it ever reaches the frontend or gets persisted.
_OUTPUT_FORMAT_CONTRACT = (
    "④输出格式：回复必须以「【正文】：」开头，后面直接接正文内容——开头前不能有任何寒暄/确认/"
    "元评论（例如「好的」「明白了」「以下是正文」之类），正文写完也不要再追加说明或点评。"
)

_OPENING_ROLE_FRAMING = (
    "你是一名故事沙盒的即兴共同创作者，负责把导演这一轮给出的开场指令即兴演绎成正文。\n"
    "场外有一位导演（用户）在推进节奏：他不扮演故事里的任何角色，只在你写完一段后，"
    "给你下一段的方向性提示或反馈（也可能只是「继续」）。\n"
    "写作契约：①导演这一轮给出的开场指令只是这一幕的起点，不是必须执行到底的大纲——写完这个开场之后，"
    "故事往哪走完全由你和导演在过程中即兴决定，不必回到任何预设的后续安排；"
    "②写到一个自然的停顿点/反应点就收笔，等导演下一句，不要一次把好几段都续写完；"
    "③不要在正文里向导演提问或跳出角色解释，只输出正文本身；"
    f"{_OUTPUT_FORMAT_CONTRACT}"
)

_FREEFORM_ROLE_FRAMING = (
    "你是一名故事沙盒的即兴共同创作者，正在延续这一章已经写出的正文往下讲。\n"
    "场外有一位导演（用户）在推进节奏：他不扮演故事里的任何角色，只在你写完一段后，"
    "给你下一段的方向性提示或反馈（也可能只是「继续」）。\n"
    "写作契约：①没有预设大纲——完全跟随已经写出的正文和导演的提示自由推进故事走向，"
    "不必呼应最初的开场设定；②写到一个自然的停顿点/反应点就收笔，等导演下一句，"
    "不要一次把好几段都续写完；③不要在正文里向导演提问或跳出角色解释，只输出正文本身；"
    f"{_OUTPUT_FORMAT_CONTRACT}"
)

_FREE_MODE_OPENING_ROLE_FRAMING = (
    "你是一名故事沙盒的即兴共同创作者，这是一场完全自由的即兴创作——没有任何预设的章节大纲或开场场景，"
    "只有下面的世界观设定，以及随导演指令或正文提及、随之登场的角色档案。\n"
    "场外有一位导演（用户）在推进节奏：他不扮演故事里的任何角色，只在你写完一段后，"
    "给你下一段的方向性提示或反馈（也可能只是「继续」）。\n"
    "写作契约：①故事从导演的第一句指令开始，具体展开完全由你和导演在过程中即兴决定；"
    "②写到一个自然的停顿点/反应点就收笔，等导演下一句，不要一次把好几段都续写完；"
    "③不要在正文里向导演提问或跳出角色解释，只输出正文本身；"
    f"{_OUTPUT_FORMAT_CONTRACT}"
)


def _cast_block(cards: list[dict]) -> str:
    if not cards:
        return ""
    body = "\n\n".join(c["card"] for c in cards)
    return f"\n\n## 在场角色档案\n{body}"


def _prose_style_block(prose_style: str) -> str:
    """No leading blank line, unlike the other block helpers -- this one is placed first in
    build_sandbox_system_prompt (prose style governs the whole turn's voice, so it leads the
    prompt for primacy) and callers add the separating blank line themselves via _lead()."""
    style = (prose_style or "").strip()
    if not style:
        return ""
    return f"## 文风调色档\n{style}"


# Appended last on every branch of build_sandbox_system_prompt -- models default to closing
# each turn with a scene-cutaway + rhetorical-summary flourish ("没有人知道/没有人会关心" ...
# "这就是……最普通不过的……") even though the writing contract already says to stop at a natural
# pause point. That contract wasn't enough on its own, so this calls out the exact failure
# pattern and puts it last (highest-recency weight) rather than folding it into
# _OPENING_ROLE_FRAMING/_FREEFORM_ROLE_FRAMING, which get pushed earlier by core_xp/progress.
_ANTI_CLOSING_BLOCK = (
    "\n\n## 收束性结尾禁令\n"
    "除非导演这一轮指令里明确要求收尾/结束/收场，否则正文结尾禁止使用'跳出场景升华总结'式的收束句："
    "例如临时切到远处环境（下课铃、路人、城市夜色之类）＋「没有人知道/没有人会关心/没有人在意」式旁白，"
    "再接一句「这就是……最普通不过的……」式总结升华。写到自然的停顿点/反应点直接收笔，"
    "不要额外追加这种脱离角色视角的旁白式总结来'收尾'这一段。"
)


def _lead(block: str) -> str:
    """Front-of-prompt placement helper: no separator before `block` (it IS the start), just a
    blank line after it when non-empty so whatever follows isn't glued to it."""
    return f"{block}\n\n" if block else ""


def _core_xp_block(core_xp: list[str]) -> str:
    items = [str(x).strip() for x in (core_xp or []) if str(x).strip()]
    if not items:
        return ""
    return "\n\n## 本章题材基调\n" + "、".join(items)


def _world_block(world_summary: str) -> str:
    summary = (world_summary or "").strip()
    return f"\n\n## 世界观\n{summary}" if summary else ""


def _known_roster_fallback_block(names: list[str]) -> str:
    if not names:
        return ""
    return (
        "\n\n## 已知角色名单（禁止凭空发明新角色）\n"
        "本小说目前已存在的角色只有以下这些，写这段开场时只能从中选用登场角色，"
        "不要创造未列出的新角色：" + "、".join(names)
    )


def _instruction_grounding_blocks(graph_block: str, briefs_block: str) -> str:
    parts = [b for b in (graph_block, briefs_block) if (b or "").strip()]
    return "".join(f"\n\n{b}" if b else "" for b in parts)


def _known_locations_block(names: list[str]) -> str:
    if not names:
        return ""
    return (
        "\n\n## 已知地点（没有更合适的已知地点时才新造地名）\n"
        "本小说世界观里已经登记的地点包括：" + "、".join(names)
    )


def _character_states_block(states: dict[str, CharacterState]) -> str:
    from context.state_derive_schema import format_state_field_value

    if not states:
        return "（暂无角色状态记录）"
    lines = []
    for name, s in states.items():
        parts = []
        for k, v in s.items():
            formatted = format_state_field_value(k, v)
            if formatted:
                parts.append(f"{k}：{formatted}")
        if parts:
            lines.append(f"  - {name}：" + "；".join(parts))
    return "\n".join(lines) if lines else "（暂无角色状态记录）"


def _scene_state_block(scene_state: SceneState) -> str:
    parts = [f"{k}：{v}" for k, v in scene_state.items() if v not in ("", None, {}, [])]
    return "；".join(parts) if parts else "（暂无场景状态记录）"


def _profile_block(profile: dict[str, CharacterState]) -> str:
    if not profile:
        return ""
    lines = []
    for name, fields in profile.items():
        parts = [f"{k}：{v}" for k, v in fields.items() if v not in ("", None, {}, [])]
        if parts:
            lines.append(f"  - {name}：" + "；".join(parts))
    return "\n".join(lines)


def recent_turns_block(turns: list[Round]) -> str:
    recent = turns[-KEEP_FULL_TURNS:] if turns else []
    if not recent:
        return "（这是第一段，还没有历史）"
    lines = [f"【导演】{r.get('instruction', '')}\n【正文】{r.get('prose', '')}" for r in recent]
    return "\n\n".join(lines)


def _progress_block(
    *, rolling_summary: str, turns: list[Round], character_states: dict[str, CharacterState],
    scene_state: SceneState, character_profile: dict[str, CharacterState],
    dialogue_draft: str = "",
) -> str:
    """Trailing per-turn state -- deliberately placed after every static/anchor block (prose
    style, opening stage, cast cards, core_xp) so it reads as the most recent grounding,
    superseding anything stale above it, same hierarchy the old packet-side comments
    ('比 system prompt 里的...更新，以此为准') used to spell out per block. recall_block moved out
    to the user turn (see turn_packet.py) -- this block no longer renders it."""
    body = (
        "## 当前进度（比上文任何设定/档案都更新，写正文以下面为准）\n\n"
        f"### 到目前为止的摘要\n{rolling_summary or '（暂无，这是第一段）'}\n\n"
        f"### 最近{KEEP_FULL_TURNS}轮完整记录\n{recent_turns_block(turns)}\n\n"
        f"### 各角色当前状态\n{_character_states_block(character_states)}\n\n"
        "### 角色档案变更（未提及的字段沿用上文的角色档案）\n"
        f"{_profile_block(character_profile) or '（暂无变更）'}\n\n"
        f"### 当前场景状态\n{_scene_state_block(scene_state)}"
    )
    if dialogue_draft:
        body += (
            "\n\n### 本轮对话草稿（必须缝合进这一轮正文，不是仅供参考——"
            "可以改写措辞、调整语序，但草稿里设计的对话交流本身不能整段跳过不用）\n"
            f"{dialogue_draft}"
        )
    return "\n\n" + body


def build_sandbox_system_prompt(
    chapter: int, *, is_opening: bool,
    rolling_summary: str = "", turns: list[Round] | None = None,
    character_states: dict[str, CharacterState] | None = None,
    scene_state: SceneState | None = None,
    character_profile: dict[str, CharacterState] | None = None,
    dialogue_draft: str = "", known_roster_fallback: list[str] | None = None,
    instruction_grounding_graph: str = "", instruction_grounding_briefs: str = "",
) -> tuple[str, set[str]]:
    """Assemble one turn's sandbox system prompt. Returns (prompt, opening_names) --
    opening_names is the set of character names this opening turn actually rendered a persona
    card for (derived from `character_states`, the same roster _build_init_char_node already
    resolved -- see cast.resolve_character_cards), empty set on every non-opening path. The
    caller (graph.py) needs it to `exclude`-dedupe when it separately renders the dynamic
    in-scene cast block into the user turn (see turn_packet.py).

    The in-scene dynamic cast block (cast.py::render_dynamic_cast_block) and recall_block (see
    memory_recall.recall.recall_relevant_context) no longer render here -- both moved to
    turn_packet.py::render_turn_packet so they sit right next to the director's instruction in
    the user turn instead of buried in the system prompt (attention-dispersion concern: the
    model may not reliably bind a system-prompt setting/character to an entity the instruction
    names). world_block and the opening turn's persona cards (_cast_block) stay here -- they're
    one-shot opening content, not per-turn dynamic state.

    Chapter and free mode share the exact same opening-turn resolution now: world grounding
    always comes from the world bible (engine.setup.chat_summary.render_world_chat) and cast
    cards always come from `character_states` -- no more resolve_stage1_cast/plot_library
    stage-description read anywhere in this function. known_roster_fallback (rendered when
    graph.py's init_char node found nobody to ground on -- see _known_roster_fallback_block),
    known_locations_block (free mode only -- see _known_locations_block) and
    core_xp_block (chapter mode's tone anchor, always "" in free mode -- computed above
    regardless of is_opening) are the only remaining per-mode differences, plus role-framing
    wording (_OPENING_ROLE_FRAMING vs _FREE_MODE_OPENING_ROLE_FRAMING).

    is_opening=False: prose style (leading) + freeform role framing + core_xp, same on both
    modes. opening_names is set() -- later turns never exclude anything from the dynamic cast
    block, per cast.py::render_dynamic_cast_block's docstring on why `exclude` must not carry
    over past the opening turn.

    Cast cards come from cast.resolve_character_cards, prose style from
    prose_style.build_active_prose_style_card, core_xp from plot_repo.chapter_core_xp -- all
    one-shot reads at construction time, no tools to refresh them mid-session.

    rolling_summary/turns/character_states/scene_state/character_profile feed _progress_block,
    appended last on every path."""
    from repositories import get_plot_repo

    from engine.execution.prose_style import build_active_prose_style_card

    is_free_mode = chapter == 0
    prose_style_block = _prose_style_block(build_active_prose_style_card())
    core_xp_block = "" if is_free_mode else _core_xp_block(get_plot_repo().chapter_core_xp(chapter))
    progress_block = _progress_block(
        rolling_summary=rolling_summary, turns=turns or [],
        character_states=character_states or {}, scene_state=scene_state or {},
        character_profile=character_profile or {}, dialogue_draft=dialogue_draft,
    )

    if not is_opening:
        prompt = (
            _lead(prose_style_block)
            + _FREEFORM_ROLE_FRAMING + core_xp_block + progress_block
            + _ANTI_CLOSING_BLOCK
        )
        return prompt, set()

    from repositories import get_world_repo

    from engine.setup.chat_summary import geography_names, render_world_chat
    from engine.story_sandbox.cast import resolve_character_cards

    wb = get_world_repo().get()
    world_block = _world_block(render_world_chat(wb))
    cards = resolve_character_cards(chapter, sorted(character_states or {}))
    opening_names = {c["name"] for c in cards}
    roster_fallback_block = _known_roster_fallback_block(known_roster_fallback or [])
    instruction_grounding_block = _instruction_grounding_blocks(
        instruction_grounding_graph, instruction_grounding_briefs,
    )
    known_locations_block = _known_locations_block(geography_names(wb)) if is_free_mode else ""
    role_framing = _FREE_MODE_OPENING_ROLE_FRAMING if is_free_mode else _OPENING_ROLE_FRAMING
    prompt = (
        _lead(prose_style_block)
        + role_framing
        + world_block
        + _cast_block(cards)
        + roster_fallback_block
        + instruction_grounding_block
        + known_locations_block
        + core_xp_block
        + progress_block
        + _ANTI_CLOSING_BLOCK
    )
    return prompt, opening_names
