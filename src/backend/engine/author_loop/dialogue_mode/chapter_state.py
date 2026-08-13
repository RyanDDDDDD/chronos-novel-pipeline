"""Line driver·角色状态:直读 archive(character_timeline)+ lore baseline,按 (chapter,stage) 坐标
折叠。动态态(psychology/posture/clothing/action/demeanor)由运行期 state_derive 推演,不再从
archive 读取; archive 只保留静态/滚动字段(sliders/personality/physique 等)。"""
from __future__ import annotations

from context import character_timeline
from context.character_resolver import resolve_from

from engine.archive.hook_loader import collect_merge_strategies
from engine.author_loop.build import _lore_repo


def resolve_card_state(name: str, chapter: int, stage: int) -> dict:
    """Lore baseline + archive 全部字段按 (chapter,stage) 坐标折叠 → 该坐标解析态。"""
    char = _lore_repo().get_character(name)
    lore = char.model_dump() if char is not None else None
    if not lore:
        return {}
    strategies = collect_merge_strategies()
    snapshots = character_timeline.deltas_upto(name, chapter, stage)
    return resolve_from(lore, snapshots, chapter, stage, strategies)


def render_state_view(dynamic_state: dict) -> str:
    """角色动态态:心理/体态/着装/动作/神态分点列出(静态 physique/personality 不进此视图)。"""
    fields = [
        ("心理", str(dynamic_state.get("psychology") or "").strip()),
        ("体态", str(dynamic_state.get("posture") or "").strip()),
        ("着装", str(dynamic_state.get("clothing") or "").strip()),
        ("动作", str(dynamic_state.get("action") or "").strip()),
        ("神态", str(dynamic_state.get("demeanor") or "").strip()),
    ]
    return "\n".join(f"    - {label}：{val or '（未设定）'}" for label, val in fields)
