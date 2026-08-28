"""Setup JSON → Natural language rendering used by setup-chat tool return (raw JSON/English key names disabled)."""
from __future__ import annotations

from typing import Any

from context.content_packs import render_custom_fields_block

_WORLD_SCALAR: tuple[tuple[str, str], ...] = (
    ("tone", "基调"),
    ("background", "世界背景"),
)
_WORLD_LIST: tuple[tuple[str, str], ...] = (
    ("factions", "势力"),
    ("races", "种族"),
    ("geography", "地理"),
    ("power_system", "力量体系"),
    ("core_themes", "核心主题"),
)


def geography_names(wb: dict[str, Any] | None) -> list[str]:
    """Extracts named geography-list entries from a world_bible dict, for callers that need a
    plain location-name reference (not the rendered natural-language summary render_world_chat
    produces) -- e.g. story_sandbox free mode's opening-turn guardrail against inventing new
    places when the director's instruction doesn't name one."""
    if not isinstance(wb, dict) or not wb:
        return []
    names: list[str] = []
    for item in wb.get("geography") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if name and name not in names:
            names.append(name)
    return names


def format_tool_done(title: str, body: str = "", *, hint: str = "") -> str:
    """The splicing tool successfully returns: title + rendered text + optional next step prompt."""
    parts = [title.strip()]
    if body.strip():
        parts.extend(["", body.strip()])
    if hint.strip():
        parts.extend(["", hint.strip()])
    return "\n".join(parts)


def render_world_chat(wb: dict[str, Any] | None) -> str:
    """
world_bible object → summary of Chinese settings."""
    if not isinstance(wb, dict) or not wb:
        return "（空）"
    parts: list[str] = []
    for key, label in _WORLD_SCALAR:
        val = wb.get(key)
        if val:
            parts.append(f"{label}：{val}")
    for key, label in _WORLD_LIST:
        items = wb.get(key) or []
        if not isinstance(items, list) or not items:
            continue
        lines: list[str] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name", "")).strip()
            desc = str(it.get("desc", "")).strip()
            if not name:
                continue
            lines.append(f"  - {name}：{desc}" if desc else f"  - {name}")
        if lines:
            parts.append(f"{label}：\n" + "\n".join(lines))
    return "\n".join(parts) if parts else "（空）"


def _char_display_name(char: dict[str, Any]) -> str:
    return str(char.get("given_name") or char.get("name") or "未命名").strip()


def render_character_chat(char: dict[str, Any], *, brief: bool = False) -> str:
    """
Single cast role → natural language summary."""
    name = _char_display_name(char)
    bits: list[str] = []
    role = str(char.get("role") or "").strip()
    gender = str(char.get("gender") or "").strip()
    if role:
        bits.append(f"角色位 {role}")
    if gender:
        bits.append(gender)
    head = f"{name}（{'，'.join(bits)}）" if bits else name
    if brief:
        return f"- {head}"
    lines = [head]
    causal = char.get("causal_anchors")
    if isinstance(causal, dict) and causal:
        ca = [f"  {k}：{v}" for k, v in causal.items() if v]
        if ca:
            lines.append("因果设定：")
            lines.extend(ca)
    physique = char.get("physique")
    if isinstance(physique, dict) and physique:
        ph = [f"  {k}：{v}" for k, v in physique.items() if v]
        if ph:
            lines.append("体质(physique)：")
            lines.extend(ph)
    sliders = char.get("sliders")
    if isinstance(sliders, dict) and sliders:
        parts = []
        for axis, val in sliders.items():
            if isinstance(val, dict) and "level" in val:
                parts.append(f"{axis}：档位{val['level']}·{val.get('text', '')}")
            else:
                parts.append(f"{axis}：{val}")
        lines.append(f"登场初始滑块：{'；'.join(parts)}")
    clothing = char.get("clothing_dna")
    if isinstance(clothing, dict):
        from engine.setup.cast.clothing_dna import render_clothing_dna_lines
        rendered = render_clothing_dna_lines(clothing)
        if rendered:
            lines.extend(rendered)
    identity_background = str(char.get("identity_background") or "").strip()
    if identity_background:
        lines.append(f"身份背景：{identity_background}")
    personality = str(char.get("personality") or "").strip()
    if personality:
        lines.append(f"人格：{personality}")
    hobbies = char.get("hobbies") or []
    if hobbies:
        lines.append(f"爱好：{'、'.join(hobbies)}")
    verbal_tic = str(char.get("verbal_tic") or "").strip()
    if verbal_tic:
        lines.append(f"口癖：{verbal_tic}")
    lines.extend(render_custom_fields_block(char))
    identity_tags = str(char.get("portrait_identity_tags") or "").strip()
    if identity_tags:
        lines.append(f"形象锚定（立绘）：{identity_tags}")
    visual_tags = str(char.get("portrait_visual_tags") or "").strip()
    if visual_tags:
        lines.append(f"生图提示词（立绘外观）：{visual_tags}")
    return "\n".join(lines)


def render_cast_chat(roster: list[Any] | None) -> str:
    """cast list → character roster summary."""
    if not isinstance(roster, list) or not roster:
        return "（暂无人物）"
    lines = [
        render_character_chat(c, brief=True)
        for c in roster
        if isinstance(c, dict)
    ]
    if not lines:
        return "（暂无人物）"
    return f"共 {len(lines)} 人：\n" + "\n".join(lines)


def render_chapter_chat(chapter: dict[str, Any], chapter_index: int) -> str:
    """Single Chapter plot object → Summary. Each stage line also reports which characters
    entity_index.scan_characters actually recognized in its description -- surfaces the same
    signal downstream cast/state derivation relies on, so the writing agent can catch a pronoun
    ("他"/"她") standing in for a name before it silently drops that character from every later
    stage."""
    from engine.memory_recall.entity_index import scan_characters

    title = str(chapter.get("title") or f"第{chapter_index}章").strip()
    lines = [f"第 {chapter_index} 章：{title}"]
    stages = chapter.get("stages")
    if isinstance(stages, list):
        for j, st in enumerate(stages):
            if not isinstance(st, dict):
                continue
            st_title = str(st.get("title") or f"场景{j + 1}").strip()
            loc = str(st.get("location") or "").strip()
            desc = str(st.get("description") or "").strip()
            seg = f"  {j + 1}. {st_title}"
            if loc:
                seg += f" @ {loc}"
            if desc:
                seg += f"：{desc[:120]}{'…' if len(desc) > 120 else ''}"
                names = scan_characters(desc)
                seg += (
                    f"（识别角色：{'、'.join(names)}）" if names
                    else "（识别角色：无——请检查是否用了人称代词而非人物全名）"
                )
            lines.append(seg)
    return "\n".join(lines)
