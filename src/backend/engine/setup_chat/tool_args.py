"""Pydantic input model for the setup-chat tool (declared centrally for use by @tool(args_schema=...)).

The main agent directly fills in the structured fields; hard verification is completed at the Args layer, and the tool function is only responsible for IO/disk placement."""
from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from engine.setup.cast.cast_validator import collect_character_field_errors

#Re-exported for tools.py's plot-write functions, which do post-write validation in the
#function body rather than a model_validator here.
from engine.setup.plot.context import load_plot_grounding  # noqa: F401
from engine.setup.plot.validator import validate_plot_chapters  # noqa: F401
from engine.setup.world.validator import validate_world_bible


class ReadSetupSummaryArgs(BaseModel):
    target: str = Field(
        description="要读哪一域的文字摘要：world / cast / plot"
    )


class WorldNamedItemArgs(BaseModel):
    name: str = Field(description="条目名称")
    desc: str = Field(description="条目描述")
    keywords: list[str] = Field(
        default_factory=list,
        description="可选：正文中可能出现的具体线索词/同义描写，仅 power_system/core_themes 用得到。"
        "留空则维持默认行为（power_system 按裸名匹配，core_themes 不参与设定回收）；一旦填写，回收判定"
        "只认这些线索词是否出现，条目名本身不再单独算数——用于抽象概念条目（正文不写字面原词，靠具象"
        "描写命中）或常见词条目（防止裸名高频误命中导致回收区块灌水）。长度 <2 字的线索词会被自动丢弃"
        "（区分度太低）,请给 3-6 个正文中易出现的具象描写复合词。",
    )

    @field_validator("keywords")
    @classmethod
    def _drop_short_and_dedupe_keywords(cls, value: list[str]) -> list[str]:
        seen: list[str] = []
        for raw in value:
            kw = raw.strip()
            if len(kw) >= 2 and kw not in seen:
                seen.append(kw)
        return seen


class WorldBibleArgs(BaseModel):
    """
Complete worldview field (common to construct/refine)."""

    tone: str = Field(description="基调")
    background: str = Field(
        description="世界背景（含故事立意/核心钩子——先一两句点出这本书'一句话是什么'，再接时代/历史背景）"
    )
    factions: list[WorldNamedItemArgs] = Field(description="势力列表，每项含 name/desc")
    geography: list[WorldNamedItemArgs] = Field(description="地理列表，每项含 name/desc")
    races: list[WorldNamedItemArgs] = Field(description="种族列表，每项含 name/desc")
    power_system: list[WorldNamedItemArgs] = Field(
        description="力量体系列表，每项含 name/desc；每项是一个独立的力量/机制概念（如境界等级、气血机制、超凡能力），"
        "desc 写清楚运作规则/代价/限制"
    )
    core_themes: list[WorldNamedItemArgs] = Field(
        description="核心主题列表，每项含 name/desc；name 为主题词，desc 写该主题在本书具体如何呈现"
    )

    def to_bible(self) -> dict[str, Any]:
        return {
            "tone": self.tone,
            "background": self.background,
            "factions": [x.model_dump() for x in self.factions],
            "geography": [x.model_dump() for x in self.geography],
            "races": [x.model_dump() for x in self.races],
            "power_system": [x.model_dump() for x in self.power_system],
            "core_themes": [x.model_dump() for x in self.core_themes],
        }

    @model_validator(mode="after")
    def _validate_bible(self) -> WorldBibleArgs:
        errs = validate_world_bible(self.to_bible())
        if errs:
            raise ValueError("\n".join(errs))
        return self


class ConstructWorldArgs(WorldBibleArgs):
    """Write a worldview from scratch (or start over)."""

class RefineWorldArgs(WorldBibleArgs):
    """
Refining the world view: transfer the complete new settings to the disk."""

class SliderInitArgs(BaseModel):
    """初始滑块单轴值：与 archive.json 逐 stage 的 sliders 同一形态 {level:int, text:str}，
    额外带这根轴自己的 3 档梯子（levels），供后续校验/渲染/回落警报使用。"""

    level: int = Field(description="该轴初始档位号，须取自本次一并给出的 levels 的合法键")
    text: str = Field(description="据该档位描述写的一句贴合角色登场态的叙述，不照抄档位描述原文")
    levels: dict[str, str] = Field(
        description='该轴固定不变的 3 档梯子，形如 {"0":"最浅档描述","1":"中间档描述","2":"最深档描述"}；'
        "轴名和梯子由你现场为这个角色量身定义，不必跟其它角色一致，也不查任何外部 schema"
    )


def _gender_field_description() -> str:
    from context.content_packs import get_gender_values
    return f"{' / '.join(get_gender_values())}，决定 physique 部位槽"


