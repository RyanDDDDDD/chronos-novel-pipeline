"""scripts/migrate_world_power_system_core_themes.py: LLM-assisted one-off migration of legacy
world_bible power_system (free text) / core_themes (list[str]) into the new named-list shape
needed by entity_index.py/recall.py. See
docs/superpowers/specs/2026-07-24-sandbox-lore-recall-and-composer-recognition-design.md."""
import contextlib
import json

import pytest

from scripts.migrate_world_power_system_core_themes import migrate_all


class _FakeWorldRepo:
    def __init__(self, bible):
        self.bible = bible

    def get(self):
        return self.bible

    def save(self, data):
        self.bible = data


def _patch_novel(monkeypatch, nid, bible):
    repo = _FakeWorldRepo(bible)
    monkeypatch.setattr(
        "api.services.novels.list_novels", lambda: [{"id": nid, "name": nid, "active": True}],
    )
    monkeypatch.setattr("utils.paths.use_novel", lambda _nid: contextlib.nullcontext())
    monkeypatch.setattr("repositories.reset_repositories", lambda: None)
    monkeypatch.setattr("repositories.get_world_repo", lambda: repo)
    return repo


@pytest.mark.asyncio
async def test_migrates_legacy_power_system_and_core_themes(monkeypatch):
    repo = _patch_novel(monkeypatch, "nov1", {
        "power_system": "蛊虫寄生驱动力量", "core_themes": ["复仇", "成长"],
    })

    async def fake_call_llm(system, user):
        return json.dumps({
            "power_system": [{"name": "蛊虫", "desc": "寄生驱动力量"}],
            "core_themes": [{"name": "复仇", "desc": "d1"}, {"name": "成长", "desc": "d2"}],
        })

    result = await migrate_all(call_llm=fake_call_llm)
    assert "nov1" in result["migrated"]
    assert repo.bible["power_system"] == [{"name": "蛊虫", "desc": "寄生驱动力量"}]
    assert repo.bible["core_themes"] == [{"name": "复仇", "desc": "d1"}, {"name": "成长", "desc": "d2"}]


@pytest.mark.asyncio
async def test_skips_novel_already_in_new_shape(monkeypatch):
    _patch_novel(monkeypatch, "nov1", {
        "power_system": [{"name": "蛊虫", "desc": "d"}],
        "core_themes": [{"name": "复仇", "desc": "d"}],
    })

    async def fake_call_llm(system, user):
        raise AssertionError("should not be called for an already-migrated novel")

    result = await migrate_all(call_llm=fake_call_llm)
    assert result["migrated"] == {}
    assert result["failed"] == []


@pytest.mark.asyncio
async def test_llm_failure_marks_novel_failed_without_raising(monkeypatch):
    _patch_novel(monkeypatch, "nov1", {"power_system": "旧文本", "core_themes": ["x"]})

    async def fake_call_llm(system, user):
        raise RuntimeError("network down")

    result = await migrate_all(call_llm=fake_call_llm)
    assert result["failed"] == ["nov1"]
    assert result["migrated"] == {}


@pytest.mark.asyncio
async def test_malformed_llm_output_marks_novel_failed(monkeypatch):
    _patch_novel(monkeypatch, "nov1", {"power_system": "旧文本", "core_themes": ["x"]})

    async def fake_call_llm(system, user):
        return "不是 JSON"

    result = await migrate_all(call_llm=fake_call_llm)
    assert result["failed"] == ["nov1"]
