"""Slider delta hook: per-character ladder from lore, closed-set gear choices + label→number parsing."""
from __future__ import annotations

from engine.archive.archive_hook import ArchiveDeltaContext, ArchiveDeltaHook


class SlidersHook(ArchiveDeltaHook):
    name = "sliders"
    fields = ["sliders"]
    merge = {"sliders": "deep_ignore_none"}

    def _rubrics(self, ctx: ArchiveDeltaContext) -> dict:
        from engine.archive.sliders import character_rubrics

        return character_rubrics(ctx.char["name"])

    def prompt_fragment(self, ctx: ArchiveDeltaContext) -> str:
        from engine.archive.sliders import axes_of, render_axis_choices

        rubrics = self._rubrics(ctx)
        choices = "\n".join(
            render_axis_choices(rubrics, ax)
            for ax in axes_of(rubrics)
        )
        return "## 滑块档位（必须从以下标签中【原样复制】一个，不得改写/近义替换）\n" + choices

    def parse(self, field: str, raw_value, ctx: ArchiveDeltaContext):
        from engine.archive.sliders import axes_of, parse_slider_label

        rubrics = self._rubrics(ctx)
        if not isinstance(raw_value, dict):
            return {}
        out: dict[str, int | None] = {}
        for ax in axes_of(rubrics):
            if ax in raw_value:
                out[ax] = parse_slider_label(rubrics, ax, str(raw_value[ax]))
        return out
