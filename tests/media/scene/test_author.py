from __future__ import annotations

import json

import pytest


class _Hub:
    def __init__(self):
        self.events: list[dict] = []

    async def broadcast(self, e):
        self.events.append(e)


def _write_journal(tmp_path, chapter, events):
    from utils.paths import author_loop_journal_path
    path = author_loop_journal_path(chapter)
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


@pytest.fixture
def novel(monkeypatch, tmp_path):
    nid = "n"
    (tmp_path / nid / "chapters").mkdir(parents=True)
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", nid)
    # NB: do NOT patch utils.paths.use_novel here -- the real context manager works fine in
    # tests (it just sets/resets a ContextVar), and patching it globally leaks into any module
    # that binds `use_novel` at import time during this test (e.g. api.services.message_hub on
    # first import), breaking unrelated later tests. See the sibling fix in test_generation.py.
    hub = _Hub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)
    return nid, tmp_path, hub


def test_stage_memory_entry_from_event_log(novel, monkeypatch):
    _nid, tmp_path, _hub = novel
    _write_journal(tmp_path, 6, [
        {"type": "author_loop_event_log", "index": 2, "entries": [
            {"summary": "甲推开书房门", "time": "深夜", "location": "书房", "characters": ["甲", "乙"]},
        ]},
    ])
    from media.scene import author
    mem = author._stage_memory_entry(6, 2)
    assert mem == {"summary": "甲推开书房门", "time": "深夜", "location": "书房",
                   "characters": ["甲", "乙"]}


def test_stage_memory_entry_falls_back_to_state_when_no_events(novel):
    _nid, tmp_path, _hub = novel
    _write_journal(tmp_path, 6, [
        {"type": "author_loop_state", "index": 2, "characters": [
            {"name": "甲"}, {"name": "乙"},
        ]},
    ])
    from media.scene import author
    mem = author._stage_memory_entry(6, 2)
    assert mem["characters"] == ["甲", "乙"] and mem["summary"] == ""


def test_stage_memory_entry_none_when_stage_missing(novel):
    _nid, tmp_path, _hub = novel
    _write_journal(tmp_path, 6, [{"type": "author_loop_state", "index": 0, "characters": []}])
    from media.scene import author
    assert author._stage_memory_entry(6, 5) is None


def test_stage_memory_entry_returns_entry_when_stage_has_no_characters(novel):
    """A finalized-but-empty-cast stage is a different failure than a missing stage -- the
    caller has to be able to tell them apart to report the right error."""
    _nid, tmp_path, _hub = novel
    _write_journal(tmp_path, 6, [{"type": "author_loop_state", "index": 2, "characters": []}])
    from media.scene import author
    assert author._stage_memory_entry(6, 2) == {
        "summary": "", "time": "", "location": "", "characters": [],
    }


@pytest.mark.asyncio
async def test_generate_happy_path(novel, monkeypatch):
    _nid, tmp_path, hub = novel
    _write_journal(tmp_path, 6, [
        {"type": "author_loop_event_log", "index": 2, "entries": [
            {"summary": "甲乙对峙", "time": "深夜", "location": "书房", "characters": ["甲", "乙"]},
        ]},
    ])
    monkeypatch.setattr("media.scene.author._resolve_scene_image_entry",
                        lambda config_key: {"id": "m1", "service": "novelai",
                                            "api_key": "k", "model": "nai-diffusion-4-5-full"})
    monkeypatch.setattr("media.scene.author._character_visual_tags",
                        lambda names: {"甲": "1boy, black hair", "乙": "1girl, silver hair"})
    monkeypatch.setattr("media.scene.author._character_portrait_bytes",
                        lambda names: {"甲": b"PORTRAIT_A"})  # 乙 无立绘

    from media.scene import scene_prompt as sp

    async def fake_build(*, memory_entry, character_visual_tags):
        return sp.ScenePromptResult(
            base="study, night, 2people",
            characters=[{"name": "甲", "caption": "1boy, black hair, standing"},
                        {"name": "乙", "caption": "1girl, silver hair, seated"}],
        )
    monkeypatch.setattr("media.scene.author.build_scene_prompt", fake_build)
    monkeypatch.setattr("media.scene.author.build_scene_positive",
                        lambda base: (f"{base}, anime style", "worst quality"))

    calls: dict = {}

    class _FakeProvider:
        async def generate(self, prompt, *, negative_prompt="", char_captions=None,
                           character_references=None):
            calls.update(prompt=prompt, char_captions=char_captions, refs=character_references)
            return b"SCENE_PNG"
    monkeypatch.setattr("media.scene.author.build_image_provider", lambda entry: _FakeProvider())

    from media.scene import author, author_store
    await author.generate_author_stage_scene_image("n", 6, 2)

    assert calls["prompt"] == "study, night, 2people, anime style"
    assert [c["char_caption"] for c in calls["char_captions"]] == \
        ["1boy, black hair, standing", "1girl, silver hair, seated"]
    assert calls["refs"] == [b"PORTRAIT_A"]
    assert author_store.author_stage_scene_image_filename(6, 2) is not None
    types = [e["type"] for e in hub.events]
    assert types == ["author_scene_image_started", "author_scene_image_done"]
    assert hub.events[-1]["index"] == 2 and "filename" in hub.events[-1] and "error" not in hub.events[-1]


