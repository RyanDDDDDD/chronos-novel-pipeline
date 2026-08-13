"""单拍联合台词草稿：机制照搬 engine.story_sandbox.dialogue_draft.draft_dialogue（同一套输出
格式），依据换成构建期能拿到的东西（见 dialogue_draft.py 模块 docstring）。"""
import pytest


@pytest.mark.asyncio
async def test_draft_beat_dialogue_skips_when_no_characters(monkeypatch):
    from engine.setup_chat import dialogue_draft as dd

    async def fail_if_called(system, user, **kwargs):
        raise AssertionError("must not call the LLM when there are no present characters")
    monkeypatch.setattr(dd, "_call_llm", fail_if_called)

    result = await dd.draft_beat_dialogue(1, 1, "拍正文", [], "")
    assert result == ""


@pytest.mark.asyncio
async def test_draft_beat_dialogue_grounds_on_beat_text_cards_and_prev_text(monkeypatch):
    from engine.setup_chat import dialogue_draft as dd

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.cards.render_character_card",
        lambda name, ch, sg, **kw: f"[{name}的卡]",
    )
    captured = {}

    async def fake_call(system, user, **kwargs):
        captured["system"] = system
        return "甲（意图：试探；动作/心理：皱眉）：你想干什么。"
    monkeypatch.setattr(dd, "_call_llm", fake_call)

    result = await dd.draft_beat_dialogue(1, 1, "这一拍的骨架正文", ["甲"], "上一拍已写的正文")
    assert result == "甲（意图：试探；动作/心理：皱眉）：你想干什么。"
    assert "[甲的卡]" in captured["system"]
    assert "这一拍的骨架正文" in captured["system"]
    assert "上一拍已写的正文" in captured["system"]
    assert "约 2 行台词" in captured["system"]  # turn_count = len(characters) + 1


@pytest.mark.asyncio
async def test_draft_beat_dialogue_omits_prev_text_block_when_empty(monkeypatch):
    from engine.setup_chat import dialogue_draft as dd

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.cards.render_character_card",
        lambda name, ch, sg, **kw: "卡",
    )
    captured = {}

    async def fake_call(system, user, **kwargs):
        captured["system"] = system
        return ""
    monkeypatch.setattr(dd, "_call_llm", fake_call)

    await dd.draft_beat_dialogue(1, 1, "拍正文", ["甲"], "")
    assert "最近上下文" not in captured["system"]


@pytest.mark.asyncio
async def test_draft_beat_dialogue_degrades_to_empty_on_llm_failure(monkeypatch):
    from engine.setup_chat import dialogue_draft as dd

    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.cards.render_character_card",
        lambda name, ch, sg, **kw: "卡",
    )

    async def boom(system, user, **kwargs):
        raise RuntimeError("network down")
    monkeypatch.setattr(dd, "_call_llm", boom)

    result = await dd.draft_beat_dialogue(1, 1, "拍正文", ["甲"], "")
    assert result == ""
