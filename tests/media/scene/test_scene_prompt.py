from __future__ import annotations

import pytest


class _FakeLLM:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list = []

    async def ainvoke(self, messages):
        self.calls.append(messages)

        class _R:
            content = self.reply
        return _R()


@pytest.mark.asyncio
async def test_build_scene_prompt_maps_characters_in_order(monkeypatch):
    from media.scene import scene_prompt

    fake = _FakeLLM(
        '{"base": "tavern interior, candlelight, night, medium shot", '
        '"characters": [{"name": "阿明", "caption": "1boy, black hair, arms crossed"}, '
        '{"name": "阿婉", "caption": "1girl, silver hair, holding teacup"}]}'
    )
    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: fake)

    r = await scene_prompt.build_scene_prompt(
        memory_entry={"summary": "阿明向阿婉摊牌", "time": "深夜", "location": "酒馆",
                      "characters": ["阿明", "阿婉"]},
        character_visual_tags={"阿明": "1boy, black hair", "阿婉": "1girl, silver hair"},
    )
    assert r.base.startswith("tavern interior")
    assert [c["name"] for c in r.characters] == ["阿明", "阿婉"]
    user = fake.calls[0][1].content
    assert "阿明" in user and "1boy, black hair" in user and "酒馆" in user


@pytest.mark.asyncio
async def test_build_scene_prompt_degrades_on_bad_json(monkeypatch):
    from media.scene import scene_prompt

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM("not json at all"))
    r = await scene_prompt.build_scene_prompt(
        memory_entry={"summary": "两人对峙", "time": "", "location": "巷子",
                      "characters": ["阿明", "阿婉"]},
        character_visual_tags={"阿明": "1boy, tall", "阿婉": "1girl"},
    )
    assert "巷子" in r.base or "两人对峙" in r.base
    assert [c["name"] for c in r.characters] == ["阿明", "阿婉"]
    assert r.characters[0]["caption"] == "1boy, tall"
    assert r.characters[1]["caption"] == "1girl"


@pytest.mark.asyncio
async def test_build_scene_prompt_character_without_tags_still_included(monkeypatch):
    from media.scene import scene_prompt

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM("garbage"))
    r = await scene_prompt.build_scene_prompt(
        memory_entry={"summary": "x", "time": "", "location": "", "characters": ["甲", "乙"]},
        character_visual_tags={"甲": "1girl, red hair"},
    )
    assert [c["name"] for c in r.characters] == ["甲", "乙"]
    assert r.characters[1]["caption"] == "1other, person"


@pytest.mark.asyncio
async def test_build_scene_prompt_rejects_llm_dropping_a_character(monkeypatch):
    from media.scene import scene_prompt

    # LLM only returned one of two present characters -> fall back
    fake = _FakeLLM('{"base": "street, day", "characters": [{"name": "甲", "caption": "1girl"}]}')
    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: fake)
    r = await scene_prompt.build_scene_prompt(
        memory_entry={"summary": "e", "time": "", "location": "街上", "characters": ["甲", "乙"]},
        character_visual_tags={"甲": "1girl, blonde", "乙": "1boy"},
    )
    assert [c["caption"] for c in r.characters] == ["1girl, blonde", "1boy"]


@pytest.mark.asyncio
async def test_build_scene_prompt_no_characters_does_not_call_llm(monkeypatch):
    from media.scene import scene_prompt

    called = {"n": 0}

    def _boom():
        called["n"] += 1
        raise AssertionError("should not build an LLM for a characterless scene")

    monkeypatch.setattr("llm.factory.get_cloud_llm", _boom)
    r = await scene_prompt.build_scene_prompt(
        memory_entry={"summary": "空场景", "time": "", "location": "空房间", "characters": []},
        character_visual_tags={},
    )
    assert called["n"] == 0
    assert r.characters == []
    assert "空房间" in r.base or "空场景" in r.base
