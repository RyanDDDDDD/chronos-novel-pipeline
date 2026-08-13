"""Pure functions for field-aware dialogue: address_ref parsing.

No side effects, no LLM, no I/O; called by dialogue_context, individually testable."""
from __future__ import annotations


def _to_pool(v: object) -> list[str]:
    """
Normalize single values/lists into a nulled string pool."""
    items = v if isinstance(v, list) else [v]
    return [str(x).strip() for x in items if x and str(x).strip()]


def as_target_pool_map(
    value: object, *, legacy_default_key: str | None = None
) -> dict[str, list[str] | None]:
    """Canonicalized into a per-target call/self mapping `{object name: [pool]}`.

    - dict: Each value is standardized into list[str] (empty); empty pool keys are discarded; **None is retained as is**
      (Remove signal, cross fold's deep_remove_none consumption).
    - Old list/str (single pool, no target): with `legacy_default_key`, you will get `{key: [pool]}`,
      Otherwise discard (for example, the old address_ref naked value has no target - the old file needs to be regenerated). Only fault-tolerant and dirty-proof data."""

    if isinstance(value, dict):
        out: dict[str, list[str] | None] = {}
        for k, v in value.items():
            if v is None:
                out[str(k)] = None
                continue
            pool = _to_pool(v)
            if pool:
                out[str(k)] = pool
        return out
    if value:
        pool = _to_pool(value)
        if pool and legacy_default_key:
            return {legacy_default_key: pool}
    return {}

