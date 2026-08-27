import json

import pytest
from engine.setup_chat.memory import make_pre_model_hook
from engine.setup_chat.novel_context import (
    build_inherited_setup_context,
    build_novel_setup_status,
    strip_novel_context_for_display,
)
from langchain_core.messages import SystemMessage

from repo_test_helpers import init_store, seed_lore, seed_plot, seed_world


def _isolate_novel(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path / "novels"))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "default")
    (tmp_path / "novels" / "default").mkdir(parents=True, exist_ok=True)
    (tmp_path / "novels" / "active.json").write_text(
        json.dumps({"active": "default"}), encoding="utf-8"
    )
    import repositories

    repositories.drop_repositories("default")
    repositories.reset_repositories()


def test_build_status_reports_all_pending_when_empty_novel(tmp_path, monkeypatch):
    _isolate_novel(tmp_path, monkeypatch)
    init_store()

    status = build_novel_setup_status()
    assert "世界观：未建" in status
    assert "角色：未建" in status
    assert "剧情：未建" in status


def test_build_context_always_includes_status_even_when_empty(tmp_path, monkeypatch):
    _isolate_novel(tmp_path, monkeypatch)
    init_store()

    ctx = build_inherited_setup_context()
    assert "当前小说构建状态" in ctx
    assert "世界观：未建" in ctx
    assert "角色：未建" in ctx
    assert "剧情：未建" in ctx


def test_build_context_includes_world_summary_when_world_exists(tmp_path, monkeypatch):
    _isolate_novel(tmp_path, monkeypatch)
    seed_world({"background": "剑客传奇", "tone": "苍凉"})

    ctx = build_inherited_setup_context()
    assert "世界观：未建" in ctx
    assert "剑客传奇" in ctx
    assert "角色 schema" not in ctx
    assert "清空对话后仍有效" in ctx


def test_build_status_counts_cast_and_plot(tmp_path, monkeypatch):
    _isolate_novel(tmp_path, monkeypatch)
    seed_world({"background": "x"})
    seed_lore([
        {"name": "甲", "given_name": "甲", "role": "主角"},
        {"name": "乙", "given_name": "乙", "role": "配角"},
    ])
    seed_plot([
        {"chapter": 1, "title": "开端", "stages": []},
        {"chapter": 3, "title": "转折", "stages": []},
    ])

    status = build_novel_setup_status()
    assert "世界观：未建" in status
    assert "角色：2 人（甲、乙）" in status
    assert "剧情：2 章（第1章、第3章）" in status


def test_strip_novel_context_removes_status_block():
    injected = "## 当前小说构建状态\n- 世界观：未建\n\n用户可见正文"
    cleaned = strip_novel_context_for_display(injected)
    assert cleaned == "用户可见正文"


def test_strip_novel_context_removes_legacy_header():
    text = "## 当前小说已有设定\n\n### 世界观\n基调：苍凉\n\n正文"
    assert strip_novel_context_for_display(text) == "正文"


def test_strip_novel_context_removes_full_injected_block(tmp_path, monkeypatch):
    _isolate_novel(tmp_path, monkeypatch)
    seed_world({"background": "测试"})

    injected = build_inherited_setup_context() + "\n\n用户可见正文"
    assert strip_novel_context_for_display(injected) == "用户可见正文"


@pytest.mark.asyncio
async def test_pre_hook_injects_inherited_context(tmp_path, monkeypatch):
    _isolate_novel(tmp_path, monkeypatch)
    seed_world({"background": "测试梗概"})
    setup_chat = tmp_path / "novels" / "default" / "setup_chat"
    setup_chat.mkdir()

    async def call_llm(system, user):
        raise AssertionError("不该蒸馏")

    hook = make_pre_model_hook(lambda: str(setup_chat), call_llm, K=4, T=20)
    out = await hook({"messages": []})
    fed = out["llm_input_messages"]
    assert isinstance(fed[0], SystemMessage)
    assert "测试梗概" in fed[0].content
    assert "世界观：未建" in fed[0].content
