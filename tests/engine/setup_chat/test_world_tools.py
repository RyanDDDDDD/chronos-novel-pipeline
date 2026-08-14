import pytest

from engine.setup_chat.world_tools import (
    WORLD_PIPELINE_TOOL_NAMES,
    build_world_dimension_tools,
)
from repo_test_helpers import get_world, init_store, seed_world


def test_world_pipeline_tool_count():
    tools = build_world_dimension_tools()
    assert len(tools) == 24
    assert len(WORLD_PIPELINE_TOOL_NAMES) == 24


@pytest.mark.asyncio
async def test_set_world_background(monkeypatch):
    init_store()

    def _noop(**_k):
        return None

    monkeypatch.setattr(
        "engine.setup_chat.world_tools.schedule_world_quality_review",
        _noop,
    )
    tool = next(t for t in build_world_dimension_tools() if t.name == "set_world_background")
    out = await tool.ainvoke({"background": "末法时代，诸国争锋"})
    assert "已写入" in out
    saved = get_world()
    assert saved is not None
    assert saved["background"] == "末法时代，诸国争锋"


@pytest.mark.asyncio
async def test_set_world_background_rejects_when_exists():
    seed_world({"background": "已有"})
    tool = next(t for t in build_world_dimension_tools() if t.name == "set_world_background")
    out = await tool.ainvoke({"background": "新的"})
    assert "refine_world_background" in out


@pytest.mark.asyncio
async def test_add_and_list_world_faction(monkeypatch):
    init_store()

    def _noop(**_k):
        return None

    monkeypatch.setattr(
        "engine.setup_chat.world_tools.schedule_world_quality_review",
        _noop,
    )
    add_tool = next(t for t in build_world_dimension_tools() if t.name == "add_world_faction")
    list_tool = next(t for t in build_world_dimension_tools() if t.name == "list_world_factions")
    out = await add_tool.ainvoke({"name": "甲帮", "desc": "控制北方贸易的帮派"})
    assert "已添加" in out
    listed = list_tool.invoke({})
    assert "甲帮" in listed
    saved = get_world()
    assert saved is not None
    assert saved["factions"][0]["name"] == "甲帮"


@pytest.mark.asyncio
async def test_edit_world_faction(monkeypatch):
    seed_world({"factions": [{"name": "甲帮", "desc": "旧描述"}]})

    def _noop(**_k):
        return None

    monkeypatch.setattr(
        "engine.setup_chat.world_tools.schedule_world_quality_review",
        _noop,
    )
    edit_tool = next(t for t in build_world_dimension_tools() if t.name == "edit_world_faction")
    out = await edit_tool.ainvoke({"name": "甲帮", "desc": "新描述"})
    assert "已更新" in out
    # Regression: the returned preview must reflect the post-write state, not a snapshot
    # read before persist_world_doc ran (see world_tools._commit_world_write render_body).
    assert "新描述" in out
    assert "旧描述" not in out
    saved = get_world()
    assert saved is not None
    assert saved["factions"][0]["desc"] == "新描述"


@pytest.mark.asyncio
async def test_delete_world_faction():
    seed_world({"factions": [{"name": "甲帮", "desc": "d"}]})
    delete_tool = next(t for t in build_world_dimension_tools() if t.name == "delete_world_faction")
    out = await delete_tool.ainvoke({"name": "甲帮"})
    assert "已删除" in out
    saved = get_world()
    assert saved is not None
    assert saved["factions"] == []


@pytest.mark.asyncio
async def test_set_world_background_cancels_active_fix_before_writing(monkeypatch):
    init_store()
    monkeypatch.setattr(
        "engine.setup_chat.world_tools.schedule_world_quality_review", lambda **_k: None,
    )
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")
    calls = []

    async def fake_cancel(novel_id):
        calls.append(novel_id)

    monkeypatch.setattr(
        "engine.setup_chat.world_background_review.cancel_active_world_review_or_fix", fake_cancel,
    )

    tool = next(t for t in build_world_dimension_tools() if t.name == "set_world_background")
    out = await tool.ainvoke({"background": "末法时代，诸国争锋"})

    assert "已写入" in out
    assert calls == ["n"]


@pytest.mark.asyncio
async def test_delete_world_faction_cancels_active_fix_before_writing(monkeypatch):
    seed_world({"factions": [{"name": "甲帮", "desc": "旧描述"}]})
    monkeypatch.setattr(
        "engine.setup_chat.world_tools.schedule_world_quality_review", lambda **_k: None,
    )
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")
    calls = []

    async def fake_cancel(novel_id):
        calls.append(novel_id)

    monkeypatch.setattr(
        "engine.setup_chat.world_background_review.cancel_active_world_review_or_fix", fake_cancel,
    )

    delete_tool = next(t for t in build_world_dimension_tools() if t.name == "delete_world_faction")
    out = await delete_tool.ainvoke({"name": "甲帮"})

    assert "已删除" in out
    assert calls == ["n"]
