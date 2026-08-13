"""Prose style card assembly: per-novel preset + custom addendum (the positive baseline card
has been retired; the negative/blocklist card was removed because it had no effect on the LLM --
mechanical sentence-pattern guarding now lives in engine/execution/style_guard.py).

Presets come from three directories: skills/prose-styles/*.md (static, hand-written, committed,
shared globally), discovered content packs' contributed dirs (e.g.
hooks/content_packs/<pack>/prose_styles/*.md, see context.content_packs.contributed_dirs),
and data/prose_styles/*.md (generated when a novel is imported -- see
engine/setup_chat/prose_style_extraction.py,
gitignored, also shared globally; the chat agent can also write directly into this directory via
the write_prose_style_preset tool -- see engine/setup_chat/tools.py). All three are the same
markdown card format (first line fixed as `# 语感调色：<title>`), so load_preset_card/
list_prose_style_presets treat them uniformly (the first two as "static"/protected, the last as
"custom"/editable)."""
from __future__ import annotations

import os

from utils.paths import SKILLS_DIR, prose_styles_dir

_DEFAULT_PROSE_STYLE_PRESET = "plain-direct"


def default_prose_style_preset() -> str:
    return _DEFAULT_PROSE_STYLE_PRESET


def _static_prose_style_dirs() -> list[str]:
    from context.content_packs import contributed_dirs

    return [os.path.join(SKILLS_DIR, "prose-styles"), *contributed_dirs("prose_style_dirs")]


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def render_prose_style_card(
    *,
    title: str,
    opening: str,
    techniques: list[str],
    examples: list[dict[str, str]],
    taboos: list[str],
) -> str:
    """Render a full prose-style card markdown, isomorphic to docs/prose-style-template.md.
    techniques/examples/taboos may be empty lists -- the corresponding section is skipped
    entirely, supporting a minimal title+opening-only card (e.g. the one-off migration script
    rebuilding cards from legacy data)."""
    lines = [f"# 语感调色：{title}", ""]
    if opening.strip():
        lines += [opening.strip(), ""]
    if techniques:
        lines += ["## 这套怎么写（发挥方向）", ""]
        lines += [f"- {t}" for t in techniques]
        lines.append("")
    if examples:
        lines += ["## 风格样例", ""]
        for i, ex in enumerate(examples, 1):
            lines.append(f"> **示例{i}·{ex.get('label', '')}**")
            lines.append(f"> {ex.get('text', '')}")
            lines.append("")
    if taboos:
        lines += ["## 这套忌讳", ""]
        lines += [f"- {t}" for t in taboos]
        lines.append("")
    return "\n".join(lines).strip()


def _extract_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def is_static_preset(preset_id: str) -> bool:
    """True iff preset_id is a static hand-written card under one of _static_prose_style_dirs()
    (built-in skills/prose-styles/, or an enabled content pack's contributed dir). Static
    presets are never writable by the write/edit chat tools -- callers guard on this before
    touching disk."""
    return any(
        os.path.exists(os.path.join(d, f"{preset_id}.md")) for d in _static_prose_style_dirs()
    )


def load_preset_card(preset_id: str) -> str:
    for d in _static_prose_style_dirs():
        card = _read(os.path.join(d, f"{preset_id}.md"))
        if card:
            return card
    return _read(os.path.join(prose_styles_dir(), f"{preset_id}.md"))


def read_active_prose_style_config() -> dict[str, str]:
    import sqlite3

    try:
        from repositories.sqlite_store import SqliteStore
        from utils.paths import active_novel_id

        settings = SqliteStore(active_novel_id()).get_doc("novel_settings", "")
        ps = settings.get("prose_style") if isinstance(settings, dict) else None
        ps = ps if isinstance(ps, dict) else {}
        preset = ps.get("preset") or default_prose_style_preset()
        return {
            "preset": preset,
            "custom_addendum": ps.get("custom_addendum") or "",
        }
    except (sqlite3.Error, TypeError):
        return {
            "preset": default_prose_style_preset(),
            "custom_addendum": "",
        }


def build_active_prose_style_card() -> str:
    cfg = read_active_prose_style_config()
    #顺序：preset 调色 → custom 压轴。正面底座已退役；防 AI 腔改走 style_guard.py 机械句式护栏。
    parts = [
        load_preset_card(cfg["preset"]),
        cfg["custom_addendum"],
    ]
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def list_prose_style_presets() -> list[dict[str, str]]:
    """Scan _static_prose_style_dirs() (built-in skills/prose-styles/ + enabled content packs'
    contributed dirs) + data/prose_styles/*.md (auto/chat-generated) and return
    [{id, title, origin}]; title is extracted from the card's first `# ` line, falling back to
    the filename. origin is "static" (protected, never writable) or "custom" (editable via
    edit_prose_style_preset -- covers both novel-import auto-<id>.md and agent-authored cards,
    they're equivalent for write/edit purposes). Same-id collisions across static dirs keep the
    earlier dir's entry (built-in wins over a content pack), mirroring skills.py's registry
    merge convention."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for base_dir in _static_prose_style_dirs():
        try:
            names = sorted(f for f in os.listdir(base_dir) if f.endswith(".md"))
        except OSError:
            continue
        for name in names:
            preset_id = name[:-3]
            if preset_id in seen:
                continue
            seen.add(preset_id)
            content = _read(os.path.join(base_dir, name))
            out.append({"id": preset_id, "title": _extract_title(content, preset_id), "origin": "static"})
    try:
        names = sorted(f for f in os.listdir(prose_styles_dir()) if f.endswith(".md"))
    except OSError:
        names = []
    for name in names:
        preset_id = name[:-3]
        content = _read(os.path.join(prose_styles_dir(), name))
        out.append({"id": preset_id, "title": _extract_title(content, preset_id), "origin": "custom"})
    return out
