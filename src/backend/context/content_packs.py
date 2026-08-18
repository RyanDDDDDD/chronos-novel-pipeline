"""Content pack SSOT: gender/physique/custom-field definitions assembled from
hooks/content_packs/*/hook.py at scan time. Core engine code never imports a
specific pack by name -- it only reads the merged result from this module, so
deleting a pack directory degrades the engine to the built-in baseline instead
of raising an ImportError anywhere."""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from loguru import logger
from utils.cache import LazyCache

StateFieldKind = Literal["text", "scored_desc"]


@dataclass(frozen=True)
class StateFieldSpec:
    """One character-state derivation field; baseline defines five text fields, content packs
    may override derive_hint on the same key or append scored_desc extras."""

    key: str
    label: str
    kind: StateFieldKind
    derive_hint: str


@dataclass(frozen=True)
class CustomFieldSpec:
    """One hook-declared open-ended character field (str-shaped); see individual packs
    under hooks/content_packs/ for concrete examples (e.g. an optional content pack's custom field)."""

    name: str
    required: bool = False
    timeline_delta: bool = False
    description: str | None = None


@dataclass(frozen=True)
class ContentPack:
    """A single hook package's contribution. Every field is optional -- a pack
    may declare only custom_fields, only gender/physique extensions, only skill
    directories, or any combination."""

    extra_genders: list[str] = field(default_factory=list)
    extra_physique_slots_by_gender: dict[str, set[str]] = field(default_factory=dict)
    slot_annotations: dict[str, str] = field(default_factory=dict)
    custom_fields: list[CustomFieldSpec] = field(default_factory=list)
    state_fields: list[StateFieldSpec] = field(default_factory=list)
    setup_chat_skill_dirs: list[str] = field(default_factory=list)
    detail_skill_dirs: list[str] = field(default_factory=list)
    prose_style_dirs: list[str] = field(default_factory=list)
    identity: str | None = None
    portrait_prompt_directive: str | None = None
    prose_style_extraction_prompt: str | None = None
    chapter_direction_guidance: str | None = None
    stage_lens_guidance: str | None = None
    dialogue_intent_guidance: str | None = None


#题材中性通用基线：不依赖任何 content pack 即可工作。
BASELINE_GENDERS: tuple[str, ...] = ("male", "female")
BASELINE_PHYSIQUE_SLOTS: dict[str, frozenset[str]] = {
    "male": frozenset({"体型", "肌肤", "面部", "体格", "手部"}),
    "female": frozenset({"体型", "肌肤", "面部", "胸部", "腰腹", "臀部", "四肢"}),
}

BASELINE_STATE_FIELDS: tuple[StateFieldSpec, ...] = (
    StateFieldSpec("psychology", "心理", "text", "情绪·心理 psychology"),
    StateFieldSpec("posture", "体态", "text", "体态 posture"),
    StateFieldSpec("clothing", "着装", "text", "服装 clothing"),
    StateFieldSpec("action", "动作", "text", "动作 action"),
    StateFieldSpec("demeanor", "神态", "text", "神态 demeanor"),
)


def _packs_dir() -> Path:
    from utils.paths import CONTENT_PACKS_DIR
    return Path(CONTENT_PACKS_DIR)


def _load_pack(hook_path: Path) -> ContentPack | None:
    module_name = f"_content_pack_{hook_path.parent.name}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, hook_path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception as exc:
        logger.warning("[ContentPacks] 加载 {} 失败：{}", hook_path, exc)
        return None
    pack = getattr(mod, "CONTENT_PACK", None)
    if not isinstance(pack, ContentPack):
        logger.warning("[ContentPacks] {} 未定义 CONTENT_PACK，跳过", hook_path)
        return None
    return pack


def scan_content_packs() -> list[ContentPack]:
    """目录扫描 hooks/content_packs/*/hook.py；目录不存在/为空 → []（不报错）。"""
    root = _packs_dir()
    if not root.is_dir():
        return []
    packs: list[ContentPack] = []
    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue
        hook_path = sub / "hook.py"
        if not hook_path.exists():
            continue
        pack = _load_pack(hook_path)
        if pack is not None:
            packs.append(pack)
    return packs


_packs_cache: LazyCache[list[ContentPack]] = LazyCache(scan_content_packs)


def _packs() -> list[ContentPack]:
    return _packs_cache.get()


def reload_content_packs() -> None:
    """清空扫描缓存；测试/切换禁用名单后调用。"""
    _packs_cache.invalidate()


def get_gender_values() -> list[str]:
    values = list(BASELINE_GENDERS)
    for pack in _packs():
        for g in pack.extra_genders:
            if g not in values:
                values.append(g)
    return values


def physique_slots(gender: str) -> set[str]:
    """基础身体槽：gender 是基线（male/female）用其自身；是内容包声明的额外性别
    （如内容包声明的扩展性别）则没有专属身体基线，降级继承 female 的身体槽——否则该性别只剩
    包追加的槽（如私处/生殖器），LLM 没地方写体型/肌肤等，只能全挤进一个字段。"""
    baseline = BASELINE_PHYSIQUE_SLOTS.get(gender) or BASELINE_PHYSIQUE_SLOTS["female"]
    slots = set(baseline)
    for pack in _packs():
        slots |= pack.extra_physique_slots_by_gender.get(gender, set())
    return slots


