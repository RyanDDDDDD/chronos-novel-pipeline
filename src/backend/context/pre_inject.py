"""Context injection helper function."""
import json
from typing import Any

_MISSING = object()  #narrow_archive_stages path missing sentinels (different from legal None/"" values)

_LABEL_MAP = {
    "outline": "剧情大纲",
    "character_archive": "角色专属档案（含各 Stage 状态）",
    "physique": "角色体质",
    "dialogue_scaffolding": "角色互称",
}


def format_context(data: dict, extra_labels: dict[str, str] | None = None) -> str:
    """
Format the data dictionary as injected text. extra_labels has higher priority than the built-in LABEL_MAP."""
    label_map = {**_LABEL_MAP, **(extra_labels or {})}
    sections: list[str] = []

    for key, val in data.items():
        label = label_map.get(key, key)
        if isinstance(val, dict):
            parts = [f"## {label}"]
            for k, v in val.items():
                parts.append(f"### {k}\n{v}")
            sections.append("\n\n".join(parts))
        else:
            sections.append(f"## {label}\n{val}")

    return "\n\n---\n\n".join(sections)


def apply_fields(text: str, fields: list[str]) -> str:
    """JSON field clipping: only keep the keys specified in fields. Non-JSON text is returned unchanged."""
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text
    if isinstance(parsed, list):
        parsed = [{f: obj[f] for f in fields if f in obj} for obj in parsed]
    elif isinstance(parsed, dict):
        parsed = {f: parsed[f] for f in fields if f in parsed}
    return json.dumps(parsed, ensure_ascii=False)


def filter_for_segment(data: dict, seg_chars: list[str]) -> dict:
    """
Clip per-character data by paragraph character list, retaining only keys for characters who appear."""
    result: dict = {}
    for key, val in data.items():
        if isinstance(val, dict) and val:
            filtered = {k: v for k, v in val.items() if str(k) in seg_chars}
            result[key] = filtered if filtered else val
        else:
            result[key] = val
    return result


def narrow_archive_stages(pi_data: dict, keep_paths: list[str]) -> dict:
    """Narrow each character_archive entry to only the specified point-path subfields --
    archive.json is flat (one profile per chapter, no per-stage nesting), so this narrows the
    whole entry directly."""

    arch = pi_data.get("character_archive")
    if not isinstance(arch, dict):
        return pi_data
    trimmed: dict = {}
    for char, raw in arch.items():
        try:
            a = json.loads(raw) if isinstance(raw, str) else raw
            narrowed: dict = {}
            for path in keep_paths:
                parts = path.split(".")
                src: Any = a
                for p in parts:
                    if isinstance(src, dict) and p in src:
                        src = src[p]
                    else:
                        src = _MISSING
                        break
                if src is _MISSING:
                    continue
                dst = narrowed
                for p in parts[:-1]:
                    dst = dst.setdefault(p, {})
                dst[parts[-1]] = src
            trimmed[char] = json.dumps(narrowed, ensure_ascii=False) if isinstance(raw, str) else narrowed
        except Exception:
            trimmed[char] = raw
    return {**pi_data, "character_archive": trimmed}


def filter_archive_to_stage(pi_data: dict, stage: int) -> dict:  # noqa: ARG001
    """No-op under the flat archive model: archive.json already holds exactly one profile per
    chapter (write_character_archive always resolves at stage=1), so there is no per-stage
    selection left to make. `stage` is accepted only for call-site compatibility."""
    return pi_data


def stage_genders_from_pi(pi_data: dict, chars: list[str], stage: int) -> dict[str, str]:  # noqa: ARG001
    """Get each character's gender from pi_data's (flat) character_archive."""

    arch = pi_data.get("character_archive")
    if not isinstance(arch, dict):
        return {}
    out: dict[str, str] = {}
    for char in chars:
        raw = arch.get(char)
        if raw is None:
            continue
        try:
            obj = json.loads(raw) if isinstance(raw, str) else raw
            g = obj.get("gender")
            if g:
                out[char] = str(g)
        except Exception:
            continue
    return out

