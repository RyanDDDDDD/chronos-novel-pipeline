"""Unify delta calls: combine each hook fragment → one LLM → send back each hook parse. Zero knowledge of the subject matter."""
from __future__ import annotations

import json
from typing import Any

from engine.archive.archive_hook import ArchiveDeltaContext


def _normalize_thought_process(tp: Any) -> dict:
    """Specification thought_process: LLM occasionally outputs strings, and verification requires dict."""
    if tp is None:
        return {}
    if isinstance(tp, dict):
        return tp
    if isinstance(tp, str):
        s = tp.strip()
        return {"delta": s} if s else {}
    return {}


def _delta_hooks(hooks: list | None) -> list:
    if hooks is not None:
        return hooks
    from engine.archive.hook_loader import DELTA_HOOKS

    return DELTA_HOOKS


def _build_system(ctx: ArchiveDeltaContext, hooks: list | None = None) -> str:
    hooks = _delta_hooks(hooks)
    if ctx.mode == "cold_start":
        envelope = "只输出纯 JSON，不要任何解释或代码块。\n"
    else:
        envelope = (
            "只输出纯 JSON，不要任何解释或代码块。顶层：\n"
            '{"stages": {"<stage_num>": {"thought_process": {...}, "delta": {...}}}}\n'
        )
    fragments = "\n\n".join(
        f for h in hooks if (f := h.prompt_fragment(ctx))
    )
    return envelope + "\n\n" + fragments


def _build_user(ctx: ArchiveDeltaContext, hooks: list | None = None) -> str:
    hooks = _delta_hooks(hooks)
    anchors = json.dumps(ctx.char.get("causal_anchors", {}), ensure_ascii=False)
    header = f"## 角色：{ctx.char['name']}\n## 因果锚点\n{anchors}\n"
    if ctx.extra_grounding:
        header += f"## 角色背景设定\n{ctx.extra_grounding}\n"
    if ctx.mode == "cold_start":
        return header
    blocks = []
    for s in ctx.relevant_stages:
        extra = "\n".join(f for h in hooks if (f := h.stage_fragment(ctx, s)))
        blocks.append(
            f"### Stage {s['stage_num']}（{s.get('location', '')}）\n"
            f"本场剧情事件：{s.get('description', '（无）')}" + (f"\n{extra}" if extra else "")
        )
    return header + "\n## 本章各 Stage\n" + "\n\n".join(blocks)


def _dispatch_parse(delta_in: dict, ctx: ArchiveDeltaContext, hooks: list | None = None) -> dict:
    hooks = _delta_hooks(hooks)
    owner = {f: h for h in hooks for f in h.fields}
    delta_out: dict = {}
    for field, val in delta_in.items():
        h = owner.get(field)
        delta_out[field] = h.parse(field, val, ctx) if h else val
    return delta_out


async def run_state_delta_call(ctx: ArchiveDeltaContext) -> dict:
    from engine.archive.hook_loader import DELTA_HOOKS

    return await _run_delta_call(ctx, DELTA_HOOKS)


async def _run_delta_call(ctx: ArchiveDeltaContext, hooks: list) -> dict:
    """Returns {sid: {"thought_process":..., "delta": {field: parsed}}}."""
    assert ctx.call_llm is not None
    label = (
        f"{ctx.char['name']} ch{ctx.chapter} [coldstart]"
        if ctx.mode == "cold_start"
        else f"{ctx.char['name']} ch{ctx.chapter} [state]"
    )
    raw = await ctx.call_llm(_build_system(ctx, hooks), _build_user(ctx, hooks), label)
    out: dict[str, dict] = {}

    if ctx.mode == "cold_start":
        delta_in = dict(raw.get("delta") or {})
        if not delta_in:
            delta_in = {
                k: raw[k]
                for k in ("sliders", "state", "gender", "physique", "clothing", "address_ref", "self_ref")
                if k in raw
            }
        out["1"] = {"thought_process": {}, "delta": _dispatch_parse(delta_in, ctx, hooks)}
        return out

    for sid, entry in (raw.get("stages") or {}).items():
        delta_in = dict(entry.get("delta") or {})
        out[str(sid)] = {
            "thought_process": _normalize_thought_process(entry.get("thought_process")),
            "delta": _dispatch_parse(delta_in, ctx, hooks),
        }
    return out