def _physique_field_description() -> str:
    from context.content_packs import get_gender_values, physique_slots
    parts = [f"{g}：{'/'.join(sorted(physique_slots(g)))}" for g in get_gender_values()]
    return (
        "体型各部位描述 {部位槽名: 描述}；槽名用中文部位键——" + "；".join(parts) +
        "。须用这些键，别用英文、别自造"
    )


def format_race_field_description(race_names: list[str] | None = None) -> str:
    """Human-readable race field guidance for tool schemas and auto_build prompts."""
    if race_names is None:
        from repositories import get_world_repo

        from engine.setup.world.summary import world_race_names

        race_names = world_race_names(get_world_repo().get())
    if not race_names:
        return "所属种族；世界设定未声明种族时留空"
    return f"所属种族（必填），须从世界设定 races 中选一：{'、'.join(race_names)}"


def _race_field_description() -> str:
    return format_race_field_description()


class _StaticCharacterFieldsArgs(BaseModel):
    """
Role complete field (common to add/edit); hard verification is completed at this layer."""

    given_name: str = Field(
        description="角色名。这本书若是某个已有作品的同人，直接用原作里的角色专名；原创作品自拟。"
        "（脱敏铁律只管你在对话框里的措辞与举例，不限制写进设定的内容。）"
    )
    role: str = Field(description="角色位（类型）标签，自由命名；不是 given_name 人名")
    gender: str = Field(
        description="(占位——由 _build_character_fields_args() 动态覆盖，见 _gender_field_description)"
    )
    causal_anchors: dict[str, str] = Field(
        description="该角色独有的因果锚点 {维度名: 一句描述}，2-4 个（创伤/执念/渴望等，按个性自拟）"
    )
    physique: dict[str, str] = Field(
        description="(占位——由 _build_character_fields_args() 动态覆盖，见 _physique_field_description)"
    )
    clothing_color_palette: list[str] = Field(description="着装色系，如 ['黑','暗金']")
    clothing_materials: list[str] = Field(description="着装材质偏好，如 ['皮革','丝绸']")
    clothing_signature_outfit: str = Field(
        description="招牌常服/默认着装描述——具体款式与上下身搭配，供写作期推演初始着装的款式基准",
    )
    clothing_accessories: list[str] = Field(
        default_factory=list,
        description="标志性配饰/饰品列表，如 ['银质吊坠','皮质腕带']，可为空列表",
    )
    sliders: dict[str, SliderInitArgs] = Field(
        description="各状态轴的登场初始值 {轴名: {level, text, levels}}；轴名、轴数（2-4 根为宜）、"
        "每轴 3 档梯子文案全部由你现场为这个角色量身定义，不查任何外部 schema，也不必和其它角色一致——"
        "level=你给的 levels 里的合法档位号（int），text=据该档位描述写的一句登场态叙述——"
        "与 archive.json 里逐 stage 的 sliders 同一形态（同一个键，供后续角色档案推演时读取起点并逐 stage 叠加，"
        "但逐 stage 的 delta 只给 {level,text}，不重复 levels）"
    )
    race: str = Field(
        "",
        description="(占位——由 _build_character_fields_args() 动态覆盖，见 _race_field_description)",
    )
    identity_background: str = Field(
        description="身份背景（出身/职业/头衔等，一句话，如'没落贵族之女，寄人篱下'；必填）"
    )
    hobbies: list[str] = Field(
        default_factory=list,
        description="爱好/杂项癖好列表，如 ['爱吃甜食','喜欢刺绣']；可选，不填留空列表；"
                    "后续章节也可由 write_character_archive 整表替换",
    )
    verbal_tic: str = Field(
        "", description="登场初始口癖（可选，风格描述与口头禅写一句，如'句尾爱加\"呢\"，"
        "紧张时会重复最后两个字；口头禅是\"本小姐\"'）；不填留空，后续章节可由 "
        "write_character_archive 按需演变"
    )
    personality: str = Field(
        description="登场初始人格（必填，一两句散文描述性格/说话气质，自由撰写，别套固定类型名，"
        "如'表面嘴硬冷漠，内心其实很依恋对方，容易口是心非'）；后续章节可由 "
        "write_character_archive 按需演变（personality 没有转折就不必每章重填）"
    )
    portrait_identity_tags: str | None = Field(
        default=None,
        description="（可选）立绘身份锚定标签：该角色若出自某个已有作品，填 danbooru 风格的角色标签串，"
        "如 `shiroko (blue archive), blue archive`，会原样拼到生图 prompt 最前面锚定原作形象；"
        "原创角色留空。不传=不改动。",
    )
    portrait_visual_tags: str | None = Field(
        default=None,
        description="（可选）立绘外观提示词（英文 booru 关键词串）。一般留空，由系统按体型/着装自动提取；"
        "想手动控制立绘外观时才填。不传=不改动（改了体型/着装则仍会自动重提取覆盖）。",
    )

    @field_validator("given_name")
    @classmethod
    def _strip_given_name(cls, v: str) -> str:
        name = (v or "").strip()
        if not name:
            raise ValueError("given_name 不能为空")
        return name

    @field_validator("personality")
    @classmethod
    def _strip_personality(cls, v: str) -> str:
        text = (v or "").strip()
        if not text:
            raise ValueError("personality 不能为空")
        return text

    @field_validator("clothing_signature_outfit")
    @classmethod
    def _strip_clothing_signature_outfit(cls, v: str) -> str:
        text = (v or "").strip()
        if not text:
            raise ValueError("clothing_signature_outfit 不能为空")
        return text

    @field_validator("identity_background")
    @classmethod
    def _strip_identity_background(cls, v: str) -> str:
        text = (v or "").strip()
        if not text:
            raise ValueError("identity_background 不能为空")
        return text

    @model_validator(mode="after")
    def _validate_character_fields(self) -> _StaticCharacterFieldsArgs:
        errs = collect_character_field_errors(
            name=self.given_name,
            role=self.role,
            gender=self.gender,
            causal_anchors=self.causal_anchors,
            physique=self.physique,
            sliders={k: v.model_dump() for k, v in self.sliders.items()},
            clothing_color_palette=self.clothing_color_palette,
            clothing_materials=self.clothing_materials,
            clothing_signature_outfit=self.clothing_signature_outfit,
            clothing_accessories=self.clothing_accessories,
            race=self.race,
            strict_race_membership=False,
        )
        if errs:
            raise ValueError("\n".join(errs))
        return self


