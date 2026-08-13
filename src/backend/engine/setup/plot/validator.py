"""Plot setup hard verification: Thin package already has validate_plot, which is completely consistent with the production and consumption of downstream chapters."""
from __future__ import annotations

import math

from engine.validator.plot_validator import validate_plot

WORDS_PER_BEAT = 350   # midpoint of skeleton-expansion's 200-500-word-per-beat guideline
BEATS_PER_STAGE = 5    # default beat budget per stage, keeps a single author_loop
                        # stage-batch generation from sprawling across too many beats


def suggested_min_stage_count(target_words: int) -> int:
    """Hard floor on how many stages a chapter must be split into, given its word-count
    target. Enforced by validate_plot_chapters -- a chapter with fewer stages is rejected,
    not merely warned."""
    total_beats = max(1, round(target_words / WORDS_PER_BEAT))
    return max(1, math.ceil(total_beats / BEATS_PER_STAGE))


def validate_plot_chapters(
    chapters: list[dict],
    *,
    character_names: list[str],
) -> list[str]:
    """Verify the plot_library array and return an error description list (empty = legal).

    validate_plot requires plot_map ({chapter: chapter}) and char_map ({name: any}); here it is constructed based on setup data."""
    from engine.modes.author_loop_skill_prefs import DEFAULT_TARGET_WORDS, load_dialogue_prefs

    plot_map = {c["chapter"]: c for c in chapters if isinstance(c.get("chapter"), int)}
    char_map: dict[str, dict] = {n: {} for n in character_names}
    errs = [str(e) for e in validate_plot(plot_map, char_map)]

    target_words = load_dialogue_prefs().get("target_words", DEFAULT_TARGET_WORDS)
    suggested = suggested_min_stage_count(target_words)
    for c in chapters:
        stages = c.get("stages") or []
        if not stages:
            errs.append(f"ch{c.get('chapter')} 无 stages（至少需 1 个 stage）")
        elif len(stages) < suggested:
            errs.append(
                f"ch{c.get('chapter')} 仅 {len(stages)} 段，按当前字数目标"
                f"（{target_words} 字/章）至少需要 {suggested} 段"
            )
    return errs
