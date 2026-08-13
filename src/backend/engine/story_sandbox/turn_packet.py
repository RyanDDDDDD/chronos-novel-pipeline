"""Per-turn user message: in-scene cast cards + related-cast cards + recalled settings/history +
the director's instruction for this turn -- plus, for a rewrite, the previous prose being redone
and free-text feedback on it.

cast_block (cast.py::render_dynamic_cast_block's output), related_cast_block
(cast.py::render_related_cast_block's output), and recall_block
(memory_recall.recall.recall_relevant_context's output) render here, right before the
instruction, rather than in the system prompt (prompt.py) -- attention-dispersion concern: a
model may not reliably bind a system-prompt setting/character to an entity the instruction
names. See docs/superpowers/specs/2026-07-25-sandbox-recall-cast-to-user-prompt-design.md and
docs/superpowers/specs/2026-07-26-sandbox-present-vs-related-cast-design.md.

Everything else (rolling summary, recent-turn history, character/scene state, profile overlay,
dialogue draft) still renders into the system prompt via prompt.py's _progress_block -- see that
module's docstring for why. This keeps those blocks the ONLY dynamic-per-entity content in
the user turn, not a wall of every kind of state."""
from __future__ import annotations

# Compound instructions (e.g. an exposition/info request bundled with a scene-start directive)
# tend to lose their weaker half to whichever clause is more vivid to write -- this is a plain
# instruction-following nudge, not a classifier, so it costs nothing when the instruction isn't
# actually compound.
COMPOUND_INSTRUCTION_REMINDER = (
    "（若这段指令包含多个诉求——例如先要说明性信息、再给一个场景动作指令——两者都要落实，"
    "不能因为其中一个更具体/更好写就只写它而漏掉另一个；说明性诉求通常适合先用叙述简要交代，"
    "再顺势进入场景动作，不要整段跳过。）"
)


def render_turn_packet(
    *, instruction: str, cast_block: str = "", related_cast_block: str = "",
    recall_block: str = "", rewrite_note: dict[str, str] | None = None,
) -> str:
    """Assemble this turn's user message: cast_block, then related_cast_block, then recall_block,
    then the instruction (closest to where generation begins -- same "most recent grounding
    wins" placement prompt.py's _progress_block already uses in the system prompt), then a fixed
    compound-instruction reminder, then rewrite_note when this is a rewrite. Each of
    cast_block/related_cast_block/recall_block is stripped and skipped entirely when blank, so a
    turn with nothing recalled/no one on stage/no related characters doesn't leave stray blank
    sections. rewrite_note (previous_prose/feedback), when given, appends a section describing
    this as a steered rewrite of an existing round -- kept separate from `instruction` since the
    feedback is about how the prose reads, not a replacement for what the scene/instruction says
    happens."""
    parts: list[str] = []
    if cast_block.strip():
        parts.append(cast_block.strip())
    if related_cast_block.strip():
        parts.append(related_cast_block.strip())
    if recall_block.strip():
        parts.append(recall_block.strip())
    parts.append(f"## 导演本轮指令\n{instruction}")
    parts.append(COMPOUND_INSTRUCTION_REMINDER)
    if rewrite_note is not None:
        feedback = rewrite_note["feedback"] or "（未填写，按你的判断改一版）"
        parts.append(
            "## 这是一次重写（场景与指令不变，只调整写法）\n"
            f"上一次写的正文：{rewrite_note['previous_prose']}\n\n"
            f"导演对这次重写的反馈：{feedback}"
        )
    return "\n\n".join(parts)
