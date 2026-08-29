from __future__ import annotations

import contextlib

import pytest


class _Hub:
    def __init__(self):
        self.events: list[dict] = []

    async def broadcast(self, e):
        self.events.append(e)


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """A hub + a fake sandbox turn + fake lore + fake provider + real store."""
    nid = "n"
    (tmp_path / nid / "chapters").mkdir(parents=True)
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", nid)
    monkeypatch.setattr("utils.paths.use_novel", lambda _id: contextlib.nullcontext())

    hub = _Hub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    turn = {
        "id": "r1", "prose": "阿明和阿婉在酒馆里对峙。",
        "character_states": {"阿明": {}, "阿婉": {}},
        "rolling_summary_after": "两人摊牌",
        "event_log_entries": [{"summary": "阿明向阿婉摊牌", "time": "深夜", "location": "酒馆",
                               "characters": ["阿明", "阿婉"]}],
    }

    async def _fake_load_turn(novel_id, chapter, branch_id, round_id):
        return turn
    monkeypatch.setattr("media.scene.generation._load_sandbox_turn", _fake_load_turn)
    monkeypatch.setattr("media.scene.generation._character_visual_tags",
                        lambda names: {"阿明": "1boy, black hair", "阿婉": "1girl, silver hair"})
    monkeypatch.setattr("media.scene.generation._character_portrait_bytes",
                        lambda names: {"阿明": b"PORTRAIT_A"})  # 阿婉 has no portrait

    from media.scene import scene_prompt as sp

    async def fake_build(*, memory_entry, character_visual_tags):
        return sp.ScenePromptResult(
            base="tavern, night, 2people",
            characters=[{"name": "阿明", "caption": "1boy, black hair, arms crossed"},
                        {"name": "阿婉", "caption": "1girl, silver hair, holding teacup"}],
        )
    monkeypatch.setattr("media.scene.generation.build_scene_prompt", fake_build)
    monkeypatch.setattr("media.scene.generation.build_scene_positive",
                        lambda base: (f"{base}, anime style", "worst quality"))

    calls: dict = {}

    class _FakeProvider:
        async def generate(self, prompt, *, negative_prompt="", char_captions=None,
                           character_references=None, reference_strength=0.7, reference_fidelity=1.0):
            calls["prompt"] = prompt
            calls["char_captions"] = char_captions
            calls["refs"] = character_references
            return b"SCENE_PNG"
    monkeypatch.setattr("media.scene.generation.build_image_provider", lambda entry: _FakeProvider())
    return hub, calls


@pytest.mark.asyncio
async def test_generate_scene_image_happy_path(wired, monkeypatch):
    hub, calls = wired
    monkeypatch.setattr(
        "media.scene.generation._resolve_scene_image_entry",
        lambda: {"id": "m1", "provider": "image_gen", "service": "novelai",
                 "api_key": "k", "model": "nai-diffusion-4-5-full"},
    )
    from media.scene import generation, store

    await generation.generate_sandbox_scene_image("n", 3, "b1", "r1")

    assert calls["prompt"] == "tavern, night, 2people, anime style"
    assert [c["char_caption"] for c in calls["char_captions"]] == \
        ["1boy, black hair, arms crossed", "1girl, silver hair, holding teacup"]
    assert calls["refs"] == [b"PORTRAIT_A"]           # only 阿明 has a portrait
    assert store.sandbox_scene_image_filename(3, "b1", "r1") is not None
    done = [e for e in hub.events if e["type"] == "sandbox_scene_image_done"][0]
    assert done["round_id"] == "r1" and "error" not in done and "filename" in done


@pytest.mark.asyncio
async def test_generate_scene_image_no_model_configured(wired, monkeypatch):
    hub, _ = wired
    monkeypatch.setattr("media.scene.generation._resolve_scene_image_entry", lambda: None)
    from media.scene import generation

    await generation.generate_sandbox_scene_image("n", 3, "b1", "r1")
    done = [e for e in hub.events if e["type"] == "sandbox_scene_image_done"][0]
    assert "未配置" in done["error"]


@pytest.mark.asyncio
async def test_generate_scene_image_round_not_found(monkeypatch, tmp_path):
    (tmp_path / "n" / "chapters").mkdir(parents=True)
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "n")
    monkeypatch.setattr("utils.paths.use_novel", lambda _id: contextlib.nullcontext())
    hub = _Hub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    async def _none(*a, **k):
        return None
    monkeypatch.setattr("media.scene.generation._load_sandbox_turn", _none)
    from media.scene import generation

    await generation.generate_sandbox_scene_image("n", 3, "b1", "nope")
    done = [e for e in hub.events if e["type"] == "sandbox_scene_image_done"][0]
    assert "error" in done


def test_resolve_scene_image_entry_rejects_non_novelai(monkeypatch):
    from media.scene import generation

    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"sandbox_llm_params": {"scene_image": {"model_ref": "m1"}}},
    )
    monkeypatch.setattr(
        "domain.model_catalog.load_custom_models",
        lambda: [{"id": "m1", "provider": "image_gen", "service": "novita"}],
    )
    assert generation._resolve_scene_image_entry() is None
