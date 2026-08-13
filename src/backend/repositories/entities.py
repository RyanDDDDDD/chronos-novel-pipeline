"""Data access layer business entities (thin envelope + open payload).

The data has a stable outer layer + a data-driven open inner layer (physique/clothing/sliders and other keys come from the setting layer data,
And prompt is consumed in JSON). Therefore, only stable fields are typed, and open areas are inherited with extra="allow" to avoid over-modelling."""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


class Character(BaseModel):
    """
Role lore business object (fold starting point; remaining lore fields are open for inheritance)."""
    model_config = ConfigDict(extra="allow")
    name: str
    gender: str | None = None
    extensions: dict[str, Any] = {}


class Stage(BaseModel):
    """Chapter outline single stage."""
    model_config = ConfigDict(extra="allow")
    index: int
    title: str = ""
    location: str = ""
    text: str = ""
    stage_num: int
    skeleton: str = ""
    clothing: dict[str, Any] = {}


class ChapterOutline(BaseModel):
    """
Chapter Outline Business Object."""
    model_config = ConfigDict(extra="allow")
    chapter: int
    title: str | None = None
    stages: list[Stage] = []

    @model_validator(mode="before")
    @classmethod
    def populate_stage_indices(cls, data: Any) -> Any:
        if isinstance(data, dict) and "stages" in data and isinstance(data["stages"], list):
            for i, stage in enumerate(data["stages"]):
                if isinstance(stage, dict) and "index" not in stage:
                    stage["index"] = i
        return data


class CharacterArchive(BaseModel):
    """One character's resolved snapshot for one chapter -- flat: base identity fields (role/
    causal_anchors/...) and resolved profile fields (sliders/gender/physique/personality/...)
    sit side by side at the top level, no per-stage nesting. extra=allow carries every field
    through untyped since the exact field set is data-driven (see archive_fields.py)."""
    model_config = ConfigDict(extra="allow")
    name: str
    chapter: int


class ResearchCategory(StrEnum):
    """Which shape of imported-novel fact a ResearchChunk holds -- lets retrieval tools
    filter vector-store metadata exactly instead of sniffing the `topic` string convention."""
    WORLD = "world"
    CHARACTER = "character"
    PLOT = "plot"


class ResearchChunk(BaseModel):
    """Set the study library hit fragment."""
    text: str = ""
    topic: str = ""
    source: str = ""
    category: str = ""
    score: float | None = None
    mention_count: int = 1


class MemoryOrigin(StrEnum):
    """Which side of the app wrote an event-memory entry -- gates recall visibility symmetrically
    (see recall.py::recall_relevant_context and event_log.py::entries_in_scope)."""
    SANDBOX = "sandbox"
    AUTHOR_LOOP = "author_loop"


class SandboxMemoryHit(BaseModel):
    """One story_sandbox vector-memory semantic-recall hit."""
    id: str = ""
    chapter: int = 0
    turn_index: int = 0
    time: str = ""
    location: str = ""
    summary: str = ""
    entities: list[str] = []
    characters: list[str] = []
    branch_id: str = ""  # "" = canon (author_loop-archived or pre-branching-feature entry)
    origin: str = ""  # "" = legacy entry predating this field, treated as MemoryOrigin.SANDBOX
