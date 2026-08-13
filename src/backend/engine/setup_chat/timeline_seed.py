"""A read-only context assembly (pure function) derived from the timeline of a certain character and a certain chapter.

Reuse the two-layer base: deltas_before + resolve_from produces the rolling seeds; plot produces the stages of this chapter;
The schema rubric shows the slider axis for this role. For the read_archive_seed tool to render to the front-end agent."""
from __future__ import annotations


def _char_lore(name: str) -> dict:
    from repositories import get_lore_repo
    for c in get_lore_repo().list_raw():
        if isinstance(c, dict) and c.get("name") == name:
            return c
    return {}


def _chapter_roster(chapter: int) -> list[str]:
    """
This chapter plots the characters appearing in all stages to preserve order."""
    from repositories import get_plot_repo

    from engine.memory_recall.entity_index import scan_characters
    chapters = get_plot_repo().list_raw()
    ch = next((c for c in chapters if isinstance(c, dict) and c.get("chapter") == chapter), {})
    seen: set[str] = set()
    out: list[str] = []
    for s in ch.get("stages", []):
        for name in scan_characters(str(s.get("description") or "")):
            if name not in seen:
                seen.add(name)
                out.append(name)
    return out


def _relevant_stages(name: str, chapter: int) -> list[dict]:
    from repositories import get_plot_repo

    from engine.memory_recall.entity_index import scan_characters
    chapters = get_plot_repo().list_raw()
    ch = next((c for c in chapters if isinstance(c, dict) and c.get("chapter") == chapter), {})
    out: list[dict] = []
    for s in ch.get("stages", []):
        if name not in scan_characters(str(s.get("description") or "")):
            continue
        out.append({
            "stage_num": s.get("stage_num"),
            "location": s.get("location", ""),
            "description": s.get("description", ""),
        })
    return out


def _slider_rubric(name: str) -> dict[str, list[tuple[int, str]]]:
    """该角色每个滑块轴的档位号+全文描述配对（按档位号升序），供 agent 据此写文本描述并给出对应档位号
    （agent 必须给 level，不再是"看着描述编散文"，见 spec D1）。"""
    from engine.archive.sliders import axes_of, character_rubrics

    rubrics = character_rubrics(name)
    out: dict[str, list[tuple[int, str]]] = {}
    for ax in axes_of(rubrics):
        levels = rubrics.get(ax) or {}
        out[ax] = [(int(k), levels[k]) for k in sorted(levels, key=lambda x: int(x))]
    return out


def build_timeline_seed(name: str, chapter: int) -> dict:
    """
Assemble the derived context of a character and a chapter. No preorder delta → cold_start, otherwise rolling."""
    from context import character_timeline
    from context.character_resolver import resolve_from

    from engine.archive.hook_loader import collect_merge_strategies

    lore = _char_lore(name)
    stages = _relevant_stages(name, chapter)
    first_stage = stages[0]["stage_num"] if stages else 1
    before = character_timeline.deltas_before(name, chapter, first_stage)
    mode = "rolling" if before else "cold_start"
    prior = resolve_from(lore, before, chapter, first_stage, collect_merge_strategies())
    return {
        "name": name, "chapter": chapter, "mode": mode,
        "prior": prior, "stages": stages, "rubric": _slider_rubric(name), "lore": lore,
        #Current physique subfield (key + description); free-form: the agent reuses these keys to ensure consistency across beats, expand on demand, and has no fixed slot verification.
        "physique_current": prior.get("physique") or lore.get("physique") or {},
    }


def _render_prior_sliders(sliders: object) -> str:
    """前序滑块展示：新形态 {axis:{level,text}} → "轴：档位N·text"；旧形态裸字符串（存量小说）→ 原样展示。"""
    if not isinstance(sliders, dict) or not sliders:
        return "（无）"
    parts = []
    for axis, val in sliders.items():
        if isinstance(val, dict) and "level" in val:
            parts.append(f"{axis}：档位{val['level']}·{val.get('text', '')}")
        else:
            parts.append(f"{axis}：{val}")
    return "；".join(parts)


def render_timeline_seed(seed: dict) -> str:
    """Render a build_timeline_seed() dict into the agent-facing grounding text — called by
    both read_archive_seed (one-shot) and world_pipeline.active_timeline_seed_injection
    (persistent, per-turn)."""
    lines = [f"第 {seed['chapter']} 章 · {seed['name']} · 派生上下文",
             f"模式：{'首次出场(cold_start)' if seed['mode'] == 'cold_start' else '滚动(rolling)'}"]
    prior = seed.get("prior") or {}
    lore = seed.get("lore") or {}
    if seed["mode"] == "rolling":
        from context.personality import resolved_personality

        lines.append(f"前序自称：{prior.get('self_ref', '（无）')}")
        lines.append(f"前序人格：{resolved_personality(prior) or '（无）'}")
        lines.append(f"前序口癖：{prior.get('verbal_tic', '（无）')}")
        hobbies = prior.get("hobbies") or []
        if hobbies:
            lines.append(f"前序爱好：{'、'.join(hobbies)}")
        lines.append(f"前序滑块：{_render_prior_sliders(prior.get('sliders'))}")
    else:
        lines.append(
            f"登场初始滑块（lore 底定，据此推演本章起点）：{_render_prior_sliders(lore.get('sliders'))}"
        )
        lines.append(
            f"登场初始口癖（lore 底定，可沿用/可在本章 delta 里改写）：{lore.get('verbal_tic') or '（未设定）'}"
        )
    identity_background = str(lore.get("identity_background") or "").strip()
    if identity_background:
        lines.append(f"身份背景：{identity_background}")
    if seed["mode"] != "rolling":
        hobbies = (prior.get("hobbies") or lore.get("hobbies") or [])
        if hobbies:
            lines.append(f"爱好：{'、'.join(hobbies)}")
    dna = lore.get("clothing_dna") or {}
    if dna:
        from engine.setup.cast.clothing_dna import render_clothing_dna_lines
        lines.extend(render_clothing_dna_lines(dna))
    lines.append("滑块轴（每轴各档位如下，格式=档位号.描述；写 sliders 时须给 level（该档位号）"
                 "+ text（据该档位描述写一句贴合此刻的叙述，别照抄描述原文）：")
    for ax, pairs in (seed.get("rubric") or {}).items():
        rendered = " ｜ ".join(f"{n}.{text}" for n, text in pairs)
        lines.append(f"  - {ax}：{rendered}")
    lines.append("人格 personality：用一两句散文描述该角色此刻的性格/说话气质（自由撰写，别套固定类型名）；"
                 "**档位没变就别换 personality**——工具会打回。")
    lines.append("本章出场 stage：")
    for s in seed["stages"]:
        lines.append(f"  - stage{s['stage_num']}（{s['location']}）：{s['description']}")
    phys = seed.get("physique_current") or {}
    if phys:
        lines.append("当前 physique 子字段（**复用这些键保跨拍一致**；按需可新增子字段、键名用中文亦可；"
                     "异化/变化写进语义最贴合的现有子字段描述，别每拍换名）：")
        for k, v in phys.items():
            lines.append(f"  - {k}: {v}")
    return "\n".join(lines)
