"""Main author of quality self-review and audit plug-in base class (cognitive layer).

According to the ArchiveHook paradigm: each plug-in declares name/weight/floor/consumes (describe attributes and write hooks,
No need to start a new json), implement build_prompt (spelled as system+user, prompt assets are read from the plug-in directory) + parse
(LLM reply → 1–10 points + feedback). The node (self_review) has no knowledge of plug-ins, adding dimensions = adding plug-ins."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReviewContext:
    """
The context required for a single audit plugin to evaluate a beat (nodes are assembled and passed in by plugin consumes)."""
    beat_intent: str
    base_draft: str            #This is the same "basic draft" that was used for write
    refined: str               #This shot will be finalized after refinement (reviewed subject)
    prev_beat_text: str | None  #The previous shot was finalized; b0 is None
    directive: str             #This beat's produce instructions (for reference, not the main axis of scoring)
    beats: list[dict] | None = None  # this stage's raw beat list (stage axis only); None for the transition axis
    world_text: str | None = None
    world_bible: dict | None = None
    character_card: str | None = None
    character: dict | None = None
    novel_brief: str | None = None


@dataclass
class ReviewScore:
    """Single plug-in scoring results. score is an integer of 1–10; write is returned when feedback fails."""
    score: int
    feedback: str


class ReviewHook:
    """Audit plug-in base class. Subclasses override class attributes + build_prompt/parse,
    or evaluate() for code-only (no-LLM) hooks."""

    name: str = ""
    display_name: str = ""
    weight: float = 0.0
    floor: int = 0

    def __init__(self) -> None:
        #Subclasses are declared with the class attribute consumes=[...]; bare base class instances each have an independent empty list
        if "consumes" not in self.__class__.__dict__:
            self.consumes: list[str] = []

    def build_prompt(self, ctx: ReviewContext) -> tuple[str, str]:
        """Return (system, user). Only called when evaluate() returns None."""
        raise NotImplementedError

    def parse(self, raw: str) -> ReviewScore:
        """Only called when evaluate() returns None."""
        raise NotImplementedError

    def evaluate(self, ctx: ReviewContext) -> ReviewScore | None:
        """Optional code-only scoring path (regex/deterministic checks needing
        no LLM call). Default None -> caller falls back to the
        build_prompt/call_llm/parse LLM round trip. Must be a pure function of
        ctx -- hook instances are process-global singletons reused across
        concurrent asyncio.gather() calls, so stashing per-call state on self
        would race."""
        return None
