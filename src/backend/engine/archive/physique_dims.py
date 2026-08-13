"""physique subfield legality guardrail: limit delta subfield ⊆ character base part slot.

Alienation (alienation organs/patterns, etc.) is no longer an independent dimension, but a description text written into a fixed part slot (intimate/face/chest...);
The amount of progress is managed by sliders. This guardrail only prevents new fields (such as a top-level custom organ field) outside the LLM self-created part slot to avoid cross-chapter field name drift."""
from __future__ import annotations

from typing import Any


def allowed_physique_keys(lore_physique: dict[str, Any] | None) -> set[str]:
    """
Legal physique delta key set = character lore base part slot key."""
    return set((lore_physique or {}).keys())


def validate_physique_delta(
    physique: dict[str, Any], allowed: set[str]
) -> tuple[dict[str, Any], list[str]]:
    """Eliminate physique subfields that are not in the allowed set and return (clean, warnings).

    - allowed is the empty set (the character has no basic physique) → regarded as not being verified and returned as is (downgraded).
    - Retain legal subfields with value None (null = alienation regression/removal, handled by fold_delta)."""

    if not allowed:
        return dict(physique), []
    clean: dict[str, Any] = {}
    warnings: list[str] = []
    for k, v in physique.items():
        if k in allowed:
            clean[k] = v
        else:
            warnings.append(
                f"[护栏] physique 未知子字段「{k}」已丢弃（不在基础部位槽内，异化请写进对应部位槽描述）"
            )
    return clean, warnings


_BASE_SLOT_ANNOTATIONS: dict[str, str] = {
    "体型": "整体体型轮廓：身高、骨架、体态比例；以及头部附肢与非人类/兽化特征（耳/角/尾/翼等长在头上或体外的非躯体部位，均归此槽描述）",
    "肌肤": "皮肤与体表：肤色、质感、纹理、伤痕、体表标记",
    "面部": "面部：五官（结构恒定）+ 神态/表情（随 state.psychology 心理演进，勿停在初始冷傲）",
    "胸部": "胸部区域：胸型、轮廓比例",
    "腰腹": "腰腹：腰线、腹部、核心躯干",
    "臀部": "臀部：臀型、肌肉与脂肪分布",
    "四肢": "四肢：手臂、腿部、手足",
    "体格": "体格：肌肉量、力量感、躯干块面",
    "手部": "手部：手掌、手指、指甲",
}


def _slot_annotations() -> dict[str, str]:
    """基线注释 + 已激活内容包贡献的注释（如私处/生殖器）合并。"""
    from context.content_packs import slot_annotations as _pack_annotations
    merged = dict(_BASE_SLOT_ANNOTATIONS)
    merged.update(_pack_annotations())
    return merged


def render_physique_prompt(
    base: dict[str, Any] | None, current: dict[str, Any] | None
) -> str:
    """
Render physique parts slot structure fragments (used by system to unify delta calls).

    Only expose the "structure" - which fixed parts slots the character has + the current description of each slot - do not write any theme/narrative semantics;
    Based on this, LLM merges the shape/state changes into semantically appropriate slots instead of self-made slot foreign keys (self-made keys will be discarded by the guardrail → the state is lost).

    - enum key set = base key (= guardrail allowed set SSOT, ensure prompt is consistent with discard caliber).
    - Per-key display description: Prioritize current (rolling fold snapshot) with the same key value, if missing, fall back to the base value.
    - Each key comes with semantic annotations (_slot_annotations) to guide LLM into assigning changes to the correct slot.
    - base empty → returns "" (aligned with the guardrail "allowed empty means no verification", no constraints are issued)."""

    base = base or {}
    if not base:
        return ""
    cur = current or {}
    lines: list[str] = []
    for k, v in base.items():
        desc = cur.get(k, v)
        ann = _slot_annotations().get(k)
        if ann:
            lines.append(f"- {k}（{ann}）: {desc}")
        else:
            lines.append(f"- {k}: {desc}")
    return (
        "## 体貌部位槽（physique）\n"
        "physique 为固定部位槽结构。delta.physique 只能使用以下键；每个值为该槽的"
        "【完整新描述文本】（在当前描述基础上改写）。外形/状态变化请并入语义最贴合的槽，"
        "禁止新增槽外的键。\n"
        "【只收持久特征，排除瞬时场景态】physique 是跨章累积的稳定底子，只描述与具体场景无关、"
        "会一直跟着角色的肉体特征：体型骨架比例、肤色肤质、恒定的异化器官/纹样，以及随心理长期"
        "演进的神态气场倾向。严禁写入任何随场景重置的瞬时态——当前姿势/站位（跪/坐/靠墙、"
        "手脚落点）、环境附着物（泥土/草屑/汗渍/尘土）、一次性动作痕迹（磨红/掐白/新添抓痕）、"
        "瞬时应激反应（战栗/后仰/踉跄）：这些属于逐场景滚动的「生理/姿态」层，写进 physique 会被"
        "当成永久特征、错误地带到后续章节。\n"
        "【神态随状态演进】`face` 的神情/表情、`silhouette` 的体态气场是**心理的外在表现**，"
        "须随本 stage 角色的 state.psychology（心理状态）演进改写——**别一直停在初始设定**"
        "（如「神情清冷倔强」「宁折不弯的傲气」）：情绪状态变化时神情应相应松动（眼神失焦/涣散、"
        "初始的冷傲傲气瓦解），与当前心理一致。本 stage 心理较上一 stage 有推进就更新该槽。\n"
        "【注意】physique 仅限描述肉体与生理状态。严禁在其中包含任何服装、配饰、鞋袜等身外之物的描述（服装会在独立环节另行生成）！\n"
        + "\n".join(lines)
    )
