"""cast product verification: schema integrity + physique vocabulary validity + group image structure diversity (pure function).

Only hard verification (schema/vocabulary/structure deduplication) of "code can be determined deterministically" is performed; semantic-level diversity and causality
Self-consistent and handed over to the user for review. The physique vocabulary check reuses the gender slot logic of stance_schema."""
from __future__ import annotations

from typing import Any

from engine.archive.sliders import valid_slider_value_shape
from engine.setup.cast.clothing_dna import CLOTHING_DNA_REQUIRED_KEYS
from engine.setup.cast.stance_schema import physique_slots

BASE_REQUIRED = (
    "name", "role", "gender", "given_name",
    "clothing_dna", "causal_anchors", "sliders", "physique", "personality",
    "identity_background",
)
_CLOTHING_REQUIRED = CLOTHING_DNA_REQUIRED_KEYS


def _required_fields() -> tuple[str, ...]:
    """BASE_REQUIRED + 已激活内容包里声明 required=True 的自定义字段。"""
    from context.content_packs import custom_fields
    extra = tuple(spec.name for spec in custom_fields() if spec.required)
    return BASE_REQUIRED + extra


def _load_world_race_names() -> list[str]:
    """
Read the list of race names declared in the active novel world_bible, accelerated by the WorldRepository cache."""
    from repositories import get_world_repo

    from engine.setup.world.summary import world_race_names

    bible = get_world_repo().get()
    return world_race_names(bible) if bible else []


def race_mismatch_advisory(char: dict[str, Any]) -> str:
    """角色 race 非空、世界观已声明种族、但不在列表里时，返回喂给后台 fix agent 的事实描述；
    否则返回空串（race 留空、或小说没声明种族，都不归这个函数管——前者继续是硬错误，
    后者本来就不需要校验）。"""
    world_races = _load_world_race_names()
    if not world_races:
        return ""
    race = str(char.get("race") or "").strip()
    if not race or race.casefold() in {w.casefold() for w in world_races}:
        return ""
    name = char.get("name") or char.get("given_name") or "<未命名>"
    bg = str(char.get("identity_background") or "").strip()
    bg_hint = f"（角色背景：{bg}）" if bg else ""
    return (
        f"角色「{name}」声明的种族「{race}」不在世界设定已声明的种族列表（"
        f"{'、'.join(world_races)}）中{bg_hint}。"
    )