@pytest.mark.asyncio
async def test_generate_no_model_configured(novel, monkeypatch):
    _nid, tmp_path, hub = novel
    _write_journal(tmp_path, 6, [
        {"type": "author_loop_event_log", "index": 2, "entries": [
            {"summary": "x", "time": "", "location": "", "characters": ["甲"]},
        ]},
    ])
    monkeypatch.setattr("media.scene.author._resolve_scene_image_entry", lambda config_key: None)
    from media.scene import author
    await author.generate_author_stage_scene_image("n", 6, 2)
    done = [e for e in hub.events if e["type"] == "author_scene_image_done"][0]
    assert "未配置" in done["error"]


@pytest.mark.asyncio
async def test_generate_caps_precise_references_at_the_shared_maximum(novel, monkeypatch):
    _nid, tmp_path, hub = novel
    names = [f"角色{i}" for i in range(9)]
    _write_journal(tmp_path, 6, [
        {"type": "author_loop_event_log", "index": 2, "entries": [
            {"summary": "群像", "time": "白天", "location": "广场", "characters": names},
        ]},
    ])
    monkeypatch.setattr("media.scene.author._resolve_scene_image_entry",
                        lambda config_key: {"id": "m1", "service": "novelai",
                                            "api_key": "k", "model": "nai-diffusion-4-5-full"})
    monkeypatch.setattr("media.scene.author._character_visual_tags", lambda ns: {})
    monkeypatch.setattr("media.scene.author._character_portrait_bytes",
                        lambda ns: {n: n.encode() for n in ns})

    from media.scene import scene_prompt as sp

    async def fake_build(*, memory_entry, character_visual_tags):
        return sp.ScenePromptResult(base="plaza", characters=[])
    monkeypatch.setattr("media.scene.author.build_scene_prompt", fake_build)
    monkeypatch.setattr("media.scene.author.build_scene_positive", lambda base: (base, ""))

    calls: dict = {}

    class _FakeProvider:
        async def generate(self, prompt, *, negative_prompt="", char_captions=None,
                           character_references=None):
            calls["refs"] = character_references
            return b"SCENE_PNG"
    monkeypatch.setattr("media.scene.author.build_image_provider", lambda entry: _FakeProvider())

    from media.scene import author
    from media.scene._shared import _MAX_REFERENCES
    await author.generate_author_stage_scene_image("n", 6, 2)

    assert _MAX_REFERENCES == 6
    assert calls["refs"] == [n.encode() for n in names[:_MAX_REFERENCES]]
    assert "error" not in hub.events[-1]


@pytest.mark.asyncio
async def test_generate_stage_not_found(novel, monkeypatch):
    _nid, tmp_path, hub = novel
    _write_journal(tmp_path, 6, [])
    from media.scene import author
    await author.generate_author_stage_scene_image("n", 6, 2)
    done = [e for e in hub.events if e["type"] == "author_scene_image_done"][0]
    assert "重置" in done["error"]


@pytest.mark.asyncio
async def test_generate_no_present_characters_reports_its_own_error(novel, monkeypatch):
    """A stage that finalized with nobody on screen must not be reported as "已重置" -- that
    sends the user hunting for a reset that never happened."""
    _nid, tmp_path, hub = novel
    _write_journal(tmp_path, 6, [{"type": "author_loop_state", "index": 2, "characters": []}])
    from media.scene import author
    await author.generate_author_stage_scene_image("n", 6, 2)
    done = [e for e in hub.events if e["type"] == "author_scene_image_done"][0]
    assert done["error"] == "该 stage 无在场角色，无法生图"
