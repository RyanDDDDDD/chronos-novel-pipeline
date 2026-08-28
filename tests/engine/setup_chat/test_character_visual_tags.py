from __future__ import annotations

import pytest


def test_schedule_extract_visual_tags_registers_dedup_once_event(monkeypatch):
    from engine.setup_chat import character_visual_tags as cvt

    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")
    captured = {}

    def fake_schedule_once(name, delay_s, coro, *, dedup=False):
        captured["name"] = name
        captured["dedup"] = dedup

    import api.services.scheduler as sched
    monkeypatch.setattr(sched.SCHEDULER, "schedule_once", fake_schedule_once)

    cvt.schedule_extract_visual_tags("甲")

    assert captured["name"] == "character-visual-tags:n:甲"
    assert captured["dedup"] is True


@pytest.mark.asyncio
async def test_run_extract_visual_tags_persists_without_triggering_portrait_job(monkeypatch):
    from engine.setup_chat import character_visual_tags as cvt

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "given_name": "甲", "gender": "female"}]

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)

    extract_calls = []

    async def fake_extract_and_persist(novel_id, name, char):
        extract_calls.append((novel_id, name, char["name"]))
        return "1girl, silver hair"

    monkeypatch.setattr(
        "media.portrait.visual_tags.extract_and_persist_visual_tags", fake_extract_and_persist,
    )

    schedule_calls = []
    monkeypatch.setattr(
        "engine.setup_chat.character_portrait_generation.schedule_character_portrait_generation",
        lambda name: schedule_calls.append(name),
    )

    await cvt._run_extract_visual_tags("n", "甲")

    assert extract_calls == [("n", "甲", "甲")]
    assert schedule_calls == []  # portrait generation is manual-only now


@pytest.mark.asyncio
async def test_run_extract_visual_tags_silently_returns_when_character_deleted(monkeypatch):
    from engine.setup_chat import character_visual_tags as cvt

    class _FakeRepo:
        def list_raw(self):
            return []

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)

    extract_calls = []
    monkeypatch.setattr(
        "media.portrait.visual_tags.extract_and_persist_visual_tags",
        lambda novel_id, name, char: extract_calls.append(name),
    )
    schedule_calls = []
    monkeypatch.setattr(
        "engine.setup_chat.character_portrait_generation.schedule_character_portrait_generation",
        lambda name: schedule_calls.append(name),
    )

    await cvt._run_extract_visual_tags("n", "甲")

    assert extract_calls == []
    assert schedule_calls == []