def collect_character_field_errors(
    *,
    name: str,
    role: str,
    gender: str,
    causal_anchors: dict[str, Any],
    physique: dict[str, Any],
    sliders: dict[str, Any],
    clothing_color_palette: list[str] | None = None,
    clothing_materials: list[str] | None = None,
    clothing_signature_outfit: str | None = None,
    clothing_accessories: list[str] | None = None,
    clothing_dna: dict[str, Any] | None = None,
    race: str | None = None,
    world_races: list[str] | None = None,
    strict_race_membership: bool = True,
) -> list[str]:
    """Single-role field-level hard validation (role/gender/race/axis/physique/causal/clothing); shared by Pydantic and validate_character."""
    errs: list[str] = []
    if world_races is None:
        world_races = _load_world_race_names()

    if clothing_dna is not None:
        dna = clothing_dna or {}
        for k in ("color_palette", "materials_preference"):
            if not dna.get(k):
                errs.append(f"[{name}] clothing_dna 缺「{k}」")
        signature = dna.get("signature_outfit")
        if signature is None and "signature_outfit" not in dna:
            pass  # legacy lore tolerated until migration / next edit
        elif not isinstance(signature, str) or not signature.strip():
            errs.append(f"[{name}] clothing_dna.signature_outfit 不能为空")
        accessories = dna.get("accessories")
        if accessories is None and "accessories" not in dna:
            pass  # legacy lore tolerated until migration / next edit
        elif not isinstance(accessories, list):
            errs.append(f"[{name}] clothing_dna.accessories 须为字符串数组")
    else:
        if not clothing_color_palette:
            errs.append(f"[{name}] clothing_color_palette 不能为空")
        if not clothing_materials:
            errs.append(f"[{name}] clothing_materials 不能为空")
        if not (clothing_signature_outfit or "").strip():
            errs.append(f"[{name}] clothing_signature_outfit 不能为空")
        if clothing_accessories is None:
            errs.append(f"[{name}] clothing_accessories 不能为空")
        elif not isinstance(clothing_accessories, list):
            errs.append(f"[{name}] clothing_accessories 须为字符串数组")

    if not role or not gender:
        return errs

    from context.content_packs import get_gender_values
    if gender not in get_gender_values():
        opts = " / ".join(get_gender_values())
        errs.append(f"[{name}] gender 须为 {opts}，收到「{gender}」")

    #Race verification: Verification is only performed when world_bible declares races (novels without races do not force race and degrade gracefully).
    #Existence: If a race is declared, one must be specified; validity: must be aligned with world_bible.races (strip+casefold normalization).
    if world_races:
        r = str(race or "").strip()
        if not r:
            opts = "、".join(world_races)
            errs.append(f"[{name}] 缺 race（世界设定已定义种族，须指定其一）；可选：{opts}")
        elif strict_race_membership and r.casefold() not in {w.casefold() for w in world_races}:
            opts = "、".join(world_races)
            errs.append(f"[{name}] race「{race}」不在世界设定种族中；可选：{opts}")

    causal = causal_anchors or {}
    if not isinstance(causal, dict) or not causal \
            or not all(isinstance(v, str) and v.strip() for v in causal.values()):
        errs.append(f"[{name}] causal_anchors 须为非空对象（维度名→非空描述）")

    #只校验已经是新形态（dict）的轴——旧小说存量数据仍是裸文本，交由 edit_character 下次改动时
    #自然升级（同 validate_character_edit 对历史字段漂移的一贯宽容），不因存量格式漂移把其它未碰的角色卡死。
    new_shape_slid = {k: v for k, v in (sliders or {}).items() if isinstance(v, dict)}
    if new_shape_slid and not valid_slider_value_shape(new_shape_slid):
        errs.append(f"[{name}] sliders 每轴须为 {{level:int, text:非空str}}（与 archive.json 同形态）")
    elif new_shape_slid:
        for axis, val in new_shape_slid.items():
            levels = val.get("levels")
            if levels is None:
                continue  #旧存量数据未迁移，跳过档位范围校验（宽容，同上）
            if not (
                isinstance(levels, dict)
                and set(levels.keys()) == {"0", "1", "2"}
                and all(isinstance(t, str) and t.strip() for t in levels.values())
            ):
                errs.append(
                    f"[{name}] sliders.{axis}.levels 须为 3 档非空散文 "
                    '{"0":..,"1":..,"2":..}'
                )
                continue
            level = int(val["level"])
            legal = {int(k) for k in levels}
            if level not in legal:
                errs.append(f"[{name}] sliders.{axis}.level={level} 不在合法档位 {sorted(legal)} 内")

    got_phys = set((physique or {}).keys())
    base = physique_slots(str(gender))
    for k in sorted(base - got_phys):
        errs.append(f"[{name}] physique 缺基础子字段「{k}」")
    for k in sorted(got_phys - base):
        errs.append(
            f"[{name}] physique 未知子字段「{k}」（异化请写进对应基础部位槽描述，勿自造字段）"
        )

    return errs


def validate_character(char: dict[str, Any], *, strict_race_membership: bool = True) -> list[str]:
    """
Single-role hard verification, returns an error description list (empty = legal)."""
    errs: list[str] = []
    name = char.get("name") or "<未命名>"
    role = char.get("role")
    gender = char.get("gender")

    for k in _required_fields():
        if k not in char or char[k] in (None, "", {}, []):
            errs.append(f"[{name}] 缺必填字段「{k}」")

    if not role or not gender:
        return errs

    clothing = char.get("clothing_dna") or {}
    errs.extend(
        collect_character_field_errors(
            name=name,
            role=str(role),
            gender=str(gender),
            causal_anchors=char.get("causal_anchors") or {},
            physique=char.get("physique") or {},
            sliders=char.get("sliders") or {},
            clothing_dna=clothing if isinstance(clothing, dict) else None,
            race=char.get("race"),
            strict_race_membership=strict_race_membership,
        )
    )

    return errs


def validate_roster(
    roster: list[dict[str, Any]], *, strict_race_membership: bool = True,
) -> list[str]:
    """Class-wide verification: role-by-role schema + name deduplication (for batch output/full-volume verification)."""
    errs: list[str] = []
    seen: set[str] = set()
    for c in roster:
        nm = c.get("name") or ""
        if nm in seen:
            errs.append(f"角色名重复「{nm}」")
        seen.add(nm)
        errs.extend(validate_character(c, strict_race_membership=strict_race_membership))
    return errs


def validate_character_edit(
    char: dict[str, Any], roster: list[dict[str, Any]], *, strict_race_membership: bool = True,
) -> list[str]:
    """
Single character editing verification: only [the modified character’s own fields] + roster-level [name uniqueness] are verified.

    Deliberately not revalidate other fields that have not touched the role - otherwise historical data format drift (old English key/old role, etc.) will make any single role
    Editors are stuck (deadlocked) by other outdated roles. Full batch verification still uses validate_roster."""

    errs = validate_character(char, strict_race_membership=strict_race_membership)
    name = char.get("name") or ""
    if name and sum(1 for c in roster if (c.get("name") or "") == name) > 1:
        errs.append(f"角色名重复「{name}」")
    return errs