class _EditCharacterPlaceholderArgs(_StaticCharacterFieldsArgs):
    """Decoration-time-only args_schema for edit_character's @tool(...) (LangChain requires
    one there; build_agent() always overwrites it with build_edit_character_args() before
    real use -- see agent.py). Unlike the gender/physique/custom_fields split out into
    _build_character_fields_args(), `name` is structural (edit vs add), not content-pack-
    dependent, so it belongs on the placeholder itself: a test or tool invocation that calls
    edit_character directly without build_agent() having run first must still see a schema
    shaped like the real one, or Pydantic silently drops the `name` kwarg as an unknown field
    and the underlying function call blows up missing a required positional argument."""

    name: str = Field(description="要改的已有角色名（cast 中定位用）")


def _build_character_fields_args() -> type[BaseModel]:
    """Rebuilds gender/physique/custom-field descriptions fresh on every call, driven by the
    currently discovered content packs. Must never be cached at module scope: a module-level
    cache here is exactly what let Pydantic's class-body-executes-once semantics permanently
    freeze whatever content-pack state was active at process start (see 2026-07-29
    content-rating-schema-freeze-fix spec). build_agent() is already the natural rebuild
    boundary (novel switch / config save all call reset_setup_chat()), so paying
    create_model()'s cost on every build_agent() call is the correct trade-off, not
    a performance problem to solve."""
    from context.content_packs import custom_fields
    from pydantic import create_model

    extra_fields: dict[str, tuple[type, Any]] = {}
    for spec in custom_fields():
        desc = spec.description or f"{spec.name}（自定义字段，{'必填' if spec.required else '可选'}）"
        if spec.required:
            extra_fields[spec.name] = (str, Field(description=desc))
        else:
            extra_fields[spec.name] = (str, Field(default="", description=desc))
    return create_model(  # type: ignore[call-overload, no-any-return]
        "CharacterFieldsArgs",
        __base__=_StaticCharacterFieldsArgs,
        gender=(str, Field(description=_gender_field_description())),
        physique=(dict[str, str], Field(description=_physique_field_description())),
        race=(str, Field(default="", description=_race_field_description())),
        **extra_fields,
    )


def refresh_character_tool_args_schemas() -> None:
    """Rebind add/edit_character args_schema from current world + content packs.

    Called from pre_model_hook so a construct_world in the same turn immediately
    exposes declared race names to the next add_character tool call."""
    from engine.setup_chat.tools import add_character, edit_character

    add_character.args_schema = build_add_character_args()
    edit_character.args_schema = build_edit_character_args()


def build_add_character_args() -> type[BaseModel]:
    base = _build_character_fields_args()

    class _AddCharacterArgs(base):  # type: ignore[misc, valid-type]
        """Add a new role; use read_setup_summary('schema') to check if you are not sure about the fields before filling them in."""

    return _AddCharacterArgs


