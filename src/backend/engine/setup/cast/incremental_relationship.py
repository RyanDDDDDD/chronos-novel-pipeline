"""Incremental relationship-graph generation: one LLM call per newly-created character,
comparing it against the already-established roster to infer any social-relationship edges.
Replaces the old whole-roster batch generator (runner.py, deleted -- had zero production
callers since setup_chat's conversational add_character tool never invoked it).

Fully degrade-on-failure at every step (LLM call, JSON parse, per-edge validation) -- this
runs as a fire-and-forget background task off engine.setup_chat.tools.py::_add_character_core
and must never raise, since a failure here must never affect character creation itself. See
docs/superpowers/specs/2026-07-20-relationship-graph-incremental-edges-design.md."""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from loguru import logger

from engine.setup.cast.relationship_graph import append_edge, validate_edge

CallLLM = Callable[[str, str], Awaitable[str]]

_RELEVANT_FIELDS = (
    ("role", "定位"), ("race", "种族"),
    ("identity_background", "身份背景"), ("personality", "人格"),
)

_SYS = (
    "你是角色关系推断助手。给定一个刚创建的新角色 + 已有花名册，判断新角色与花名册中每个角色"
    "是否存在**社交关系**（心动/倾慕这类不算，那是状态系统按剧情演变的情感关系，这里只管"
    "开篇即存在的社交事实——师徒/血亲姐妹/同门同宗/退婚婚约/上下级/世仇/青梅竹马等）。\n"
    "能从双方设定明确推出关系才写，推不出的就不写（当陌生人，宁缺毋滥）——多数角色之间没有"
    "关系，这正常。\n"
    "推断 relationship_anchor（from 对 to 的初始情结短句）时，须结合双方档案里的因果锚点"
    "（创伤/执念/渴望等）——情结应能反映这些锚点在两人关系中的投射或碰撞，而非泛泛的客套描述。"
    "每条关系输出一条边：from/to 用花名册里的 given_name（方向只表示这条关系记录的起止方，"
    "不代表主从关系）；nature 写关系性质；relationship_anchor 写 from 对 to 的初始情结短句"
    "（无则空串）；from_ref_terms/to_ref_terms 是这段关系里区别于本名的第三人称称呼（比如"
    "师徒关系里 to 称 from 为「师傅」，兄妹关系里对应称「妹妹」/「哥哥」），没有这种称呼就"
    "留空数组，不要硬凑。\n"
    "只输出一个 JSON 数组，形如：\n"
    '[{"from": "...", "to": "...", "nature": "...", "relationship_anchor": "...", '
    '"from_ref_terms": [], "to_ref_terms": []}]\n'
    "没有任何关系就输出空数组 []。不要输出数组以外的任何文字。"
)


def _char_name(c: dict) -> str:
    return str(c.get("given_name") or c.get("name") or "").strip()


def _render_char_brief(c: dict) -> str:
    lines = [f"角色：{_char_name(c)}"]
    for field, label in _RELEVANT_FIELDS:
        v = c.get(field)
        if v:
            lines.append(f"{label}：{v}")
    anchors = c.get("causal_anchors")
    if isinstance(anchors, dict) and anchors:
        lines.append("因果锚点：" + "；".join(f"{k}：{v}" for k, v in anchors.items()))
    return "\n".join(lines)


def _default_call_llm() -> CallLLM:
    from langchain_core.messages import HumanMessage, SystemMessage
    from llm.factory import get_cloud_llm

    from engine.modes.author_loop_skill_prefs import bind_node_llm, load_dialogue_prefs

    llm = bind_node_llm(
        get_cloud_llm(),
        "incremental_relationship",
        load_dialogue_prefs()["import_llm_params"],
    )

    async def call_llm(system: str, user: str) -> str:
        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        return content.strip()

    return call_llm


async def generate_edges_for_new_character(
    new_char: dict,
    existing_roster: list[dict],
    *,
    call_llm: CallLLM | None = None,
    edges_path: str | None = None,
) -> list[dict]:
    """新角色入库后的增量关系推断：新角色 + 已有花名册整体喂给一次 LLM 调用，产出的每条边
    校验通过后逐条 append_edge()。existing_roster 为空（第一个角色）直接返回 []，不调用 LLM。
    返回值是实际写入的边列表（供调用方/测试观察，不是调用方需要的必需返回值）。"""
    if not existing_roster:
        return []

    from engine.execution.embed_json import parse_embed_json

    caller = call_llm or _default_call_llm()
    user = (
        "## 新角色\n" + _render_char_brief(new_char)
        + "\n\n## 已有花名册\n"
        + "\n\n".join(_render_char_brief(c) for c in existing_roster)
    )
    try:
        raw = await caller(_SYS, user)
    except Exception as e:  # noqa: BLE001 — 后台旁路任务，失败只降级，绝不向上抛
        logger.warning("[cast] 新角色「{}」关系推断 LLM 调用失败：{}", _char_name(new_char), e)
        return []

    candidates = parse_embed_json(raw)
    raw_stripped = raw.strip()
    if not candidates and raw_stripped and raw_stripped != "[]":
        logger.warning(
            "[cast] 新角色「{}」关系推断 JSON 解析失败或结果为空（raw 非空且非 []）",
            _char_name(new_char),
        )
    names = {_char_name(c) for c in [*existing_roster, new_char] if _char_name(c)}
    appended: list[dict] = []
    for edge in candidates:
        if not isinstance(edge, dict):
            continue
        errs = validate_edge(edge, names)
        if errs:
            logger.warning("[cast] 新角色关系边校验未过，丢弃：{}", "；".join(errs))
            continue
        try:
            append_edge(edge, path=edges_path)
        except OSError as e:
            logger.warning(
                "[cast] 新角色「{}」关系边写入失败，跳过：{}",
                _char_name(new_char),
                e,
            )
            continue
        appended.append(edge)

    if appended:
        from engine.memory_recall.entity_index import invalidate_entity_vocab_cache

        invalidate_entity_vocab_cache()
    return appended
