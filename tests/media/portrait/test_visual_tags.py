from __future__ import annotations

import pytest


class _FakeLLM:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[list] = []

    async def ainvoke(self, messages):
        self.calls.append(messages)

        class _Resp:
            content = self.reply

        return _Resp()


def test_describe_character_visual_only_includes_visible_fields():
    from media.portrait.visual_tags import _describe_character_visual

    char = {
        "gender": "female", "physique": {"体型": "娇小"},
        "clothing_dna": {"signature_outfit": "白衬衫"},
        "personality": "傲娇", "identity_background": "没落贵族",
    }
    described = _describe_character_visual(char)

    assert "娇小" in described
    assert "白衬衫" in described
    assert "female" in described
    assert "傲娇" not in described
    assert "没落贵族" not in described


@pytest.mark.asyncio
async def test_extract_visual_tags_without_directive(monkeypatch):
    from context import content_packs as cp
    from media.portrait import visual_tags

    monkeypatch.setattr(cp, "active_portrait_directive", lambda: None)
    fake_llm = _FakeLLM("1girl, silver hair, red eyes")
    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: fake_llm)

    char = {"gender": "female", "physique": {"体型": "娇小"}, "clothing_dna": {}}
    result = await visual_tags.extract_visual_tags(char)

    assert result == "1girl, silver hair, red eyes"
    system_msg = fake_llm.calls[0][0]
    assert "adult" not in system_msg.content.lower()


@pytest.mark.asyncio
async def test_extract_visual_tags_system_prompt_forbids_numeric_age(monkeypatch):
    """Regression for the 2026-08-10 age-tag leak: physique/clothing_dna text sometimes
    embeds an age mention (e.g. '17岁'), and the tag LLM would otherwise echo it back as
    an explicit age tag (e.g. '17yo') -- a pattern that trips third-party image platforms'
    content filters. See media.portrait.visual_tags._SYSTEM_PROMPT."""
    from context import content_packs as cp
    from media.portrait import visual_tags

    monkeypatch.setattr(cp, "active_portrait_directive", lambda: None)
    fake_llm = _FakeLLM("1girl, silver hair, red eyes")
    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: fake_llm)

    char = {"gender": "female", "physique": {"体型": "娇小,看起来才17岁"}, "clothing_dna": {}}
    await visual_tags.extract_visual_tags(char)

    system_content = fake_llm.calls[0][0].content
    assert "age" in system_content.lower()
    assert "never include" in system_content.lower()


@pytest.mark.asyncio
async def test_extract_visual_tags_system_prompt_forbids_multi_person_leak(monkeypatch):
    """Regression: physique text often describes a character relative to a sibling/twin
    (e.g. '和双双是双胞胎但骨架更软更纤细' -- 'twin sister but softer, more slender frame')
    for narrative flavor. Without guidance the tag LLM can echo the comparison/second
    person straight into the output, producing a prompt that describes two people instead
    of the one character this portrait is for. See media.portrait.visual_tags._SYSTEM_PROMPT."""
    from context import content_packs as cp
    from media.portrait import visual_tags

    monkeypatch.setattr(cp, "active_portrait_directive", lambda: None)
    fake_llm = _FakeLLM("1girl, silver hair, red eyes")
    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: fake_llm)

    char = {
        "gender": "female",
        "physique": {"体型": "和双胞胎姐姐相比骨架更软更纤细，看起来比姐姐小一号"},
        "clothing_dna": {},
    }
    await visual_tags.extract_visual_tags(char)

    system_content = fake_llm.calls[0][0].content
    assert "one person" in system_content.lower() or "single" in system_content.lower()
    assert "2girls" in system_content.lower()


@pytest.mark.asyncio
async def test_extract_visual_tags_appends_directive_when_active(monkeypatch):
    from context import content_packs as cp
    from media.portrait import visual_tags

    monkeypatch.setattr(cp, "active_portrait_directive", lambda: "custom portrait directive text")
    fake_llm = _FakeLLM("1girl, masterpiece, cinematic lighting")
    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: fake_llm)

    char = {"gender": "female", "physique": {}, "clothing_dna": {}}
    await visual_tags.extract_visual_tags(char)

    system_content = fake_llm.calls[0][0].content
    assert "custom portrait directive text" in system_content


@pytest.mark.asyncio
async def test_extract_and_persist_visual_tags_writes_only_target_character(monkeypatch):
    from media.portrait import visual_tags

    async def fake_extract(character):
        assert character["name"] == "甲"
        return "1girl, silver hair"

    monkeypatch.setattr(visual_tags, "extract_visual_tags", fake_extract)

    saved = {}

    class _FakeRepo:
        def list_raw(self):
            return [
                {"name": "甲", "gender": "female"},
                {"name": "乙", "gender": "male"},
            ]

        def save_all(self, roster):
            saved["roster"] = roster

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)
    monkeypatch.setattr("utils.paths.use_novel", lambda novel_id: _NullContext())

    result = await visual_tags.extract_and_persist_visual_tags(
        "novel-1", "甲", {"name": "甲", "gender": "female"},
    )

    assert result == "1girl, silver hair"
    assert saved["roster"][0]["portrait_visual_tags"] == "1girl, silver hair"
    assert "portrait_visual_tags" not in saved["roster"][1]


class _NullContext:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False