def build_edit_character_args() -> type[BaseModel]:
    base = _build_character_fields_args()

    class _EditCharacterArgs(base):  # type: ignore[misc, valid-type]
        """
To change an existing role; name is used to locate the character. If the character is to be changed, given_name is used to fill in the new name.
    写入成功后会清空该角色已有角色档案（delta + 各章 resolved archive），需之后重新构造。"""

        name: str = Field(description="要改的已有角色名（cast 中定位用）")

        @field_validator("name")
        @classmethod
        def _strip_lookup_name(cls, v: str) -> str:
            lookup = (v or "").strip()
            if not lookup:
                raise ValueError("name 不能为空")
            return lookup

    return _EditCharacterArgs


class PlotStageArgs(BaseModel):
    """Single stage field (stage_num is filled in by tool). Who's present is derived from
    `description` at read time via entity_index.scan_characters, not declared here --
    description MUST name every present character by their lore given_name; pronouns
    (你/我/他/她/他们/大家 etc.) are invisible to the scanner and will silently drop that
    character from every downstream cast/state derivation."""

    title: str = Field(description="场景标题")
    location: str = Field(description="场景地点")
    description: str = Field(
        description="场景描述——出场角色必须直接写人物全名，禁止用你/我/他/她/他们/大家等"
        "人称代词指代（角色识别靠对全名做精确扫描，代词扫不到，会导致该角色从后续所有 "
        "cast/状态推演里静默消失）"
    )


class PlotChapterArgs(BaseModel):
    """
Complete single chapter (including stages)."""

    title: str = Field(description="章标题")
    core_xp: list[str] = Field(min_length=1, description="本章核心体验/题材基调（必填，至少 1 条）")
    stages: list[PlotStageArgs] = Field(min_length=1, description="本章 stages")

    def to_chapter(self, chapter_index: int) -> dict[str, Any]:
        stages: list[dict[str, Any]] = []
        for j, s in enumerate(self.stages, 1):
            st = s.model_dump()
            st["stage_num"] = j
            stages.append(st)
        return {
            "chapter": chapter_index,
            "title": self.title,
            "core_xp": self.core_xp,
            "stages": stages,
        }


class GenerateOneChapterArgs(PlotChapterArgs):
    """Write/replace a single chapter (complete: title/core_xp/stages, stages required); press
    chapter_index upsert. `characters` doesn't exist on the incoming stages yet at parse time
    (derived after write) so full validation happens in generate_one_chapter's function body,
    post-extraction -- not here."""

    chapter_index: int = Field(ge=1, description="章号（1 起）")


class InsertChapterArgs(PlotChapterArgs):
    """Insert one brand-new chapter immediately after an existing chapter (or at the very
    front, if after_chapter=0), shifting every later chapter's number up by one. Unlike
    generate_one_chapter, this never replaces an existing chapter's content -- it only ever
    creates a new one."""

    after_chapter: int = Field(ge=0, description="插入到第几章之后（0=插到最前面）")


class PatchOp(StrEnum):
    """
Operation type of partial editing of chapter outline."""

    REPLACE = "replace"
    ADD = "add"
    REMOVE = "remove"
    REPLACE_BEAT = "replace_beat"
    SET_BEAT_DIALOGUE = "set_beat_dialogue"


class BeatArgs(BaseModel):
    """单拍写作底稿：text=结构+血肉的叙事底稿（含台词与否取决于 3b 选中的拓展本身是否产出台词），
    sensation_notes 可空=该拍无体感软引导（如动作方案的生理感受描述）。"""

    text: str = Field(
        min_length=1,
        description="该拍写作底稿（200–500 字叙事正文；是否含台词取决于 3b 选中的拓展本身）",
    )
    sensation_notes: list[str] = Field(
        default_factory=list,
        description="该拍体感/生理感受软引导（可空，供写作期主笔参考，非硬约束）",
    )
    dialogue_draft: str = Field(
        default="",
        description="该拍联合台词草稿（write_chapter_skeleton 内部自动生成，"
        "可为空=判断这拍不需要对话；可手动编辑）",
    )


class StagePatchFields(BaseModel):
    """Replace is used: only the fields to be changed are given, and the fields that are not given (None) remain unchanged."""

    title: str | None = Field(default=None, description="场景标题")
    location: str | None = Field(default=None, description="场景地点")
    description: str | None = Field(
        default=None,
        description="场景描述（粗大纲）——出场角色必须直接写人物全名，禁止用你/我/他/她/"
        "他们/大家等人称代词指代（角色识别靠对全名做精确扫描，代词扫不到，会导致该角色从"
        "后续所有 cast/状态推演里静默消失）",
    )
    beats: list[BeatArgs] | None = Field(
        default=None, description="该 stage 的分拍底稿（整体替换；只改单拍用 replace_beat）"
    )

    def applied(self) -> dict[str, Any]:
        """
Only take the fields that are explicitly given (not None) - None means no action."""
        return {k: v for k, v in self.model_dump().items() if v is not None}