def slot_annotations() -> dict[str, str]:
    out: dict[str, str] = {}
    for pack in _packs():
        out.update(pack.slot_annotations)
    return out


def active_identity() -> str | None:
    """First pack-declared identity override, or None if no pack declares one --
    caller falls back to its own default identity string."""
    for pack in _packs():
        if pack.identity:
            return pack.identity
    return None


def active_portrait_directive() -> str | None:
    """First pack-declared portrait prompt directive, or None if no pack declares one."""
    for pack in _packs():
        if pack.portrait_prompt_directive:
            return pack.portrait_prompt_directive
    return None


def active_prose_style_extraction_prompt() -> str | None:
    """First pack-declared prose-style-extraction system prompt override, or None if no
    pack declares one -- caller falls back to its own neutral default prompt."""
    for pack in _packs():
        if pack.prose_style_extraction_prompt:
            return pack.prose_style_extraction_prompt
    return None


def active_chapter_direction_guidance() -> str | None:
    """First pack-declared skeleton-expansion 全局方向构思引导覆写(章级 set_chapter_direction
    前置步骤)，或 None——caller 落回自身中性默认引导文案。"""
    for pack in _packs():
        if pack.chapter_direction_guidance:
            return pack.chapter_direction_guidance
    return None


def active_stage_lens_guidance() -> str | None:
    """First pack-declared skeleton-expansion 分镜角度构思引导覆写(段级 set_stage_lens 前置步骤)，
    或 None——caller 落回自身中性默认引导文案。"""
    for pack in _packs():
        if pack.stage_lens_guidance:
            return pack.stage_lens_guidance
    return None


def active_dialogue_intent_guidance() -> str | None:
    """First pack-declared dialogue-draft 意图构造引导覆写(含 few-shot 示例；构建期 setup_chat
    与运行期 story_sandbox 的联合台词草稿共用同一份覆写)，或 None——caller 落回自身中性默认
    引导文案。"""
    for pack in _packs():
        if pack.dialogue_intent_guidance:
            return pack.dialogue_intent_guidance
    return None


def custom_fields() -> list[CustomFieldSpec]:
    out: list[CustomFieldSpec] = []
    seen: set[str] = set()
    for pack in _packs():
        for spec in pack.custom_fields:
            if spec.name in seen:
                raise ValueError(f"[ContentPacks] 自定义字段重名：{spec.name}")
            seen.add(spec.name)
            out.append(spec)
    return out


def state_derive_fields() -> list[StateFieldSpec]:
    """Baseline five text fields, with pack overrides on matching keys and pack-only extras appended."""
    baseline_keys = {f.key for f in BASELINE_STATE_FIELDS}
    overrides: dict[str, StateFieldSpec] = {}
    extras: list[StateFieldSpec] = []
    seen_extra: set[str] = set()
    for pack in _packs():
        for spec in pack.state_fields:
            if spec.key in baseline_keys:
                overrides[spec.key] = spec
            elif spec.key in seen_extra:
                raise ValueError(f"[ContentPacks] 状态推演字段重名：{spec.key}")
            else:
                seen_extra.add(spec.key)
                extras.append(spec)
    merged = [overrides.get(f.key, f) for f in BASELINE_STATE_FIELDS]
    merged.extend(extras)
    return merged


def state_derive_fields_api() -> list[dict[str, str]]:
    return [{"key": f.key, "label": f.label, "kind": f.kind} for f in state_derive_fields()]


def custom_fields_api() -> list[dict[str, str | bool]]:
    return [
        {"name": spec.name, "required": spec.required, "timeline_delta": spec.timeline_delta}
        for spec in custom_fields()
    ]


def contributed_dirs(attr: str) -> list[str]:
    """attr = "setup_chat_skill_dirs" | "detail_skill_dirs". Returns absolute paths:
    pack directory + each relative sub-path the pack declared under `attr`."""
    root = _packs_dir()
    out: list[str] = []
    try:
        names = sorted(p.name for p in root.iterdir() if p.is_dir())
    except OSError:
        return out
    for name in names:
        hook_path = root / name / "hook.py"
        if not hook_path.exists():
            continue
        pack = _load_pack(hook_path)
        if pack is None:
            continue
        for rel in getattr(pack, attr):
            out.append(str(root / name / rel))
    return out


def render_custom_fields_block(char: dict) -> list[str]:
    """遍历已注册自定义字段，角色档案里有值的拼成「name：value」行；供
    dialogue_mode/cards.py 与 setup/chat_summary.py 共用，字段落地后自动出现
    在两处渲染里，不需要逐字段回来改这两个文件。"""
    lines: list[str] = []
    for spec in custom_fields():
        value = char.get(spec.name)
        if isinstance(value, str) and value.strip():
            lines.append(f"{spec.name}：{value.strip()}")
        elif isinstance(value, list) and value:
            lines.append(f"{spec.name}：{'、'.join(str(v) for v in value)}")
    return lines
