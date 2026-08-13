import pytest
from engine.setup_chat import skills
from engine.story_sandbox import skill_suggest


def test_parse_skill_hint_matches_registered_plot_extension(monkeypatch):
    monkeypatch.setattr(skills, "list_skill_index", lambda dirs: [
        {"name": "example-action-skill", "description": "", "kind": "plot-extension", "source": "builtin"},
    ])
    name, rest = skill_suggest.parse_skill_hint("/example-action-skill 两人在船上")
    assert name == "example-action-skill"
    assert rest == "两人在船上"


def test_parse_skill_hint_no_slash_returns_none_and_original_text():
    name, rest = skill_suggest.parse_skill_hint("往乙这边的反应上靠一点")
    assert name is None
    assert rest == "往乙这边的反应上靠一点"


def test_parse_skill_hint_unregistered_name_returns_none(monkeypatch):
    monkeypatch.setattr(skills, "list_skill_index", lambda dirs: [
        {"name": "example-action-skill", "description": "", "kind": "plot-extension", "source": "builtin"},
    ])
    name, rest = skill_suggest.parse_skill_hint("/not-registered 继续")
    assert name is None
    assert rest == "/not-registered 继续"


def test_parse_skill_hint_rejects_non_plot_extension_kind(monkeypatch):
    monkeypatch.setattr(skills, "list_skill_index", lambda dirs: [
        {"name": "world-interview", "description": "", "kind": "", "source": "builtin"},
    ])
    name, rest = skill_suggest.parse_skill_hint("/world-interview 继续")
    assert name is None
    assert rest == "/world-interview 继续"


@pytest.mark.asyncio
async def test_run_skill_suggestion_parses_final_answer(monkeypatch):
    monkeypatch.setattr(skills, "load_skill_body", lambda name, dirs: f"BODY::{name}")
    monkeypatch.setattr(skills, "collect_single_skill_tools", lambda skills_dir, name: ["tool-x"])

    seen = {}

    async def _fake_agent(system: str, user: str, tools: list) -> str:
        seen["system"] = system
        seen["user"] = user
        seen["tools"] = tools
        return '["候选一", "候选二"]'

    result = await skill_suggest.run_skill_suggestion(
        "example-action-skill", "刚写的正文", {"甲": {"psychology": "紧张"}}, _fake_agent,
        hint="补充提示", core_xp=["猎奇"], cards=[{"name": "甲", "card": "角色：甲"}],
    )
    assert result == ["候选一", "候选二"]
    assert seen["tools"] == ["tool-x"]
    assert "BODY::example-action-skill" in seen["system"]
    assert "刚写的正文" in seen["user"]
    assert "补充提示" in seen["user"]
    assert "角色：甲" in seen["user"]
    assert "猎奇" in seen["user"]


@pytest.mark.asyncio
async def test_run_skill_suggestion_renders_related_cards_as_background_only(monkeypatch):
    monkeypatch.setattr(skills, "load_skill_body", lambda name, dirs: "BODY")
    monkeypatch.setattr(skills, "collect_single_skill_tools", lambda skills_dir, name: [])

    seen = {}

    async def _fake_agent(system: str, user: str, tools: list) -> str:
        seen["user"] = user
        return "[]"

    await skill_suggest.run_skill_suggestion(
        "example-action-skill", "正文", {}, _fake_agent,
        cards=[{"name": "甲", "card": "角色：甲"}],
        related_cards=[{"name": "角色甲", "card": "角色：角色甲"}],
    )
    assert "角色：甲" in seen["user"]
    assert "相关角色档案" in seen["user"]
    assert "角色甲" in seen["user"]
    assert "默认不要让他们出现或行动" in seen["user"]


@pytest.mark.asyncio
async def test_run_skill_suggestion_includes_recall_block_in_user_prompt(monkeypatch):
    monkeypatch.setattr(skills, "load_skill_body", lambda name, dirs: "BODY")
    monkeypatch.setattr(skills, "collect_single_skill_tools", lambda skills_dir, name: [])

    seen = {}

    async def _fake_agent(system: str, user: str, tools: list) -> str:
        seen["user"] = user
        return "[]"

    await skill_suggest.run_skill_suggestion(
        "example-action-skill", "正文", {}, _fake_agent,
        recall_block="## 相关历史/设定回收\n- 【蛊虫】寄生方式驱动力量",
    )
    assert "## 相关历史/设定回收" in seen["user"]
    assert "蛊虫" in seen["user"]


@pytest.mark.asyncio
async def test_run_skill_suggestion_omits_recall_section_when_empty(monkeypatch):
    monkeypatch.setattr(skills, "load_skill_body", lambda name, dirs: "BODY")
    monkeypatch.setattr(skills, "collect_single_skill_tools", lambda skills_dir, name: [])

    seen = {}

    async def _fake_agent(system: str, user: str, tools: list) -> str:
        seen["user"] = user
        return "[]"

    await skill_suggest.run_skill_suggestion("example-action-skill", "正文", {}, _fake_agent)
    assert "设定回收" not in seen["user"]


@pytest.mark.asyncio
async def test_run_skill_suggestion_returns_empty_list_on_bad_json(monkeypatch):
    monkeypatch.setattr(skills, "load_skill_body", lambda name, dirs: "BODY")
    monkeypatch.setattr(skills, "collect_single_skill_tools", lambda skills_dir, name: [])

    async def _fake_agent(system: str, user: str, tools: list) -> str:
        return "不是 JSON"

    result = await skill_suggest.run_skill_suggestion(
        "example-bridges", "正文", {}, _fake_agent,
    )
    assert result == []


@pytest.mark.asyncio
async def test_run_skill_suggestion_returns_empty_list_when_body_missing(monkeypatch):
    monkeypatch.setattr(skills, "load_skill_body", lambda name, dirs: None)

    async def _fake_agent(system: str, user: str, tools: list) -> str:
        raise AssertionError("should not be called when body is missing")

    result = await skill_suggest.run_skill_suggestion(
        "missing-skill", "正文", {}, _fake_agent,
    )
    assert result == []