class PatchChapterOpArgs(BaseModel):
    """Single local editing operation. stage_num / after_stage_num both refer to the current number [when called]."""

    op: PatchOp = Field(description="操作：replace（改字段）/ add（插段）/ remove（删段）")
    stage_num: int | None = Field(default=None, ge=1, description="replace/remove 定位的段号")
    after_stage_num: int | None = Field(
        default=None, ge=0, description="add 的插入位置：在此段后插入，0=插到最前"
    )
    fields: StagePatchFields | None = Field(default=None, description="replace 用：要改的字段子集")
    stage: PlotStageArgs | None = Field(default=None, description="add 用：完整新段")
    beat_idx: int | None = Field(default=None, ge=0, description="replace_beat 定位的拍序（0 起）")
    beat: BeatArgs | None = Field(
        default=None, description="replace_beat 用：整拍替换（完整 text 一起给）"
    )
    dialogue_draft: str | None = Field(
        default=None, description="set_beat_dialogue 用：该拍台词草稿（允许空字符串）"
    )

    @model_validator(mode="after")
    def _check(self) -> PatchChapterOpArgs:
        if self.op == PatchOp.REPLACE:
            if self.stage_num is None:
                raise ValueError("replace 需 stage_num 定位段")
            if self.fields is None or not self.fields.applied():
                raise ValueError("replace 需在 fields 里给至少一个要改的字段")
        elif self.op == PatchOp.REMOVE:
            if self.stage_num is None:
                raise ValueError("remove 需 stage_num 定位段")
        elif self.op == PatchOp.ADD:
            if self.after_stage_num is None:
                raise ValueError("add 需 after_stage_num（0=插到最前）")
            if self.stage is None:
                raise ValueError("add 需 stage（完整新段）")
        elif self.op == PatchOp.REPLACE_BEAT:
            if self.stage_num is None or self.beat_idx is None:
                raise ValueError("replace_beat 需 stage_num + beat_idx 定位拍")
            if self.beat is None:
                raise ValueError("replace_beat 需给完整 beat（整拍替换）")
        elif self.op == PatchOp.SET_BEAT_DIALOGUE:
            if self.stage_num is None or self.beat_idx is None:
                raise ValueError("set_beat_dialogue 需 stage_num + beat_idx 定位拍")
            if self.dialogue_draft is None:
                raise ValueError("set_beat_dialogue 需给 dialogue_draft（允许空字符串，但不能是 None）")
        return self


class PatchChapterArgs(BaseModel):
    """
Partially edit a chapter: an ordered list of stage operations, positioned one by one according
to the current number and rearranged at the end, plus an optional whole-chapter core_xp
replace."""

    chapter: int = Field(ge=1, description="要改的章号（1 起）")
    ops: list[PatchChapterOpArgs] = Field(
        default_factory=list, description="有序操作列表；各 op 的 stage 号均指调用时的当前编号"
    )
    core_xp: list[str] | None = Field(
        default=None, description="本章核心体验/题材基调（可选；给了就整体替换，不给不动）"
    )
    is_reviewed: bool = Field(
        default=False,
        description="True=本次是按后台审查通知做的终稿修正，写盘后不再触发全章过渡/文风审查",
    )

    @model_validator(mode="after")
    def _check_has_effect(self) -> PatchChapterArgs:
        if not self.ops and self.core_xp is None:
            raise ValueError("ops 和 core_xp 至少给一个，否则本次调用没有任何效果")
        return self


class AutoBuildSetupArgs(BaseModel):
    """AUTO mode only, from-scratch construction: builds world + N characters + M chapters in
    one deterministic pass instead of the agent driving each step itself. character_count/
    chapter_count come from the "对话" tab's config panel (author_loop_skill_prefs.json), not
    from the LLM -- see docs/superpowers/specs/2026-08-01-auto-build-character-outline-design.md."""

    brief: str = Field(
        description="题材/基调/主要冲突等用户简述，作为世界观/角色/剧情三步生成的共同上下文"
    )


class RecallResearchArgs(BaseModel):
    topic: str = Field(description="要查的主题/关键词（只查本地研究库）")


class WebSearchArgs(BaseModel):
    topic: str = Field(description="联网检索的主题/关键词（仅在用户明确同意联网后调用）")


class GetCharacterArgs(BaseModel):
    name: str = Field(description="要精确查询的角色名（须与 list_characters 返回的名字完全一致，不支持模糊匹配）")


class ReadAttachmentArgs(BaseModel):
    attachment_id: str = Field(description="上传附件时返回的 attachment_id")


class ReadAttachmentBatchArgs(BaseModel):
    attachment_ids: list[str] = Field(
        min_length=1,
        description="按文件名自然排序后批量读取的图片 attachment_id 列表（漫画/多页）",
    )


class LoadSkillArgs(BaseModel):
    name: str = Field(description=(
        "要加载的引导技能名（见系统 prompt 的『可用引导技能』索引）；"
        "技能正文里引用了 references/ 下的文件时，可用「技能名/references/文件名」取该文件"
    ))


