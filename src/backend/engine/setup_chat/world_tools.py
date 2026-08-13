"""Per-dimension setup-chat tools for world_bible (scalars + list-entry CRUD)."""
from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from engine.setup.chat_summary import format_tool_done
from engine.setup.world import world_ops as wo
from engine.setup_chat.tool_args import (
    AddWorldEntryArgs,
    AddWorldKeywordsEntryArgs,
    DeleteWorldEntryArgs,
    EditWorldEntryArgs,
    EditWorldKeywordsEntryArgs,
    RefineWorldBackgroundArgs,
    RefineWorldToneArgs,
    SetWorldBackgroundArgs,
    SetWorldToneArgs,
)
from engine.setup_chat.world_background_review import schedule_world_quality_review


async def _commit_world_write(
    doc: dict[str, Any],
    *,
    changed_field: str,
    success_title: str,
    body: str = "",
) -> str:
    from utils.paths import active_novel_id

    from engine.setup_chat.world_background_review import cancel_active_world_review_or_fix

    await cancel_active_world_review_or_fix(active_novel_id())
    saved, err = wo.persist_world_doc(doc, changed_field=changed_field)
    if not saved:
        return err
    schedule_world_quality_review()
    return format_tool_done(success_title, body)


def _make_scalar_tools(
    field: str,
    label: str,
    set_args: type,
    refine_args: type,
) -> tuple[BaseTool, BaseTool]:
    async def set_fn(**kwargs: Any) -> str:
        value = next(iter(kwargs.values()))
        ok, err, doc = wo.set_scalar_field(field, value)
        if not ok:
            return err
        return await _commit_world_write(
            doc,
            changed_field=field,
            success_title=f"已写入{label}。",
            body=str(doc.get(field, "")),
        )

    async def refine_fn(**kwargs: Any) -> str:
        value = next(iter(kwargs.values()))
        ok, err, doc = wo.refine_scalar_field(field, value)
        if not ok:
            return err
        return await _commit_world_write(
            doc,
            changed_field=field,
            success_title=f"已更新{label}。",
            body=str(doc.get(field, "")),
        )

    set_tool = StructuredTool.from_function(
        coroutine=set_fn,
        name=f"set_world_{field}",
        description=f"首次写入世界观「{label}」。该字段已有内容时须改用 refine_world_{field}。",
        args_schema=set_args,
    )
    refine_tool = StructuredTool.from_function(
        coroutine=refine_fn,
        name=f"refine_world_{field}",
        description=f"修改已有世界观「{label}」全文。字段尚未构建时须先用 set_world_{field}。",
        args_schema=refine_args,
    )
    return set_tool, refine_tool


def _make_list_tools(
    field: str,
    label: str,
    singular: str,
    list_name: str,
    *,
    with_keywords: bool,
) -> tuple[BaseTool, BaseTool, BaseTool, BaseTool]:
    add_schema = AddWorldKeywordsEntryArgs if with_keywords else AddWorldEntryArgs
    edit_schema = EditWorldKeywordsEntryArgs if with_keywords else EditWorldEntryArgs

    async def add_fn(**kwargs: Any) -> str:
        args = add_schema.model_validate(kwargs)
        item = args.model_dump()
        ok, err, doc = wo.add_list_entry(field, item)
        if not ok:
            return err
        return await _commit_world_write(
            doc,
            changed_field=field,
            success_title=f"已添加{label}「{args.name}」。",
            body=wo.render_list_field(field),
        )

    async def edit_fn(**kwargs: Any) -> str:
        args = edit_schema.model_validate(kwargs)
        kw = getattr(args, "keywords", None) if with_keywords else None
        ok, err, doc = wo.edit_list_entry(
            field,
            args.name,
            desc=args.desc,
            keywords=kw,
        )
        if not ok:
            return err
        return await _commit_world_write(
            doc,
            changed_field=field,
            success_title=f"已更新{label}「{args.name}」。",
            body=wo.render_list_field(field),
        )

    async def delete_fn(**kwargs: Any) -> str:
        args = DeleteWorldEntryArgs.model_validate(kwargs)
        ok, err, doc = wo.remove_list_entry(field, args.name)
        if not ok:
            return err
        from utils.paths import active_novel_id

        from engine.setup_chat.world_background_review import cancel_active_world_review_or_fix

        await cancel_active_world_review_or_fix(active_novel_id())
        saved, save_err = wo.persist_world_doc(doc, changed_field=field)
        if not saved:
            return save_err
        schedule_world_quality_review()
        return format_tool_done(
            f"已删除{label}「{args.name}」。",
            wo.render_list_field(field),
        )

    def list_fn() -> str:
        return wo.render_list_field(field)

    kw_hint = "；支持 keywords" if with_keywords else ""
    add_tool = StructuredTool.from_function(
        coroutine=add_fn,
        name=f"add_world_{singular}",
        description=f"向世界观「{label}」新增一条 entry（name 在该维度内唯一{kw_hint}）。",
        args_schema=add_schema,
    )
    edit_tool = StructuredTool.from_function(
        coroutine=edit_fn,
        name=f"edit_world_{singular}",
        description=f"修改「{label}」中已有 entry 的 desc{kw_hint}（按 name 精确匹配，不支持改名）。",
        args_schema=edit_schema,
    )
    delete_tool = StructuredTool.from_function(
        coroutine=delete_fn,
        name=f"delete_world_{singular}",
        description=f"从「{label}」删除指定 entry（按 name 精确匹配）。",
        args_schema=DeleteWorldEntryArgs,
    )
    list_tool = StructuredTool.from_function(
        func=list_fn,
        name=list_name,
        description=f"列出当前世界观「{label}」的全部 entry。",
    )
    return add_tool, edit_tool, delete_tool, list_tool


_LIST_TOOL_SPECS: tuple[tuple[str, str, str, str, bool], ...] = (
    ("factions", "势力", "faction", "list_world_factions", False),
    ("geography", "地理", "geography", "list_world_geographies", False),
    ("races", "种族", "race", "list_world_races", False),
    ("power_system", "力量体系", "power_system", "list_world_power_systems", True),
    ("core_themes", "核心主题", "core_theme", "list_world_core_themes", True),
)


def build_world_dimension_tools() -> list[BaseTool]:
    tools: list[BaseTool] = []
    bg_set, bg_ref = _make_scalar_tools(
        "background", "世界背景", SetWorldBackgroundArgs, RefineWorldBackgroundArgs,
    )
    tone_set, tone_ref = _make_scalar_tools(
        "tone", "基调", SetWorldToneArgs, RefineWorldToneArgs,
    )
    tools.extend([bg_set, bg_ref, tone_set, tone_ref])
    for field, label, singular, list_name, with_kw in _LIST_TOOL_SPECS:
        tools.extend(_make_list_tools(field, label, singular, list_name, with_keywords=with_kw))
    return tools


WORLD_PIPELINE_TOOL_NAMES: frozenset[str] = frozenset(
    t.name for t in build_world_dimension_tools()
)

# Stable import surface for agent registration (built once at import).
WORLD_DIMENSION_TOOLS: list[BaseTool] = build_world_dimension_tools()
