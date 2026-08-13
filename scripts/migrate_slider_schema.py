"""One-shot migration: fold old role-keyed world/character_schema.json rubrics into each
character's own sliders[axis].levels where the axis name matches that character's declared
role in the old schema. Axes that don't match anything in the old schema are left alone --
they get backfilled the next time someone touches that character via edit_character (same
tolerance as the rest of the codebase's handling of legacy slider shapes). See
docs/superpowers/specs/2026-07-30-per-character-slider-schema-design.md.

Run against real novel data AFTER this change has merged to dev, from the main checkout --
data/novels/ is gitignored and does not exist in a fresh worktree/Cursor dispatch checkout.
"""
from __future__ import annotations

import argparse
import json
import os


def _load_json(path: str) -> object:
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: str, data: object) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def migrate_novel(novel_dir: str) -> dict[str, list[tuple[str, str]]]:
    """Returns {"migrated": [(character_name, axis), ...], "skipped": [(character_name, axis), ...]}."""
    schema = _load_json(os.path.join(novel_dir, "world", "character_schema.json"))
    roles = (schema or {}).get("roles") if isinstance(schema, dict) else {}
    roles = roles if isinstance(roles, dict) else {}

    lore_path = os.path.join(novel_dir, "lore", "character_lore_library.json")
    characters = _load_json(lore_path)
    if not isinstance(characters, list):
        return {"migrated": [], "skipped": []}

    migrated: list[tuple[str, str]] = []
    skipped: list[tuple[str, str]] = []
    changed = False

    for char in characters:
        if not isinstance(char, dict):
            continue
        name = str(char.get("name") or "")
        role = str(char.get("role") or "")
        sliders = char.get("sliders")
        if not isinstance(sliders, dict):
            continue
        role_sliders = (roles.get(role) or {}).get("sliders") if isinstance(roles.get(role), dict) else {}
        role_sliders = role_sliders if isinstance(role_sliders, dict) else {}
        for axis, val in sliders.items():
            if not isinstance(val, dict):
                continue
            if isinstance(val.get("levels"), dict):
                continue  # already migrated, leave untouched
            axis_def = role_sliders.get(axis)
            levels = axis_def.get("levels") if isinstance(axis_def, dict) else None
            if isinstance(levels, dict) and levels:
                val["levels"] = levels
                migrated.append((name, axis))
                changed = True
            else:
                skipped.append((name, axis))

    if changed:
        _save_json(lore_path, characters)

    return {"migrated": migrated, "skipped": skipped}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "novels_dir", nargs="?", default="data/novels",
        help="Directory containing one subdirectory per novel (default: data/novels)",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.novels_dir):
        print(f"未找到 {args.novels_dir}，无小说可迁移。")
        return

    for entry in sorted(os.listdir(args.novels_dir)):
        novel_dir = os.path.join(args.novels_dir, entry)
        if not os.path.isdir(novel_dir) or entry == ".trash":
            continue
        result = migrate_novel(novel_dir)
        if result["migrated"] or result["skipped"]:
            print(f"[{entry}] 迁移 {len(result['migrated'])} 轴，跳过 {len(result['skipped'])} 轴")
            for name, axis in result["skipped"]:
                print(f"  待人工/edit_character 补齐: {name}.{axis}")


if __name__ == "__main__":
    main()