class PresentChoicesArgs(BaseModel):
    question: str = Field(description="向用户提出的问题/选择题题干")
    options: list[str] = Field(min_length=1, description="供用户勾选的选项 label 列表（≥1）")
    recommended: str = Field(
        description="若由你自主决策（如 AUTO 模式），这是你会选的那个 option 原文；"
                    "manual 模式下该字段会被忽略但仍需填写"
    )


class RenameNovelTitleArgs(BaseModel):
    new_title: str = Field(description="小说的新标题，越详细越有助于 LLM 创作，无长度限制。")


class SetSourceFranchiseArgs(BaseModel):
    franchise: str = Field(
        description="这本小说是哪个已有作品的同人（如「碧蓝档案」/「Blue Archive」）；"
        "留空字符串=原创作品。设定后，各角色立绘会尝试按 danbooru 角色标签锚定原作形象。"
    )


class WriteCharacterArchiveArgs(BaseModel):
    chapter: int = Field(description="章号")
    name: str = Field(description="角色名（须在 cast）")
    profile: dict = Field(
        description="这一章的完整初始档案 delta（只含变化的字段：sliders/physique/address_ref/"
        "self_ref/gender/personality/verbal_tic/hobbies 等）；sliders 每轴须给 {level, text}；"
        "hobbies 为字符串列表（整表替换）；未变字段沿用上一章，不用重写")


class ReadArchiveSeedArgs(BaseModel):
    chapter: int = Field(description="章号")
    name: str = Field(description="角色名")


class ReadArchiveStatusArgs(BaseModel):
    chapter: int = Field(description="章号")


class ReadCharacterArchiveArgs(BaseModel):
    chapter: int = Field(description="要查的章号")
    name: str | None = Field(default=None, description="只看某角色给名字；省略=整章全部")


class ReadCharacterArgs(BaseModel):
    name: str = Field(description="角色全名")


class ReadRelationshipsArgs(BaseModel):
    name: str = Field(description="角色全名，查该角色作为 from 或 to 出现的所有关系边")


class AddRelationshipEdgeArgs(BaseModel):
    from_name: str = Field(min_length=1, description="边的起点角色全名（花名册里的 given_name）")
    to_name: str = Field(min_length=1, description="边的终点角色全名；方向只表示记录的起止方，不代表主从关系")
    nature: str = Field(min_length=1, description="关系性质（如「师徒」「双胞胎姐妹」「世仇」）")
    relationship_anchor: str = Field(default="", description="from 对 to 的情结短句，无则留空")
    from_ref_terms: list[str] = Field(default_factory=list, description="这段关系里 to 称呼 from 的第三人称称呼（如「师傅」），没有就留空")
    to_ref_terms: list[str] = Field(default_factory=list, description="这段关系里 from 称呼 to 的第三人称称呼（如「徒弟」），没有就留空")


class RemoveRelationshipEdgeArgs(BaseModel):
    from_name: str = Field(min_length=1, description="要删除的边的起点角色全名")
    to_name: str = Field(min_length=1, description="要删除的边的终点角色全名")


class DeleteCharacterArgs(BaseModel):
    name: str = Field(min_length=1, description="要删除的角色全名（花名册里的 given_name）")


class DeleteChapterArgs(BaseModel):
    chapter: int = Field(ge=1, description="要删除的章节号")


class SkeletonStageArgs(BaseModel):
    stage_num: int = Field(description="stage 号")
    overview: str = Field(
        default="",
        description=(
            "首次展开：本段概述——补充 3a/3b 已记录的分镜角度、情景拓展之外，对话里讨论出的、"
            "值得内部生成时参考的细节（非必填，分镜+拓展已经够用时可留空）。"
            "改这段（该 stage 已有拍文）：用户的修改意见，此时不可为空。"
        ),
    )


class AutoExpandSkeletonArgs(BaseModel):
    """AUTO mode only: one-shot whole-chapter skeleton expansion. Only valid when the chapter's
    plot exists and none of its stages has been expanded yet -- see
    docs/superpowers/specs/2026-08-09-auto-mode-skeleton-expansion-design.md."""

    chapter: int = Field(description="要一键扩写骨架的章号（该章 plot 已写、且全部 stage 尚未展开）")


class WriteChapterSkeletonArgs(BaseModel):
    chapter: int = Field(description="章号")
    stages: list[SkeletonStageArgs] = Field(min_length=1, description="逐 stage 的分拍底稿")
    is_reviewed: bool = Field(
        default=False,
        description="True=本次是按后台审查通知做的终稿修正，写盘后不再触发全章过渡/文风审查",
    )


