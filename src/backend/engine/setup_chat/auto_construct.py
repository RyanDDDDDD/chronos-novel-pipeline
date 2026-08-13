"""Deterministic Python orchestration for AUTO mode's from-scratch world/character/plot
construction (auto_build_setup tool). Not an agent tool-calling loop -- a plain sequential
control flow that calls the existing construct_world/add_character/generate_one_chapter
functions directly, reusing their Pydantic validation and side effects (archive clearing,
timeline cascade, etc.) instead of reimplementing them. See
docs/superpowers/specs/2026-08-01-auto-mode-one-shot-construction-tool-design.md."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger
from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

CallLLM = Callable[[str, str], Awaitable[str]]

_DEFAULT_MAX_REDO = 2


def _review_regen_feedback(gate_message: str) -> str:
    """Qualitative rubric for AUTO regen prompts — no numeric scores."""
    rubric = gate_message.strip()
    prefix = "设定质量评审未通过，未写入。"
    if rubric.startswith(prefix):
        rubric = rubric[len(prefix):].lstrip()
    return f"\n\n## 设定质量评审未通过，请修正：\n{rubric}"


def _parse_extracted_character_text(text: str) -> tuple[str, str]:
    """Reverses novel_import.py::split_fine_grained's fixed '性格：X\\n口癖：Y' format --
    that format is written by our own code, so this is a deterministic split, not another
    round of LLM output parsing. '（无）' or blank values normalize to ''."""
    personality = ""
    verbal_tic = ""
    for line in text.split("\n"):
        if line.startswith("性格："):
            personality = line[len("性格："):].strip()
        elif line.startswith("口癖："):
            verbal_tic = line[len("口癖："):].strip()
    if personality == "（无）":
        personality = ""
    if verbal_tic == "（无）":
        verbal_tic = ""
    return personality, verbal_tic


def _load_imported_characters(cap: int) -> list[dict[str, str]]:
    """Roster grounded in the current novel's imported extraction (novel_import.py), ranked by
    mention_count (a best-effort prominence proxy, see split_fine_grained's docstring) and
    truncated to `cap` -- characters beyond the cap stay queryable via list_characters/
    get_character, they just don't become full Character entities. Returns [] when nothing has
    been imported (or extraction produced no characters), letting callers fall back to the
    from-scratch plan_character_outline path."""
    from repositories import get_research_repo
    from repositories.entities import ResearchCategory

    chunks = get_research_repo().get_chunks(ResearchCategory.CHARACTER)
    ranked = sorted(chunks, key=lambda c: c.mention_count, reverse=True)
    roster: list[dict[str, str]] = []
    for chunk in ranked[:cap]:
        name = chunk.topic.strip()
        if not name:
            continue
        personality, verbal_tic = _parse_extracted_character_text(chunk.text)
        roster.append({"given_name": name, "personality": personality, "verbal_tic": verbal_tic})
    return roster


def _parse_one_object(raw: str) -> dict[str, Any] | None:
    from engine.execution.embed_json import parse_embed_json

    items = parse_embed_json(raw)
    return items[0] if items else None


_WORLD_SYSTEM = (
    "你是世界观设定生成器，为一部小说一次性生成完整的世界观设定。这是单轮单次生成——不得提问、"
    "不得等待用户确认、不得只给部分维度分批输出，必须在这一轮直接输出覆盖全部维度的完整 JSON。\n\n"
    "## 覆盖以下维度\n"
    "- tone：整体气质，一句话。\n"
    "- background：小说立意（一句话说清\"这本书一句话是什么\"）+ 时代/大背景，几句话说清、自然"
    "成段。\n"
    "- core_themes：读者向往的爽点/题材标签，2-4 条，每条 {name: 关键词, desc: 在本书具体如何"
    "呈现}；name 若是通篇高频常见词（如「复仇」「成长」），额外给 keywords（2-4 个正文中可能出现"
    "的具体线索词/同义描写，如「血恨」「手刃」），否则不加这个字段。\n"
    "- power_system：超凡或异化机制怎么运作、有什么代价或限制；纯写实无超凡设定的题材，用一条"
    "隐喻性条目填补（如「心动的力量」），不能省略或留空；name 若是抽象概念、正文描写这件事时几乎"
    "不会逐字提到这几个字（如「信仰丧失」），额外给 keywords（2-4 个正文中可能出现的具体线索词/"
    "同义描写，如「神像崩塌」「停止祷告」），否则不加这个字段。\n"
    "- factions：2-4 个为冲突服务的势力，每条 {name, desc}。\n"
    "- geography：1-3 个关键地点，每条 {name, desc}。\n"
    "- races：即使是纯人类世界，也必须给至少 1 条（如 {\"name\":\"人类\",\"desc\":\"纯人类世界，"
    "无特殊体质\"}）；非纯人类世界列出全部关键种族及其体貌/异化倾向，每条 {name, desc}。\n\n"
    "## 输出格式（严格）\n"
    "只输出一个 JSON 对象，形如 {\"tone\": \"...\", \"background\": \"...\", \"factions\": "
    "[{\"name\":\"...\",\"desc\":\"...\"}], \"geography\": [...], \"races\": [...], "
    "\"power_system\": [...], \"core_themes\": [...]}，不要输出 JSON 以外的任何文字。"
    "factions/geography/races/power_system/core_themes 这 5 个字段全部必须是「{name, desc} "
    "对象列表」，没有例外——地理条目也不能只给地名字符串，必须是 {\"name\":\"地名\","
    "\"desc\":\"作用\"}；power_system/core_themes 里按上面规则需要 keywords 的条目，格式是 "
    "{\"name\":\"...\",\"desc\":\"...\",\"keywords\":[\"...\",\"...\"]}，不需要就不加这个键。\n\n"
    "示例与措辞只用通用占位词，绝不写入真实人名/小说 IP。"
)


def _load_imported_world_reference() -> str:
    from repositories import get_research_repo
    from repositories.entities import ResearchCategory

    chunks = get_research_repo().get_chunks(ResearchCategory.WORLD)
    return "\n".join(f"- {c.text}" for c in chunks if c.text.strip())


async def build_world(
    brief: str, call_llm: CallLLM, *, max_redo: int = _DEFAULT_MAX_REDO, reference_text: str = "",
) -> tuple[dict[str, Any] | None, list[str]]:
    """One-shot world generation, LLM-drafted then Pydantic-validated (ConstructWorldArgs),
    retried up to max_redo times with the previous attempt's validation errors fed back.
    Returns (world_bible_dict, []) on success -- the dict is already in construct_world()'s
    to_bible() shape, ready to pass straight through. Returns (None, errors) once retries are
    exhausted; world is a hard prerequisite for characters/chapters, so callers must stop the
    whole build rather than skip-and-continue (unlike character/chapter failures).

    Uses a standalone one-shot system prompt (_WORLD_SYSTEM), not the interactive
    world-interview skill -- that skill is written for a multi-turn, tool-calling agent (ask
    one dimension at a time, wait for the user) and actively conflicts with a single bare
    completion call that must emit the complete JSON immediately with no back-and-forth.

    reference_text (imported-novel world facts, see _load_imported_world_reference) is optional
    grounding context appended to the user message when non-empty -- it's loose extracted facts,
    not a structured mapping onto the tone/background/factions/... schema below, so the LLM still
    freely synthesizes the structured bible, just informed by it instead of inventing something
    that might contradict already-locked character backgrounds."""
    from engine.setup_chat.tool_args import ConstructWorldArgs
    from engine.setup_chat.tool_progress import emit_tool_progress

    await emit_tool_progress("auto_build_setup", "正在构建世界观…")
    system = _WORLD_SYSTEM
    reference_block = (
        f"\n\n已知设定（从导入小说提炼，可参考整合，不要与之矛盾）：\n{reference_text}"
        if reference_text else ""
    )
    schema_feedback = ""
    schema_failures = 0
    last_errors: list[str] = []
    attempt = 0
    while schema_failures <= max_redo:
        attempt += 1
        user = f"{brief}{reference_block}{schema_feedback}"
        logger.debug(
            "[auto_build_setup] 世界观 attempt={} schema_failures={}/{} 发起 LLM 调用",
            attempt, schema_failures, max_redo,
        )
        raw = await call_llm(system, user)
        parsed = _parse_one_object(raw)
        if parsed is None:
            last_errors = ["未能解析出合法 JSON"]
            logger.warning(
                "[auto_build_setup] 世界观 attempt={} JSON 解析失败，原始输出前200字：{!r}",
                attempt, raw[:200],
            )
            schema_failures += 1
            schema_feedback = "\n\n## 上一轮未通过，请修正：\n- 未能解析出合法 JSON，请只输出 JSON 对象"
            continue
        try:
            args = ConstructWorldArgs.model_validate(parsed)
        except ValidationError as exc:
            last_errors = [str(e["msg"]) for e in exc.errors()]
            logger.warning(
                "[auto_build_setup] 世界观 attempt={} 校验失败：{}", attempt, "；".join(last_errors),
            )
            schema_failures += 1
            schema_feedback = "\n\n## 上一轮未通过，请修正：\n" + "\n".join(f"- {m}" for m in last_errors)
            continue
        bible = args.to_bible()
        logger.info("[auto_build_setup] 世界观 attempt={} schema 通过", attempt)
        await emit_tool_progress("auto_build_setup", "世界观已构建")
        return bible, []
    logger.error(
        "[auto_build_setup] 世界观 schema 校验耗尽尝试（schema={}/{}），最终失败：{}",
        schema_failures, max_redo, "、".join(last_errors),
    )
    return None, last_errors


class CharacterOutlineEntry(BaseModel):
    given_name: str = Field(description="角色化名（通用占位词，禁用真实人名/小说 IP）")
    role: str = Field(description="角色定位标签，自由命名")
    persona: str = Field(description="一两句性格/特点概要")

    @field_validator("given_name", "role", "persona")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        text = (v or "").strip()
        if not text:
            raise ValueError("大纲角色字段不能为空")
        return text


class CharacterRelationship(BaseModel):
    a: str = Field(description="关系一方的 given_name")
    b: str = Field(description="关系另一方的 given_name")
    relation: str = Field(description="关系性质，一句话")

    @field_validator("a", "b", "relation")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        text = (v or "").strip()
        if not text:
            raise ValueError("关系字段不能为空")
        return text


class CharacterOutlineArgs(BaseModel):
    """Roster + relationship-network plan produced by plan_character_outline. Not a LangChain
    tool args_schema (no interactive tool exposes this) -- lives here, not tool_args.py, next
    to the one-shot-only prompts (_WORLD_SYSTEM/_CHAPTER_SYSTEM) it belongs with."""

    characters: list[CharacterOutlineEntry]
    relationships: list[CharacterRelationship] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_outline(self) -> CharacterOutlineArgs:
        names = [c.given_name for c in self.characters]
        errs: list[str] = []
        if len(set(names)) != len(names):
            errs.append("角色姓名不能重复")
        name_set = set(names)
        for r in self.relationships:
            if r.a not in name_set or r.b not in name_set:
                errs.append(f"关系引用了未声明的角色：{r.a} / {r.b}")
        if errs:
            raise ValueError("\n".join(errs))
        return self


class CharacterRoleEntry(BaseModel):
    given_name: str = Field(description="须与 roster 里的姓名完全一致")
    role: str = Field(description="角色定位标签，自由命名")

    @field_validator("given_name", "role")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        text = (v or "").strip()
        if not text:
            raise ValueError("角色定位字段不能为空")
        return text


class CharacterRolesArgs(BaseModel):
    """Import-grounded counterpart to CharacterOutlineArgs -- given_name/persona/verbal_tic are
    already locked from extraction (see _load_imported_characters), this only carries role +
    relationships. model_validate must be called with context={"roster_names": set[str]} so the
    name-set check below has something to check against."""

    characters: list[CharacterRoleEntry]
    relationships: list[CharacterRelationship] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_against_roster(self, info: ValidationInfo) -> CharacterRolesArgs:
        roster_names: set[str] = (info.context or {}).get("roster_names", set()) if info.context else set()
        names = {c.given_name for c in self.characters}
        errs: list[str] = []
        if roster_names and names != roster_names:
            missing = roster_names - names
            extra = names - roster_names
            if missing:
                errs.append(f"缺少角色：{'、'.join(sorted(missing))}")
            if extra:
                errs.append(f"出现了未知角色：{'、'.join(sorted(extra))}")
        for r in self.relationships:
            if r.a not in names or r.b not in names:
                errs.append(f"关系引用了未声明的角色：{r.a} / {r.b}")
        if errs:
            raise ValueError("\n".join(errs))
        return self


_CHARACTER_OUTLINE_SYSTEM = (
    "你是角色阵容规划师，为一部小说一次性规划全部角色的姓名/定位/人设概要，并设计角色之间的"
    "关系网。这是单轮单次生成——不得提问、不得等待用户确认，必须在这一轮直接输出完整 JSON。\n\n"
    "## 输出内容\n"
    "- characters：恰好 N 个角色（N 见下方 user 消息），每条 {given_name, role, persona}。"
    "given_name 为角色化名（通用占位词，禁用真实人名/小说 IP），role 为角色定位标签（自由命名，"
    "如「女主角」「反派」），persona 为一两句性格/特点概要。\n"
    "- relationships：角色之间的结构化关系，每条 {a, b, relation}，a/b 必须是上面 characters "
    "里已经出现过的 given_name，relation 一句话说清关系性质（如「师徒，互相猜忌」）。角色数 ≥2 "
    "时至少给出若干条关系，让阵容不是互相孤立的碎片，而是有恋人/对手/血缘/羁绊等联系的整体。\n\n"
    "## 输出格式（严格）\n"
    "只输出一个 JSON 对象：{\"characters\": [{\"given_name\":\"...\",\"role\":\"...\","
    "\"persona\":\"...\"}], \"relationships\": [{\"a\":\"...\",\"b\":\"...\",\"relation\":\"...\"}]}"
    "，不要输出 JSON 以外的任何文字。\n\n"
    "示例与措辞只用通用占位词，绝不写入真实人名/小说 IP。"
)


def _render_world_summary(world_bible: dict[str, Any]) -> str:
    theme_parts = []
    for t in world_bible.get("core_themes") or []:
        if not isinstance(t, dict):
            continue
        name = str(t.get("name", "")).strip()
        if not name:
            continue
        desc = str(t.get("desc", "")).strip()
        theme_parts.append(f"{name}（{desc}）" if desc else name)
    themes = "、".join(theme_parts)
    return f"基调：{world_bible.get('tone', '')}；背景：{world_bible.get('background', '')}；核心看点：{themes}"


async def plan_character_outline(
    brief: str, character_count: int, world_bible: dict[str, Any], call_llm: CallLLM, *,
    max_redo: int = _DEFAULT_MAX_REDO,
) -> tuple[dict[str, Any] | None, list[str]]:
    """One-shot roster + relationship planning, LLM-drafted then Pydantic-validated
    (CharacterOutlineArgs), retried up to max_redo times with the previous attempt's
    validation errors fed back. Returns ({"characters": [...], "relationships": [...]}, [])
    on success. Returns (None, errors) once retries are exhausted -- this is a hard
    prerequisite for the character phase (same contract as build_world for the whole build):
    no outline means no characters, not a fallback to independent per-character drafting."""
    from engine.setup_chat.tool_progress import emit_tool_progress

    await emit_tool_progress("auto_build_setup", "正在规划角色阵容…")
    world_summary = _render_world_summary(world_bible)
    system = _CHARACTER_OUTLINE_SYSTEM
    feedback = ""
    last_errors: list[str] = ["未知错误"]
    for attempt in range(max_redo + 1):
        user = f"{brief}\n\n世界观：{world_summary}\n\n角色数：{character_count}{feedback}"
        logger.debug(
            "[auto_build_setup] 角色阵容规划 attempt={}/{} 发起 LLM 调用", attempt + 1, max_redo + 1,
        )
        raw = await call_llm(system, user)
        parsed = _parse_one_object(raw)
        if parsed is None:
            last_errors = ["未能解析出合法 JSON"]
            logger.warning(
                "[auto_build_setup] 角色阵容规划 attempt={} JSON 解析失败，原始输出前200字：{!r}",
                attempt + 1, raw[:200],
            )
            feedback = "\n\n## 上一轮未通过，请修正：\n- 未能解析出合法 JSON，请只输出 JSON 对象"
            continue
        try:
            args = CharacterOutlineArgs.model_validate(parsed)
        except ValidationError as exc:
            last_errors = [str(e["msg"]) for e in exc.errors()]
            logger.warning(
                "[auto_build_setup] 角色阵容规划 attempt={} 校验失败：{}",
                attempt + 1, "；".join(last_errors),
            )
            feedback = "\n\n## 上一轮未通过，请修正：\n" + "\n".join(f"- {m}" for m in last_errors)
            continue
        if len(args.characters) != character_count:
            last_errors = [f"characters 条数须恰好为 {character_count}，实际 {len(args.characters)}"]
            logger.warning("[auto_build_setup] 角色阵容规划 attempt={} 条数不符：{}", attempt + 1, last_errors[0])
            feedback = "\n\n## 上一轮未通过，请修正：\n" + "\n".join(f"- {m}" for m in last_errors)
            continue
        logger.info("[auto_build_setup] 角色阵容规划 attempt={} 校验通过", attempt + 1)
        await emit_tool_progress("auto_build_setup", "角色阵容已规划")
        return {
            "characters": [c.model_dump() for c in args.characters],
            "relationships": [r.model_dump() for r in args.relationships],
        }, []
    logger.error(
        "[auto_build_setup] 角色阵容规划耗尽 {} 次尝试，最终失败：{}", max_redo + 1, "、".join(last_errors),
    )
    return None, last_errors


_CHARACTER_ROLES_SYSTEM = (
    "你是角色阵容定位师，为一部小说已确定的角色名单分配定位标签，并设计角色之间的关系网。"
    "姓名与人设已经从原著提炼确定，不需要也不允许更改——你只需要给每个角色一个定位标签，并设计"
    "关系网。这是单轮单次生成——不得提问、不得等待用户确认，必须在这一轮直接输出完整 JSON。\n\n"
    "## 输出内容\n"
    "- characters：与下方 user 消息给出的角色名单一一对应（姓名不能改、不能加、不能减），"
    "每条 {given_name, role}，role 为角色定位标签（自由命名，如「女主角」「反派」）。\n"
    "- relationships：角色之间的结构化关系，每条 {a, b, relation}，a/b 必须是角色名单里的"
    "given_name，relation 一句话说清关系性质。角色数 ≥2 时至少给出若干条关系。\n\n"
    "## 输出格式（严格）\n"
    "只输出一个 JSON 对象：{\"characters\": [{\"given_name\":\"...\",\"role\":\"...\"}], "
    "\"relationships\": [{\"a\":\"...\",\"b\":\"...\",\"relation\":\"...\"}]}，不要输出 JSON "
    "以外的任何文字。\n\n"
    "示例与措辞只用通用占位词，绝不写入真实人名/小说 IP。"
)


async def plan_character_roles_and_relationships(
    brief: str, roster: list[dict[str, str]], world_bible: dict[str, Any], call_llm: CallLLM, *,
    max_redo: int = _DEFAULT_MAX_REDO,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Import-grounded counterpart to plan_character_outline: given_name/personality/verbal_tic
    are already locked from extraction (see _load_imported_characters) -- this only asks the LLM
    to assign a role label per character and design the relationship network, the two things raw
    extraction doesn't capture. Returns ({"characters": [{"given_name","role"}], "relationships":
    [...]}, []) on success -- persona/verbal_tic are NOT part of this return value, the caller
    (run_auto_build) splices them back in from `roster`. Returns (None, errors) once retries are
    exhausted, same hard-prerequisite contract as plan_character_outline."""
    from engine.setup_chat.tool_progress import emit_tool_progress

    await emit_tool_progress("auto_build_setup", "正在为导入角色分配定位与关系…")
    roster_names = {r["given_name"] for r in roster}
    roster_lines = "\n".join(
        f"- {r['given_name']}：性格={r['personality'] or '（未知）'}；口癖={r['verbal_tic'] or '（无）'}"
        for r in roster
    )
    world_summary = _render_world_summary(world_bible)
    system = _CHARACTER_ROLES_SYSTEM
    feedback = ""
    last_errors: list[str] = ["未知错误"]
    for attempt in range(max_redo + 1):
        user = f"{brief}\n\n世界观：{world_summary}\n\n角色名单：\n{roster_lines}{feedback}"
        logger.debug(
            "[auto_build_setup] 导入角色定位规划 attempt={}/{} 发起 LLM 调用", attempt + 1, max_redo + 1,
        )
        raw = await call_llm(system, user)
        parsed = _parse_one_object(raw)
        if parsed is None:
            last_errors = ["未能解析出合法 JSON"]
            feedback = "\n\n## 上一轮未通过，请修正：\n- 未能解析出合法 JSON，请只输出 JSON 对象"
            continue
        try:
            args = CharacterRolesArgs.model_validate(parsed, context={"roster_names": roster_names})
        except ValidationError as exc:
            last_errors = [str(e["msg"]) for e in exc.errors()]
            logger.warning(
                "[auto_build_setup] 导入角色定位规划 attempt={} 校验失败：{}",
                attempt + 1, "；".join(last_errors),
            )
            feedback = "\n\n## 上一轮未通过，请修正：\n" + "\n".join(f"- {m}" for m in last_errors)
            continue
        logger.info("[auto_build_setup] 导入角色定位规划 attempt={} 校验通过", attempt + 1)
        await emit_tool_progress("auto_build_setup", "导入角色定位与关系已规划")
        return {
            "characters": [c.model_dump() for c in args.characters],
            "relationships": [r.model_dump() for r in args.relationships],
        }, []
    logger.error(
        "[auto_build_setup] 导入角色定位规划耗尽 {} 次尝试，最终失败：{}",
        max_redo + 1, "、".join(last_errors),
    )
    return None, last_errors


def _character_system_prompt(race_names: list[str] | None = None) -> str:
    """Standalone one-shot system prompt for the remaining (non-locked) character fields.
    given_name/role/personality are decided by plan_character_outline and locked before this
    call ever validates -- this prompt tells the LLM they'll be given as fact in the user
    message and are not part of what it needs to produce, so it doesn't waste output tokens
    (or get confused) trying to reinvent them."""
    from engine.setup_chat.tool_args import (
        _gender_field_description,
        _physique_field_description,
        format_race_field_description,
    )

    race_line = format_race_field_description(race_names)

    return (
        "你是角色设定生成器，为一部小说的某个角色补全详细设定。该角色的姓名/定位/人设概要已经"
        "在阵容规划阶段锁定，会在下方 user 消息里直接告诉你——不必也不会被要求重新输出这三项，"
        "你只需要基于它们，把其余字段写全。这是单轮单次生成——不得提问、不得等待用户确认、"
        "不得要求提供角色 schema 或任何外部信息，成长轴名称与梯子文案全部由你自己现场定义，"
        "不查询任何外部资料；必须在这一轮直接输出该角色剩余字段的完整 JSON。\n\n"
        "## 各字段要点\n"
        f"- gender：{_gender_field_description()}。\n"
        "- causal_anchors：该角色独有的因果锚点 2-4 个（创伤/执念/渴望等），{维度名: 一句描述}；"
        "若下方 user 消息给出了该角色与其他角色的关系，至少 1 条锚点须体现这段关系里的情感/"
        "心理烙印，不要让因果锚点和关系网互相无关。\n"
        f"- physique：{_physique_field_description()}。\n"
        "- clothing_color_palette / clothing_materials：着装色系/材质偏好。\n"
        "- clothing_signature_outfit：招牌常服/默认着装描述——具体款式与上下身搭配。\n"
        "- clothing_accessories：标志性配饰/饰品列表（可为空数组）。\n"
        "- sliders：2-4 根状态轴的登场初始值；轴名、每轴 3 档梯子文案全部由你现场为这个角色量身"
        "定义，不必和其它角色一致。\n"
        f"- race：{race_line}。\n"
        "- identity_background：身份背景，一句话（必填）。\n"
        "- hobbies：爱好/杂项癖好列表（可选，可留空列表）。\n"
        "- verbal_tic：口癖（可选，可留空字符串）。\n\n"
        "## 严格输出格式（字段类型不能错）\n"
        "只输出一个 JSON 对象，字段：gender/causal_anchors/physique/clothing_color_palette/"
        "clothing_materials/clothing_signature_outfit/clothing_accessories/sliders/race/"
        "identity_background/hobbies/verbal_tic，不要输出 "
        "JSON 以外的任何文字。字段类型必须严格遵守：\n"
        "- clothing_color_palette、clothing_materials、clothing_accessories、hobbies 必须是 JSON 字符串数组"
        "（如 [\"黑\",\"暗金\"]），不能是用顿号连接的单个字符串。\n"
        "- clothing_signature_outfit 必须是单个非空字符串。\n"
        "- causal_anchors、physique 必须是 {字符串: 字符串} 的对象。\n"
        "- sliders 必须是 {轴名: {\"level\": 档位号整数, \"text\": \"据该档位写的一句登场态描述\", "
        "\"levels\": {\"0\":\"最浅档描述\",\"1\":\"中间档描述\",\"2\":\"最深档描述\"}}} 这个完整"
        "对象形状，**不能只给一个裸整数或裸字符串**。\n\n"
        "示例与措辞只用通用占位词，绝不写入真实人名/小说 IP。"
    )


async def _draft_one_character(
    brief: str, outline_entry: dict[str, str], relationships_text: str, call_llm: CallLLM, *,
    max_redo: int, race_names: list[str] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Returns (validated_fields_dict, None) on success, (None, error_summary) on exhausted
    retries. Does not write to disk -- see build_characters for the sequential write step.

    given_name/role/personality are locked by plan_character_outline (Task 1) -- whatever the
    LLM puts in those three keys (if anything) is discarded and unconditionally overwritten
    with the locked outline values before validation, so drift in the LLM's own copy of them
    can never surface as a validation failure or a mismatched final character.

    race_names (the just-built world's declared races, if any) must be told to the draft
    prompt up front -- collect_character_field_errors hard-requires `race` to match one of
    them whenever the world declares races, but the LLM has no way to guess the exact names
    on its own."""
    from engine.setup_chat.setup_quality_review import _SETUP_REVIEW_MAX_REDO, gate_character
    from engine.setup_chat.tool_args import build_add_character_args
    from engine.setup_chat.tools import _build_character_dict

    args_cls = build_add_character_args()
    system = _character_system_prompt(race_names)
    schema_feedback = ""
    review_feedback = ""
    schema_failures = 0
    review_failures = 0
    last_errors: list[str] = ["未知错误"]
    given_name = outline_entry.get("given_name", "")
    role = outline_entry.get("role", "")
    persona = outline_entry.get("persona", "")
    race_block = (
        f"\n\n世界设定已定义种族，race 字段须从中选一个填入：{'、'.join(race_names)}"
        if race_names else ""
    )
    relationship_block = f"\n\n该角色的关系：{relationships_text}" if relationships_text else ""
    label = given_name or "?"
    attempt = 0
    while schema_failures <= max_redo and review_failures <= _SETUP_REVIEW_MAX_REDO:
        attempt += 1
        user = (
            f"{brief}\n\n该角色已定：姓名={given_name}，定位={role}，人设概要={persona}"
            f"{relationship_block}{race_block}{schema_feedback}{review_feedback}"
        )
        logger.debug(
            "[auto_build_setup] 角色草稿 name={} attempt={} schema_failures={}/{} review_failures={}/{} 发起 LLM 调用",
            label, attempt, schema_failures, max_redo, review_failures, _SETUP_REVIEW_MAX_REDO,
        )
        raw = await call_llm(system, user)
        parsed = _parse_one_object(raw)
        if parsed is None:
            last_errors = ["未能解析出合法 JSON"]
            logger.warning(
                "[auto_build_setup] 角色草稿 name={} attempt={} JSON 解析失败，原始输出前200字：{!r}",
                label, attempt, raw[:200],
            )
            schema_failures += 1
            schema_feedback = "\n\n## 上一轮未通过，请修正：\n- 未能解析出合法 JSON，请只输出 JSON 对象"
            continue
        parsed["given_name"] = given_name
        parsed["role"] = role
        parsed["personality"] = persona
        if "verbal_tic" in outline_entry:
            parsed["verbal_tic"] = outline_entry["verbal_tic"]
        try:
            validated = args_cls.model_validate(parsed)
        except ValidationError as exc:
            last_errors = [str(e["msg"]) for e in exc.errors()]
            logger.warning(
                "[auto_build_setup] 角色草稿 name={} attempt={} 校验失败：{}",
                label, attempt, "；".join(last_errors),
            )
            schema_failures += 1
            schema_feedback = "\n\n## 上一轮未通过，请修正：\n" + "\n".join(f"- {m}" for m in last_errors)
            continue
        dumped = validated.model_dump()
        char_for_gate = _build_character_dict(
            dumped["given_name"], dumped["role"], dumped["gender"], dumped.get("race", ""),
            dumped["causal_anchors"], dumped["physique"],
            dumped["clothing_color_palette"], dumped["clothing_materials"],
            dumped["clothing_signature_outfit"], dumped.get("clothing_accessories") or [],
            dumped["sliders"],
            dumped["identity_background"], dumped.get("hobbies") or [],
            dumped.get("verbal_tic", ""), dumped["personality"],
        )
        char_for_gate.update({k: v for k, v in dumped.items() if k not in char_for_gate})
        ok, gate_msg = await gate_character(char_for_gate, novel_brief=brief)
        if ok:
            logger.info("[auto_build_setup] 角色草稿 name={} attempt={} 校验与质量评审通过", label, attempt)
            return dumped, None
        review_failures += 1
        last_errors = [gate_msg.strip()]
        logger.warning(
            "[auto_build_setup] 角色草稿 name={} attempt={} 质量评审未通过（review_failures={}/{}）",
            label, attempt, review_failures, _SETUP_REVIEW_MAX_REDO,
        )
        review_feedback = _review_regen_feedback(gate_msg)
    logger.error(
        "[auto_build_setup] 角色草稿 name={} 耗尽尝试（schema={}/{} review={}/{}），最终失败：{}",
        label, schema_failures, max_redo, review_failures, _SETUP_REVIEW_MAX_REDO, "、".join(last_errors),
    )
    return None, "、".join(last_errors)


async def build_characters(
    brief: str, outline: dict[str, Any], call_llm: CallLLM, *,
    batch_size: int = 3, max_redo: int = _DEFAULT_MAX_REDO, race_names: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Drafts every character declared in outline["characters"] (each entry's given_name/role/
    persona are locked and spliced verbatim into the final object -- see _draft_one_character)
    in batches of batch_size, concurrently within a batch, sequentially across batches. Writes
    (add_character) happen strictly sequentially -- one at a time, batch or no batch -- because
    the underlying JsonStore read-modify-write has no atomic append; concurrent writes would
    silently drop characters.

    Unlike the pre-outline version, batch order carries no narrative meaning any more --
    outline["relationships"] already gives every character everything it needs to know about
    the others, so there's no "already built" cross-batch summary to construct. batch_size is
    now pure API-concurrency throttling. A character whose draft never validates within
    max_redo retries is skipped (its error recorded), the rest of the batch and all later
    batches still proceed. Emits one progress event per character (success or failure/skip)."""
    from engine.setup_chat.tool_progress import emit_tool_progress

    entries = outline.get("characters") or []
    relationships = outline.get("relationships") or []
    character_count = len(entries)
    built: list[dict[str, Any]] = []
    errors: list[str] = []
    processed = 0
    for batch_start in range(0, character_count, batch_size):
        batch_entries = entries[batch_start:batch_start + batch_size]
        drafts = await asyncio.gather(*(
            _draft_one_character(
                brief, entry, _relationship_text_for(entry.get("given_name", ""), relationships),
                call_llm, max_redo=max_redo, race_names=race_names,
            )
            for entry in batch_entries
        ))
        for fields, error in drafts:
            processed += 1
            if fields is None:
                errors.append(f"角色草稿失败：{error}")
                await emit_tool_progress(
                    "auto_build_setup", f"角色 {processed}/{character_count}：草稿失败已跳过",
                )
                continue
            ok, msg, char = await _add_character_core(**fields)
            if not ok or char is None:
                errors.append(f"角色「{fields.get('given_name', '?')}」写入失败：{msg}")
                logger.error(
                    "[auto_build_setup] 角色「{}」写入失败：{}", fields.get("given_name", "?"), msg,
                )
                await emit_tool_progress(
                    "auto_build_setup",
                    f"角色 {processed}/{character_count}：「{fields.get('given_name', '?')}」失败已跳过",
                )
                continue
            logger.info("[auto_build_setup] 角色「{}」已写入", fields.get("given_name", "?"))
            built.append(char)
            await emit_tool_progress(
                "auto_build_setup",
                f"角色 {processed}/{character_count}：已建「{fields.get('given_name', '?')}」",
            )
    return built, errors


def _relationship_text_for(given_name: str, relationships: list[dict[str, str]]) -> str:
    """Renders every relationship touching `given_name` as one line each, from that
    character's point of view (the other party first)."""
    lines = [
        f"与{r.get('b') if r.get('a') == given_name else r.get('a')}：{r.get('relation', '')}"
        for r in relationships if given_name in (r.get("a"), r.get("b"))
    ]
    return "；".join(lines)


async def _add_character_core(**kwargs: Any) -> tuple[bool, str, dict[str, Any] | None]:
    """Thin re-export so tests can monkeypatch `ac._add_character_core` without reaching into
    tools.py -- the real implementation is tools.py's module-private helper, imported lazily to
    avoid a top-level circular import (tools.py itself will import auto_construct in Task 3)."""
    from engine.setup_chat.tools import _add_character_core as _real
    return await _real(**kwargs)


def _chapter_system_prompt(target_words: int) -> str:
    from engine.setup.plot.validator import suggested_min_stage_count

    suggested = suggested_min_stage_count(target_words)
    return (
        "你是剧情章纲生成器，为一部小说生成一整章的章纲。这是单轮单次生成——不得提问、不得等待"
        "用户确认、不得只给章纲不给 stages 分两轮，必须在这一轮直接输出该章完整的 title/core_xp/"
        "stages。\n\n"
        "## 各字段要点\n"
        "- title：章标题。\n"
        "- core_xp：本章核心体验/题材基调，几个关键词，至少 1 条。\n"
        "- stages：把本章拆成几个场景，每个 stage 含 title（场景标题）/location（场景地点）/"
        "description（一句到几句的剧情概述，交代发生了什么、情绪与走向；不写台词/对白引号/过细"
        "细节，章纲不是正文）。description 里对每个在场角色必须直接写人物全名，禁止用你/我/他/"
        "她/他们/大家等人称代词指代——角色识别靠对全名做精确扫描，代词扫不到，会导致该角色从后续"
        "所有 cast/状态推演里静默消失。当前章节字数目标为"
        f"{target_words} 字，stage 数量不得少于 {suggested} 个，少于此数会导致本章写入被拒绝、"
        "需要重新生成。\n\n"
        "## 输出格式（严格）\n"
        "只输出一个 JSON 对象：{title, core_xp: [...], stages: [{\"title\":\"...\","
        "\"location\":\"...\",\"description\":\"...\"}]}，不要输出 JSON 以外的任何文字。\n\n"
        "示例与措辞只用通用占位词，绝不写入真实人名/小说 IP。"
    )

_CHAPTER_SUMMARY_SYS = (
    "你是剧情记账员。把给定章节信息压成 1-2 句纯事件摘要：谁做了什么、局势/关系有何变化、"
    "埋下什么线索。不写文采、只记发生了什么。只输出摘要句。"
)


async def _summarize_chapter(prior: str, chapter: dict[str, Any], call_llm: CallLLM) -> str:
    """Mirrors the old plot runner's _summarize_chapter -- pure gain, failure degrades to
    returning `prior` unchanged rather than blocking the build."""
    descs = " ".join(str(s.get("description", "")) for s in chapter.get("stages") or [])
    body = f"标题：{chapter.get('title', '')}\n情节：{descs}"
    try:
        raw = await call_llm(_CHAPTER_SUMMARY_SYS, f"## 本章\n{body}")
    except Exception:  # noqa: BLE001 -- summary is pure gain, never blocks the build
        return prior
    addition = (raw or "").strip()
    if not addition:
        return prior
    return f"{prior}\n{addition}" if prior else addition


def _load_imported_plot_reference() -> str:
    from repositories import get_research_repo
    from repositories.entities import ResearchCategory

    chunks = get_research_repo().get_chunks(ResearchCategory.PLOT)
    return "\n".join(f"- {c.text}" for c in chunks if c.text.strip())


async def build_chapters(
    brief: str, character_names: list[str], chapter_count: int, call_llm: CallLLM, *,
    max_redo: int = _DEFAULT_MAX_REDO, reference_text: str = "",
) -> tuple[int, list[str]]:
    """Strictly sequential -- chapter N's prompt carries a rolling summary of chapters 1..N-1,
    so chapters must be written in order (no batching, no concurrency, unlike build_characters).
    A chapter that never validates or never writes successfully within max_redo retries is
    skipped (recorded in errors) and the next chapter number is still attempted --
    generate_one_chapter upserts by chapter_index, so a skipped chapter just leaves a gap
    rather than corrupting later chapters. Emits one progress event per chapter (success or
    failure/skip).

    Short-circuits with zero chapters attempted if character_names is empty -- generate_one_
    chapter hard-requires a non-empty cast (load_plot_grounding raises ValueError otherwise),
    so every chapter would fail identically; better to report that once than burn chapter_count
    LLM calls repeating the same failure.

    Uses _chapter_system_prompt (a standalone one-shot prompt), not the interactive plot-interview
    skill -- that skill is written for a multi-turn agent (define the chapter outline first,
    then negotiate stages one at a time) and would conflict with a single completion call the
    same way world-interview/character-interview did (see build_world's docstring).

    The write attempt (generate_one_chapter) lives inside the same attempt/feedback loop as the
    JSON-parse and pydantic-validation checks -- a chapter that parses fine but fails the
    stage-count hard gate (or any other validate_plot_chapters check) must retry with feedback
    like any other draft failure, not get silently recorded as written."""
    from engine.modes.author_loop_skill_prefs import DEFAULT_TARGET_WORDS, load_dialogue_prefs
    from engine.setup_chat.tool_args import GenerateOneChapterArgs
    from engine.setup_chat.tool_progress import emit_tool_progress

    if not character_names:
        return 0, ["角色为空（角色全部构建失败），已跳过章节生成"]

    target_words = load_dialogue_prefs().get("target_words", DEFAULT_TARGET_WORDS)
    system = _chapter_system_prompt(target_words)
    roster = "、".join(character_names) or "（无）"
    prior_summary = ""
    written = 0
    errors: list[str] = []
    for chapter_index in range(1, chapter_count + 1):
        feedback = ""
        last_errors: list[str] = ["未知错误"]
        chapter_dict: dict[str, Any] | None = None
        write_ok = False
        for attempt in range(max_redo + 1):
            prior_block = f"\n\n前情摘要：{prior_summary}" if prior_summary else ""
            reference_block = (
                f"\n\n导入剧情参考（可整合改编，不必逐句照搬）：\n{reference_text}" if reference_text else ""
            )
            user = f"{brief}\n\n角色名单：{roster}{prior_block}{reference_block}{feedback}"
            logger.debug(
                "[auto_build_setup] 第{}章 attempt={}/{} 发起 LLM 调用",
                chapter_index, attempt + 1, max_redo + 1,
            )
            raw = await call_llm(system, user)
            parsed = _parse_one_object(raw)
            if parsed is None:
                last_errors = ["未能解析出合法 JSON"]
                logger.warning(
                    "[auto_build_setup] 第{}章 attempt={} JSON 解析失败，原始输出前200字：{!r}",
                    chapter_index, attempt + 1, raw[:200],
                )
                feedback = "\n\n## 上一轮未通过，请修正：\n- 未能解析出合法 JSON，请只输出 JSON 对象"
                continue
            try:
                validated = GenerateOneChapterArgs.model_validate({
                    "chapter_index": chapter_index, **parsed,
                })
            except ValidationError as exc:
                last_errors = [str(e["msg"]) for e in exc.errors()]
                logger.warning(
                    "[auto_build_setup] 第{}章 attempt={} 校验失败：{}",
                    chapter_index, attempt + 1, "；".join(last_errors),
                )
                feedback = "\n\n## 上一轮未通过，请修正：\n" + "\n".join(f"- {m}" for m in last_errors)
                continue
            chapter_dict = validated.model_dump()
            try:
                write_ok, msg = await _generate_one_chapter_core(
                    chapter_index=chapter_index, title=chapter_dict["title"],
                    core_xp=chapter_dict["core_xp"], stages=chapter_dict["stages"],
                )
            except (ValueError, OSError) as exc:
                write_ok, msg = False, str(exc)
            if write_ok:
                break
            last_errors = [msg]
            logger.warning(
                "[auto_build_setup] 第{}章 attempt={} 写入失败：{}",
                chapter_index, attempt + 1, msg,
            )
            feedback = "\n\n## 上一轮未通过，请修正：\n- " + msg
        if not write_ok:
            logger.error(
                "[auto_build_setup] 第{}章耗尽 {} 次尝试，最终失败：{}",
                chapter_index, max_redo + 1, "、".join(last_errors),
            )
            errors.append(f"第{chapter_index}章写入失败：{'、'.join(last_errors)}")
            await emit_tool_progress(
                "auto_build_setup", f"章节 {chapter_index}/{chapter_count}：第{chapter_index}章失败已跳过",
            )
            continue
        assert chapter_dict is not None
        logger.info("[auto_build_setup] 第{}章「{}」已写入", chapter_index, chapter_dict["title"])
        written += 1
        prior_summary = await _summarize_chapter(prior_summary, chapter_dict, call_llm)
        await emit_tool_progress(
            "auto_build_setup",
            f"章节 {chapter_index}/{chapter_count}：已建「{chapter_dict['title']}」",
        )
    return written, errors


async def _generate_one_chapter_core(**kwargs: Any) -> tuple[bool, str]:
    """Thin re-export, same reasoning as _add_character_core -- lazy import avoids a top-level
    circular import with tools.py."""
    from engine.setup_chat.tools import _generate_one_chapter_impl as _real
    return await _real(**kwargs)


async def _construct_world_core(**kwargs: Any) -> str:
    from engine.setup_chat.tools import construct_world as _real
    result = await _real.ainvoke(kwargs)
    return result if isinstance(result, str) else str(result)


def _summary_line(label: str, succeeded: int, requested: int, errors: list[str]) -> str:
    line = f"{label}：{succeeded}/{requested}"
    if errors:
        line += "（" + "；".join(errors) + "）"
    return line


async def run_auto_build(
    brief: str, character_count: int, chapter_count: int, call_llm: CallLLM,
) -> str:
    """Top-level entry point -- the only thing tools.py::auto_build_setup calls. World is a
    hard prerequisite (characters/chapters need it grounded): a world failure aborts the whole
    build immediately with no characters/chapters attempted.

    Each of the three phases independently checks whether the current novel's imported research
    library (novel_import.py) has anything for that phase's category -- an import-grounded
    roster (_load_imported_characters) skips plan_character_outline entirely in favor of
    plan_character_roles_and_relationships (roles/relationships only, names/personas/verbal_tics
    are locked from extraction); world/plot reference text is soft grounding context appended to
    the existing from-scratch prompts, not a hard branch. A partial import (e.g. only world facts,
    no characters) is fine -- each phase degrades to its from-scratch behavior independently when
    its own category is empty.

    The roster/outline (character phase planning) is a hard prerequisite for the character phase
    specifically: a planning failure skips characters entirely (no fallback to independent
    per-character drafting) but still lets chapters proceed with character_names possibly empty.
    Character and chapter failures are otherwise best-effort -- partial success is still reported
    and kept, not rolled back."""
    logger.info(
        "[auto_build_setup] === 开始一键构建：character_count={} chapter_count={} ===",
        character_count, chapter_count,
    )
    world_reference = _load_imported_world_reference()
    plot_reference = _load_imported_plot_reference()
    imported_roster = _load_imported_characters(cap=character_count)

    world_bible, world_errors = await build_world(brief, call_llm, reference_text=world_reference)
    if world_bible is None:
        logger.error("[auto_build_setup] 世界观生成失败，未构建任何内容：{}", "、".join(world_errors))
        return "世界观生成失败，未构建任何内容：" + "、".join(world_errors)
    await _construct_world_core(**world_bible)

    race_names = [
        r["name"] for r in (world_bible.get("races") or [])
        if isinstance(r, dict) and r.get("name")
    ]
    logger.debug("[auto_build_setup] 世界观已建，声明种族：{}", race_names or "（无）")

    if imported_roster:
        roles_result, outline_errors = await plan_character_roles_and_relationships(
            brief, imported_roster, world_bible, call_llm,
        )
        if roles_result is None:
            outline: dict[str, Any] | None = None
        else:
            role_by_name = {c["given_name"]: c["role"] for c in roles_result["characters"]}
            outline = {
                "characters": [
                    {
                        "given_name": c["given_name"],
                        "role": role_by_name.get(c["given_name"], "角色"),
                        "persona": c["personality"] or "（性格待补全）",
                        "verbal_tic": c["verbal_tic"],
                    }
                    for c in imported_roster
                ],
                "relationships": roles_result["relationships"],
            }
    else:
        outline, outline_errors = await plan_character_outline(brief, character_count, world_bible, call_llm)

    if outline is None:
        logger.error("[auto_build_setup] 角色阵容规划失败，跳过角色阶段：{}", "、".join(outline_errors))
        characters: list[dict[str, Any]] = []
        char_errors = [f"角色阵容规划失败：{'、'.join(outline_errors)}"]
    else:
        characters, char_errors = await build_characters(
            brief, outline, call_llm, race_names=race_names,
        )
    character_names = [c.get("given_name", "") for c in characters if c.get("given_name")]
    requested_character_count = len(imported_roster) if imported_roster else character_count
    logger.info(
        "[auto_build_setup] 角色阶段完成：{}/{} 成功，{}",
        len(characters), requested_character_count, char_errors or "无错误",
    )

    chapters_written, chapter_errors = await build_chapters(
        brief, character_names, chapter_count, call_llm, reference_text=plot_reference,
    )
    logger.info(
        "[auto_build_setup] === 一键构建结束：章节 {}/{} 成功，{} ===",
        chapters_written, chapter_count, chapter_errors or "无错误",
    )

    return "\n".join([
        "世界观已建。",
        _summary_line("角色", len(characters), requested_character_count, char_errors),
        _summary_line("章节", chapters_written, chapter_count, chapter_errors),
    ])
