"""One LLM call: turn a sandbox round's memory-archive entry + each present character's
cached appearance tags into a structured multi-character booru prompt for NovelAI V4.5.

Mirrors media.portrait.visual_tags in spirit (booru tags, no art-style/medium tags, no age
tags -- the art-style preset layer downstream owns rendering style), but scene-scoped:
multi-subject is allowed, and per-character captions come straight from portrait_visual_tags
so the Precise Reference image and the caption reinforce each other."""
from __future__ import annotations

import json
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage

_TAGLESS_PLACEHOLDER = "1other, person"

_SYSTEM_PROMPT = (
    "You are a prompt engineer for NovelAI's V4.5 anime image model. Given a scene moment and "
    "a list of characters in frame (each with their fixed appearance tags), output ONE JSON "
    "object, no other text:\n"
    '{"base": "<scene tags>", "characters": [{"name": "<name>", "caption": "<tags>"}]}\n'
    "- base: comma-separated booru tags for the SETTING only -- location, time of day, mood, "
    "framing/shot (e.g. 'medium shot', 'wide shot'), and a subject-count tag ('2girls', "
    "'1boy 1girl', ...). No character appearance in base.\n"
    "- characters: one entry PER given character, SAME names, SAME order, none added/removed. "
    "Each caption = that character's given appearance tags + what they are doing in THIS "
    "moment (pose, gesture, expression, what they hold). Keep the appearance tags verbatim.\n"
    "- Never emit an art-style / medium / rendering tag ('anime style', 'realistic', "
    "'oil painting', '3d', ...). Never emit a numeric age. English tags only, no full "
    "sentences, no Chinese, no quotes inside tag strings."
)


@dataclass(frozen=True)
class ScenePromptResult:
    base: str
    characters: list[dict]  # [{"name": str, "caption": str}], present-character order


def _describe(memory_entry: dict, character_visual_tags: dict[str, str]) -> str:
    names = list(memory_entry.get("characters") or [])
    lines = [
        f"event: {memory_entry.get('summary') or ''}",
        f"time: {memory_entry.get('time') or ''}",
        f"location: {memory_entry.get('location') or ''}",
        "characters in frame:",
    ]
    for n in names:
        lines.append(f"- {n}: {character_visual_tags.get(n) or '(no appearance tags)'}")
    return "\n".join(lines)


def _fallback(memory_entry: dict, character_visual_tags: dict[str, str]) -> ScenePromptResult:
    bits = [
        b for b in (memory_entry.get("location"), memory_entry.get("time"),
                    memory_entry.get("summary"))
        if b
    ]
    base = ", ".join(bits) or "scene"
    names = list(memory_entry.get("characters") or [])
    chars = [
        {"name": n, "caption": character_visual_tags.get(n) or _TAGLESS_PLACEHOLDER}
        for n in names
    ]
    return ScenePromptResult(base=base, characters=chars)


def _parse(
    raw: str, memory_entry: dict, character_visual_tags: dict[str, str],
) -> ScenePromptResult:
    names = list(memory_entry.get("characters") or [])
    try:
        obj = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return _fallback(memory_entry, character_visual_tags)
    if not isinstance(obj, dict):
        return _fallback(memory_entry, character_visual_tags)
    base = str(obj.get("base") or "").strip()
    got = {
        str(c.get("name")): str(c.get("caption") or "").strip()
        for c in (obj.get("characters") or []) if isinstance(c, dict)
    }
    if not base or any(n not in got or not got[n] for n in names):
        return _fallback(memory_entry, character_visual_tags)
    return ScenePromptResult(
        base=base,
        characters=[{"name": n, "caption": got[n]} for n in names],
    )


async def build_scene_prompt(
    *, memory_entry: dict, character_visual_tags: dict[str, str],
) -> ScenePromptResult:
    from llm.factory import get_cloud_llm

    if not (memory_entry.get("characters") or []):
        return _fallback(memory_entry, character_visual_tags)
    llm = get_cloud_llm()
    resp = await llm.ainvoke([
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=_describe(memory_entry, character_visual_tags)),
    ])
    raw = resp.content if isinstance(resp.content, str) else str(resp.content)
    return _parse(raw, memory_entry, character_visual_tags)