class SetChapterDirectionArgs(BaseModel):
    """3a 之前的章级前置：记录本章整体叙事走向（skeleton_pipeline 的 DIRECTION 阶段）。"""

    chapter: int = Field(description="章号")
    direction: str = Field(min_length=1, description="本章整体叙事走向（用户选定的那条，或自定义）")


class SetStageLensArgs(BaseModel):
    """3a 完成后记录：本段选定的分镜/突出角度（skeleton_pipeline 的 LENS 阶段）。"""

    chapter: int = Field(description="章号")
    stage_num: int = Field(description="stage 号")
    angles: list[str] = Field(min_length=1, description="本段选定的分镜/突出角度")


class SetStageExtensionsArgs(BaseModel):
    """3b 完成后记录：本段选定的情景拓展（skeleton_pipeline 的 EXTENSIONS 阶段）。
    允许空列表——用户选"都不用"后仍需调用本工具，以空列表标记 3b 已完成。"""

    chapter: int = Field(description="章号")
    stage_num: int = Field(description="stage 号")
    extensions: list[str] = Field(default_factory=list, description="本段选定的情景拓展（可空）")


class ReadSkeletonSeedArgs(BaseModel):
    chapter: int = Field(description="要扩写骨架的章号")


class ReadChapterSkeletonArgs(BaseModel):
    chapter: int = Field(description="要读已扩写骨架的章号")
    stage_num: int | None = Field(default=None, description="只看某段则给 stage 号；省略=整章各段")


class ReadAuthorManuscriptArgs(BaseModel):
    """
Read the final author manuscript saved on disk (第N章_主笔.md), but only by stage slice.

The goal is to avoid feeding the entire chapter at once; the agent must request a stage range explicitly.
"""

    chapter: int = Field(ge=1, description="章号（1 起）")
    stage_num: int = Field(ge=1, description="起始阶段号（1 起，对应成稿里的「阶段一/二/三…」）")
    stage_to: int | None = Field(
        default=None,
        ge=1,
        description="结束阶段号（含）；省略=只读 stage_num 这一段",
    )

    @model_validator(mode="after")
    def _validate_stage_range(self) -> ReadAuthorManuscriptArgs:
        if self.stage_to is not None and self.stage_to < self.stage_num:
            raise ValueError("stage_to 必须 ≥ stage_num")
        return self


class QueryCharacterVoiceArgs(BaseModel):
    character: str = Field(min_length=1, description="角色全名")
    chapter: int = Field(ge=1, description="章号")
    stage_num: int = Field(ge=1, description="设计台词的 stage 号（人格可能章内转变，须按段解析）")


class TextPatchOpArgs(BaseModel):
    """单条文内替换规则。"""

    mode: str = Field(
        default="literal",
        description="literal=字面量查找；regex=正则（慎用，建议先 dry_run）",
    )
    find: str = Field(min_length=1, description="查找串或正则 pattern")
    replace: str = Field(default="", description="替换为（可为空串=删除匹配段）")
    match_policy: str = Field(
        default="unique",
        description="unique=必须恰好 1 处否则失败；first=只改第一处；all=改全部命中",
    )

    @field_validator("mode")
    @classmethod
    def _mode_ok(cls, v: str) -> str:
        if v not in ("literal", "regex"):
            raise ValueError("mode 只能是 literal 或 regex")
        return v

    @field_validator("match_policy")
    @classmethod
    def _policy_ok(cls, v: str) -> str:
        if v not in ("unique", "first", "all"):
            raise ValueError("match_policy 只能是 unique / first / all")
        return v


