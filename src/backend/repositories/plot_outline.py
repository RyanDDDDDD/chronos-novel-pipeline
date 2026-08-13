"""Chapter outline → segment initial list (pure function except for the scan_characters call,
moved from old plot_outline_provider)."""
from __future__ import annotations


def _stage_character_names(stage: dict) -> list[str]:
    from engine.memory_recall.entity_index import scan_characters

    return scan_characters(str(stage.get("description") or ""))


def stages_to_segments(ch_data: dict) -> tuple[str | None, list]:
    """Chapter outline dict → (title, segment initial list). title contains 'Basic plot summary' or empty → None."""
    raw_title = ch_data.get("title", "")
    title = raw_title if raw_title and "基础剧情概要" not in raw_title else None
    stages = [
        {
            "index": i,
            "title": s.get("title", ""),
            "location": s.get("location", ""),
            "text": s.get("description", ""),
            "stage_num": s.get("stage_num", i + 1),
            "beats": list(s.get("beats") or []),
            "characters": _stage_character_names(s),
        }
        for i, s in enumerate(ch_data.get("stages", []))
    ]
    return title, stages
