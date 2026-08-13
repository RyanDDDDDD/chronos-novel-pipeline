"""体貌 delta hook：部位槽结构 prompt 片段 + physique 子字段合法性 guard。

贡献统一 delta 调用的结构片段（枚举槽键与当前描述），并在 parse 阶段丢弃槽外自造键。
"""
from __future__ import annotations

from engine.archive.archive_hook import ArchiveDeltaContext, ArchiveDeltaHook
from loguru import logger


class PhysiqueHook(ArchiveDeltaHook):
    name = "physique"
    fields = ["physique"]
    merge = {"physique": "deep_remove_none"}

    def prompt_fragment(self, ctx: ArchiveDeltaContext) -> str:
        from engine.archive.physique_dims import render_physique_prompt

        current = ctx.prior.get("physique") if (ctx.mode == "rolling" and ctx.prior) else None
        return render_physique_prompt(ctx.char.get("physique"), current)

    def parse(self, field: str, raw_value, ctx: ArchiveDeltaContext):
        from engine.archive.physique_dims import (
            allowed_physique_keys,
            validate_physique_delta,
        )

        if not isinstance(raw_value, dict):
            return raw_value
        allowed = allowed_physique_keys(ctx.char.get("physique"))
        clean, warns = validate_physique_delta(raw_value, allowed)
        for w in warns:
            logger.warning("[BUILD] {} {}", ctx.char.get("name", "?"), w)
        return clean
