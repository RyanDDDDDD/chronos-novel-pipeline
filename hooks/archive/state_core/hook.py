"""state/gender/address_ref delta hook：自带 state_builder/cold_start 框架 + 滚动种子/冷启动大纲。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engine.archive.archive_hook import ArchiveDeltaContext, ArchiveDeltaHook

_HOOKS_DIR = Path(__file__).parent
#Static prompt assets never change at runtime -- read once at import instead of on every
#StateCoreHook() instantiation (a new instance is created each time AgentPluginLoader
#re-resolves the hook, e.g. across validator script runs).
_STATE_PROMPT = (_HOOKS_DIR / "state_builder.md").read_text(encoding="utf-8")
_COLDSTART_PROMPT = (_HOOKS_DIR / "cold_start.md").read_text(encoding="utf-8")


def _normalize_state(value: Any) -> dict:
    """
规范 state 字段：确保为 dict。"""

    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    return {}


class StateCoreHook(ArchiveDeltaHook):
    name = "state"
    fields = ["state", "gender", "address_ref", "self_ref"]

    def __init__(self) -> None:
        self._state_prompt = _STATE_PROMPT
        self._coldstart_prompt = _COLDSTART_PROMPT
        from utils.paths import story_character_config_path, world_bible_path

        story_cfg_path = Path(story_character_config_path())
        self._story_config: dict = {}
        if story_cfg_path.exists():
            with open(story_cfg_path, encoding="utf-8") as f:
                self._story_config = json.load(f)

        # 题材基调（per-novel）：称呼/自称的用词风格据此定，引擎不预设题材。
        self._tone: str = ""
        self._core_themes: list[str] = []
        try:
            with open(world_bible_path(), encoding="utf-8") as f:
                wb = json.load(f)
            self._tone = str(wb.get("tone") or "")
            themes = wb.get("core_themes")
            self._core_themes = [
                str(t.get("name", "")).strip() for t in themes if isinstance(t, dict) and t.get("name")
            ] if isinstance(themes, list) else []
        except (OSError, json.JSONDecodeError):
            pass

    def _story_ext(self, ctx: ArchiveDeltaContext) -> dict[str, Any]:
        ext = self._story_config.get(ctx.char["name"], {})
        return ext if isinstance(ext, dict) else {}

    def _tone_grounding(self) -> str:
        """本作基调 grounding：称呼/自称用词风格的唯一来源（题材中性，引擎不预设题材）。"""

        if not self._tone and not self._core_themes:
            return ""
        lines = ["## 本作基调（称呼/自称用词风格据此定，引擎不预设题材）"]
        if self._tone:
            lines.append(f"tone：{self._tone}")
        if self._core_themes:
            lines.append("core_themes：" + "、".join(self._core_themes))
        return "\n".join(lines)

    def _rolling_fragment(self, ctx: ArchiveDeltaContext) -> str:
        from engine.archive.sliders import axes_of, character_rubrics, render_slider

        name = ctx.char["name"]
        rubrics = character_rubrics(name)
        story_ext = self._story_ext(ctx)
        parts = [self._state_prompt]

        story_block = (
            "## 故事专属设定\n"
            + (json.dumps(story_ext, ensure_ascii=False, indent=2) if story_ext else "（无）")
        )
        parts.append(story_block)

        tone_block = self._tone_grounding()
        if tone_block:
            parts.append(tone_block)

        rel_block = self._relationship_block(ctx.char.get("name", ""), ctx.chapter_roster)
        if rel_block:
            parts.append(rel_block)

        if ctx.prior:
            ps = ctx.prior.get("sliders", {})
            slider_txt = "；".join(
                f"{ax}：{render_slider(rubrics, ax, ps[ax])}"
                for ax in axes_of(rubrics) if ax in ps
            )
            st = ctx.prior.get("state", {})
            seed_block = (
                "## 上一 stage 解析快照（滚动种子）\n"
                f"gender：{ctx.prior.get('gender', '（无）')}\n"
                f"self_ref：{json.dumps(ctx.prior.get('self_ref', '（无）'), ensure_ascii=False)}\n"
                f"address_ref：{json.dumps(ctx.prior.get('address_ref', '（无）'), ensure_ascii=False)}\n"
                f"physique：{json.dumps(ctx.prior.get('physique', {}), ensure_ascii=False)}\n"
                f"滑块：{slider_txt or '（无）'}\n"
                f"physiology：{st.get('physiology', '（无）')}\n"
                f"psychology：{st.get('psychology', '（无）')}"
            )
        else:
            seed_block = "## 上一 stage 解析快照（滚动种子）\n（首次出场，无种子——以 lore 初始值为起点）"
        parts.append(seed_block)
        parts.append(
            "请按规范输出该角色本章各 stage 的变化量 delta JSON（含 thought_process / delta，仅输出 JSON）。"
        )
        return "\n\n".join(parts)

    def _cold_start_fragment(self, ctx: ArchiveDeltaContext) -> str:
        from engine.archive.sliders import axes_of, character_rubrics, render_slider

        name = ctx.char["name"]
        role = str(ctx.char.get("role") or "")
        rubrics = character_rubrics(name)
        anchors = ctx.char.get("causal_anchors", {})
        init = ctx.char.get("sliders", {})
        story_ext = self._story_ext(ctx)

        def _slider_level(axis: str) -> int:
            val = init.get(axis)
            if isinstance(val, dict):
                return int(val.get("level", 0))
            if isinstance(val, int):
                return val
            return 0

        init_txt = "；".join(
            f"{ax}：{render_slider(rubrics, ax, _slider_level(ax))}"
            for ax in axes_of(rubrics)
        )
        anchor_lines = [
            f"{k}：{v}" for k, v in anchors.items() if str(v).strip()
        ]
        outline = "\n".join(
            f"- 第{a['chapter']}章：{a['description']}" for a in ctx.prior_appearances
        ) or "（无历史出场）"

        story_block = (
            "## 故事专属设定\n"
            + (json.dumps(story_ext, ensure_ascii=False, indent=2) if story_ext else "（无）")
        )

        # lore 初始称呼底色（可选，单值）：作为 per-target 称呼推演的起点，题材/性别中性
        addr_ref_block = ""
        lore_addr = ctx.char.get("address_ref")
        if lore_addr:
            addr_ref_block = (
                "## 初始称呼底色（lore）\n"
                f"lore 给的初始专属称呼底色：「{lore_addr}」——以此为底色，按下方历史经历，"
                "为有特殊称呼的关系对象分别推演到此刻的演变叫法（per-target，语气随关系演变）。"
            )

        parts = [
            self._coldstart_prompt,
            f"## 因果锚点（{role or '未设定'}）\n" + "\n".join(anchor_lines),
            f"## 登场起点滑块\n{init_txt}",
            story_block,
        ]
        tone_block = self._tone_grounding()
        if tone_block:
            parts.append(tone_block)
        rel_block = self._relationship_block(name, ctx.chapter_roster)
        if rel_block:
            parts.append(rel_block)
        if addr_ref_block:
            parts.append(addr_ref_block)
        parts.append("## 历史经历大纲（从登场起点到此刻）\n" + outline)
        parts.append(
            f"请基于其人设底线，阅读以上她过去经历的事件大纲，直接推演出她【第 {ctx.chapter} 章本章开局】"
            "此刻相对 lore 初始值的**全字段累积 delta**。仅输出 JSON。"
        )
        return "\n\n".join(parts)

    def _relationship_block(self, name: str, roster: list[str]) -> str:
        """
本段角色关系块：静态社交关系（师徒/姐妹等），按本章在场名单过滤。

        roster=本章在场名单（过滤用）。无关系 → ''（降级，回退原推断）。具体渲染逻辑在
        social_relations.relations_for_character。"""

        if not name:
            return ""
        from hooks.archive.social_relations.social_relations import relations_for_character

        return relations_for_character(name, roster)

    def prompt_fragment(self, ctx: ArchiveDeltaContext) -> str:
        if ctx.mode == "cold_start":
            return self._cold_start_fragment(ctx)
        return self._rolling_fragment(ctx)

    def parse(self, field: str, raw_value, ctx: ArchiveDeltaContext):
        from context.dialogue.scene_aware import as_target_pool_map

        if field == "state":
            return _normalize_state(raw_value)
        if field == "self_ref":
            # per-target 自称映射；旧 list/str 收成 _default 基线池
            return as_target_pool_map(raw_value, legacy_default_key="_default")
        if field == "address_ref":
            # per-target 称呼映射；旧裸值无目标 → 丢弃（旧档需重生成）
            return as_target_pool_map(raw_value, legacy_default_key=None)
        return raw_value
