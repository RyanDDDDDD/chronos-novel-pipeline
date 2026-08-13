"""TimelineRepository: Thin package context.character_timeline (per-character stage delta IO).

Physical IO/fold reuses existing modules; this class only collects them into the unified repo entry, eliminating scattered calls from direct import modules."""
from __future__ import annotations

from context import character_timeline


class TimelineRepository:
    def load(self, name: str) -> dict:
        return character_timeline.load_timeline(name)

    def append_stage(self, name: str, chapter: int, stage: int, delta: dict) -> None:
        character_timeline.append_stage(name, chapter, stage, delta)

    def deltas_upto(self, name: str, chapter: int, stage: int) -> list[dict]:
        return character_timeline.deltas_upto(name, chapter, stage)

    def deltas_before(self, name: str, chapter: int, stage: int) -> list[dict]:
        return character_timeline.deltas_before(name, chapter, stage)

    def truncate_from(self, name: str, from_chapter: int) -> int:
        return character_timeline.truncate_from(name, from_chapter)

    def latest_chapter(self, name: str) -> int:
        return character_timeline.latest_chapter(name)

    def list_names(self) -> list[str]:
        return character_timeline.list_timeline_names()
