"""Extracts raw token counts from an LLM response's usage_metadata. Pure
token-counting logic, no currency/cost math -- see api/services/token_stats.py
and token_accountant.py for where the resulting counts get persisted."""
from __future__ import annotations


def extract_usage(resp: object) -> tuple[int, int, int]:
    """Get (tokens_in, tokens_out, tokens_cached) from LLM response. Missing usage_metadata → (0,0,0)."""
    usage = getattr(resp, "usage_metadata", None)
    if not isinstance(usage, dict):
        return (0, 0, 0)
    tin = int(usage.get("input_tokens", 0) or 0)
    tout = int(usage.get("output_tokens", 0) or 0)
    details = usage.get("input_token_details")
    cached = int((details or {}).get("cache_read", 0) or 0) if isinstance(details, dict) else 0
    return (tin, tout, cached)
