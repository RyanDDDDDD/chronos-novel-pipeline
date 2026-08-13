"""scripts/migrate_prose_style_json_to_md.py

One-off migration: converts legacy JSON-format auto-generated prose style presets
(data/prose_styles/auto-<novel_id>.json) into the new full markdown card format
(auto-<novel_id>.md), isomorphic to the static presets in skills/prose-styles/*.md.
engine.execution.prose_style.load_preset_card/list_prose_style_presets now only recognize
.md and no longer read .json -- this script salvages the old rules+samples into a minimal
card (title + opening + examples only; techniques/taboos left empty, since the legacy data
has nothing to fill them with), then deletes the old .json.
See docs/superpowers/specs/2026-07-22-prose-style-card-unification-design.md for details.

Usage: uv run python scripts/migrate_prose_style_json_to_md.py
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re

from engine.execution.prose_style import render_prose_style_card
from utils.paths import prose_styles_dir

_NAME_WRAPPER_RE = re.compile(r"^《(.+)》风格$")
_MAX_MIGRATED_EXAMPLES = 5


def convert_legacy_preset(data: dict) -> dict:
    """Reshape a legacy {id,name,rules,samples} preset dict into
    render_prose_style_card's keyword args (title/opening/techniques/examples/taboos)."""
    name = str(data.get("name") or "").strip()
    m = _NAME_WRAPPER_RE.match(name)
    title = m.group(1) if m else (name or str(data.get("id") or ""))
    opening = str(data.get("rules") or "").strip()
    examples: list[dict[str, str]] = []
    samples = data.get("samples") or {}
    for cat, texts in samples.items():
        if not isinstance(texts, list):
            continue
        for text in texts:
            if len(examples) >= _MAX_MIGRATED_EXAMPLES:
                break
            if isinstance(text, str) and text.strip():
                examples.append({"label": cat, "text": text.strip()})
    return {"title": title, "opening": opening, "techniques": [], "examples": examples, "taboos": []}


def migrate_prose_style_json_to_md() -> dict[str, str]:
    """Convert every data/prose_styles/*.json into a same-name .md and delete the
    .json. Returns {old_json_filename: new_md_filename} for files actually migrated."""
    migrated: dict[str, str] = {}
    for path in sorted(glob.glob(os.path.join(prose_styles_dir(), "*.json"))):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        fields = convert_legacy_preset(data)
        card = render_prose_style_card(**fields)
        md_path = path[: -len(".json")] + ".md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(card)
        os.remove(path)
        migrated[os.path.basename(path)] = os.path.basename(md_path)
    return migrated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    migrated = migrate_prose_style_json_to_md()
    if not migrated:
        print("没有找到旧格式 .json 预设，无需迁移。")
        return
    print(f"已迁移 {len(migrated)} 份文风预设：")
    for old, new in migrated.items():
        print(f"  - {old} → {new}")


if __name__ == "__main__":
    main()
