"""Archive building plug-in protocol.

The engine only provides "the most basic files + rolling fold + shared infrastructure + arrangement", theme/IP specialization (person, clothing,
Physical dimension...) is made into ArchiveHook: comes with its own configuration loading + comes with its own construction logic, but the engine does not understand its semantics.
Both halves of delta/enrich have been implemented: delta is called uniformly through `run_state_delta_call`, and enrich is called through `ENRICH_HOOKS`."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum


class ArchivePhase(StrEnum):
    """
Archive plug-in role."""

    DELTA = "delta"      #Output per-stage delta → into timeline (Phase 2)
    ENRICH = "enrich"    #Collect resolved snapshots → merge fields into assemble (this issue)


class MergeStrategy(StrEnum):
    """fold is the merging strategy of a field (declared by delta hook)."""

    REPLACE = "replace"                          #Whole replacement (scalar/state)
    DEEP_MERGE_IGNORE_NONE = "deep_ignore_none"  #Deep merge, None ignores retaining original values ​​(sliders)
    DEEP_MERGE_REMOVE_NONE = "deep_remove_none"  #Deep merge, None removes subfields (physique)


@dataclass
class ArchiveDeltaContext:
    """
Required context for delta hook (engine injection)."""

    char: dict
    chapter: int
    relevant_stages: list[dict]
    mode: str                       # "rolling" | "cold_start"
    prior: dict | None              #rolling: previous stage resolved snapshot
    prior_appearances: list         #cold_start: historical appearance outline
    call_llm: Callable[[str, str, str], Awaitable[dict]] | None = None
    extra_grounding: str = ""        #Character-level additional background (such as race settings); empty = no injection
    #This chapter's presence list: the relationship block is filtered accordingly, and only edges of opponents in the same chapter are fed (empty = no filtering, backwards compatibility).
    chapter_roster: list[str] = field(default_factory=list)


@dataclass
class ArchiveEnrichContext:
    """Context required by enrich hook (engine injection; hook does not touch the global)."""

    char: dict
    chapter: int
    relevant_stages: list[dict]
    #Resolved snapshot of each stage (including sliders/state/physique/clothing…). key=str(stage_num).
    resolved_by_stage: dict[str, dict]
    #Constrained LLM caller, routed to engine _call_llm (preserved retries + token metering).
    call_llm: Callable[[str, str, str], Awaitable[dict]]


class ArchiveHook:
    """
Archive building plug-in base class."""

    name: str = ""
    phase: ArchivePhase


class ArchiveEnrichHook(ArchiveHook):
    """Decorate each stage after resolve: return {stage_id: {field: value}}, and the engine merges into assemble."""

    phase = ArchivePhase.ENRICH

    async def enrich(self, ctx: ArchiveEnrichContext) -> dict[str, dict]:
        return {}


class ArchiveDeltaHook(ArchiveHook):
    """
Homogeneous contributors to unified delta calls: contribute prompt snippets + parse own field slices."""

    phase = ArchivePhase.DELTA
    fields: list[str] = []
    merge: dict[str, str] = {}      #{field: MergeStrategy value}; default = REPLACE

    def prompt_fragment(self, ctx: ArchiveDeltaContext) -> str:
        return ""

    def stage_fragment(self, ctx: ArchiveDeltaContext, stage: dict) -> str:
        return ""

    def parse(self, field: str, raw_value, ctx: ArchiveDeltaContext):
        return raw_value
