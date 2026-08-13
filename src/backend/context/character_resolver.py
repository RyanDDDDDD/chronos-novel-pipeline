"""Role file fold parser: lore initial value + accumulated stage level delta = full snapshot of a (chapter, stage).

fold rules (spec §2.2):
  - Scalar fields (gender, etc.): the last delta replaces the previous value.
  - state: overall replacement.
  - dict field (physique/clothing/sliders/address_ref/self_ref): deep merge; subfield value is
    None → Remove this subfield (alienation fades/rolls back; title disappears by object).
Pure functions, deterministic, not dependent on runtime state.

Note: address_ref/self_ref is a per-target mapping (`{object name: [call/self-named pool]}`, self_ref contains
`_default` baseline key), so merge deeply by object - only changed opponent entries are produced in each stage, and unchanged opponents are used."""
from __future__ import annotations

import copy

DEFAULT_MERGE_STRATEGIES: dict[str, str] = {
    "sliders": "deep_ignore_none",
    "physique": "deep_remove_none",
    "address_ref": "deep_remove_none",
    "self_ref": "deep_remove_none",
}


def fold_delta(acc: dict, delta: dict, strategies: dict[str, str] | None = None) -> dict:
    """
Superimpose a delta onto the cumulative snapshot acc and return a new dict (without changing the parameters)."""
    strat = strategies if strategies is not None else DEFAULT_MERGE_STRATEGIES
    out = copy.deepcopy(acc)
    for key, val in delta.items():
        mode = strat.get(key, "replace")
        if mode == "deep_remove_none" and isinstance(val, dict):
            cur = dict(out.get(key) or {})
            for sk, sv in val.items():
                if sv is None:
                    cur.pop(sk, None)
                else:
                    cur[sk] = sv
            out[key] = cur
        elif mode == "deep_ignore_none" and isinstance(val, dict):
            cur = dict(out.get(key) or {})
            for sk, sv in val.items():
                if sv is not None:
                    cur[sk] = sv
            out[key] = cur
        else:
            out[key] = copy.deepcopy(val)
    return out


def resolve_from(
    lore: dict,
    snapshots: list[dict],
    chapter: int,
    stage: int,
    strategies: dict[str, str] | None = None,
) -> dict:
    """Starting from the initial value of lore, accumulate all deltas of (c,s) ≤ (chapter,stage), and return a full snapshot of the coordinates.

    snapshots: [{chapter, stage, delta}, ...] (no pre-sorting required, this function sorts by coordinates)."""

    acc = copy.deepcopy(lore)
    relevant = sorted(
        (s for s in snapshots if (s["chapter"], s["stage"]) <= (chapter, stage)),
        key=lambda s: (s["chapter"], s["stage"]),
    )
    for snap in relevant:
        acc = fold_delta(acc, snap.get("delta") or {}, strategies)
    return acc