class PatchTextFragmentArgs(BaseModel):
    """
文内手术式替换：针对大纲 description、骨架 skeleton 或主笔成稿的局部文本精修。

不写盘时设 dry_run=true 可预览命中情况。手术式改 description 不会清空 skeleton（与 patch_chapter 整段替换不同）。
"""

    source: str = Field(
        description="plot_description（粗大纲）| plot_skeleton（分拍底稿单拍，需 stage_num+beat_idx）| manuscript（主笔成稿）",
    )
    chapter: int = Field(ge=1, description="章号")
    scope: str = Field(
        default="stage",
        description=(
            "stage=单段 plot 字段；chapter=本章各 stage 逐段应用同一组补丁；"
            "manuscript_stage=成稿单 stage 块；manuscript_chapter=成稿各 stage 块逐段应用"
        ),
    )
    stage_num: int | None = Field(
        default=None,
        ge=1,
        description="scope 为 stage / manuscript_stage 时必填",
    )
    beat_idx: int | None = Field(
        default=None,
        ge=0,
        description="source=plot_skeleton 时必填：定位该 stage 的第几拍（0 起），只改该拍 text",
    )
    patches: list[TextPatchOpArgs] = Field(
        min_length=1,
        max_length=20,
        description="有序补丁列表，串行应用；任一步失败则整次不写盘",
    )
    dry_run: bool = Field(default=False, description="true=只报告命中与预览，不写盘")
    is_reviewed: bool = Field(
        default=False,
        description="True=本次是按后台审查通知做的终稿修正，写盘后不再触发全章过渡/文风审查",
    )

    @field_validator("source")
    @classmethod
    def _source_ok(cls, v: str) -> str:
        if v not in ("plot_description", "plot_skeleton", "manuscript"):
            raise ValueError("source 只能是 plot_description / plot_skeleton / manuscript")
        return v

    @field_validator("scope")
    @classmethod
    def _scope_ok(cls, v: str) -> str:
        if v not in ("stage", "chapter", "manuscript_stage", "manuscript_chapter"):
            raise ValueError(
                "scope 只能是 stage / chapter / manuscript_stage / manuscript_chapter"
            )
        return v

    @model_validator(mode="after")
    def _cross_check(self) -> PatchTextFragmentArgs:
        plot_scopes = frozenset({"stage", "chapter"})
        ms_scopes = frozenset({"manuscript_stage", "manuscript_chapter"})
        if self.source == "manuscript":
            if self.scope not in ms_scopes:
                raise ValueError("source=manuscript 时 scope 须为 manuscript_stage 或 manuscript_chapter")
        elif self.scope not in plot_scopes:
            raise ValueError("source=plot_* 时 scope 须为 stage 或 chapter")
        if self.scope in ("stage", "manuscript_stage") and self.stage_num is None:
            raise ValueError("scope 为 stage / manuscript_stage 时必须提供 stage_num")
        if self.source == "plot_skeleton":
            #分拍底稿的手术式替换只支持单拍定位（跨拍/跨段批量替换语义不清，用 replace_beat 逐拍改）
            if self.scope != "stage" or self.beat_idx is None:
                raise ValueError("source=plot_skeleton 须 scope=stage 且提供 beat_idx（单拍定位）")
        return self


class ProseStyleExampleArgs(BaseModel):
    label: str = Field(description="场景标签，如「开场压制」「高潮收尾」")
    text: str = Field(description="示例正文，2-4句到一小段")


class WriteProseStylePresetArgs(BaseModel):
    slug: str = Field(
        description=(
            "英文 slug，小写字母/数字/连字符，作为预设 id；避免以 auto- 开头"
            "（该前缀被小说导入自动生成的专属预设占用）"
        )
    )
    title: str = Field(description="中文风格名，4-8字，不含「语感调色：」前缀")
    opening: str = Field(description="开场定位，3-5句：核心技法+适用场面+一个类比收尾")
    techniques: list[str] = Field(
        min_length=3,
        description="发挥方向条目，每条已含**手法名**+规则+「示例」内联引用的完整正文",
    )
    examples: list[ProseStyleExampleArgs] = Field(min_length=2, description="风格样例，覆盖不同场景阶段")
    taboos: list[str] = Field(min_length=1, description="这套忌讳条目，每条含忌+为什么")

    @field_validator("slug")
    @classmethod
    def _slug_ok(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", v):
            raise ValueError("slug 只能用小写字母/数字/连字符，如 cold-restrained")
        return v


class ReadProseStylePresetArgs(BaseModel):
    preset_id: str = Field(description="要读取的文风预设 id（list_prose_style_presets 能看到的 id）")


class SetWorldBackgroundArgs(BaseModel):
    background: str = Field(
        description="世界背景（含故事立意/核心钩子 + 时代/历史背景）"
    )


class RefineWorldBackgroundArgs(BaseModel):
    background: str = Field(description="新的世界背景全文（覆盖旧值）")


class SetWorldToneArgs(BaseModel):
    tone: str = Field(description="整体基调，如黑暗压抑 / 诙谐轻快 / 史诗厚重")


class RefineWorldToneArgs(BaseModel):
    tone: str = Field(description="新的基调全文（覆盖旧值）")


class AddWorldEntryArgs(BaseModel):
    name: str = Field(description="条目名称（该维度内唯一）")
    desc: str = Field(description="条目描述")


class AddWorldKeywordsEntryArgs(AddWorldEntryArgs):
    keywords: list[str] = Field(
        default_factory=list,
        description="可选：正文中可能出现的具体线索词/同义描写（2-4 个）；抽象概念或高频常见词时建议填写",
    )


class EditWorldEntryArgs(BaseModel):
    name: str = Field(description="要修改的条目名称（精确匹配，不支持改名）")
    desc: str = Field(description="新的条目描述")


class EditWorldKeywordsEntryArgs(EditWorldEntryArgs):
    keywords: list[str] = Field(
        default_factory=list,
        description="新的 keywords 列表（覆盖旧值；留空则清空 keywords）",
    )


class DeleteWorldEntryArgs(BaseModel):
    name: str = Field(description="要删除的条目名称（精确匹配）")

