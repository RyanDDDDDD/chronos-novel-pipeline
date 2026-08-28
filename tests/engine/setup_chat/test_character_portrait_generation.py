from __future__ import annotations

import httpx
import pytest


class _FakeHub:
    def __init__(self):
        self.broadcasts: list[dict] = []

    async def broadcast(self, event):
        self.broadcasts.append(event)


def test_schedule_character_portrait_generation_registers_dedup_once_event(monkeypatch):
    from engine.setup_chat import character_portrait_generation as cpg

    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")
    captured = {}

    def fake_schedule_once(name, delay_s, coro, *, dedup=False):
        captured["name"] = name
        captured["dedup"] = dedup

    import api.services.scheduler as sched
    monkeypatch.setattr(sched.SCHEDULER, "schedule_once", fake_schedule_once)

    cpg.schedule_character_portrait_generation("甲")

    assert captured["name"] == "character-portrait:n:甲"
    assert captured["dedup"] is True


@pytest.mark.asyncio
async def test_run_portrait_generation_uses_cached_tags(monkeypatch):
    from engine.setup_chat import character_portrait_generation as cpg

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "given_name": "甲", "portrait_visual_tags": "1girl, silver hair"}]

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)

    fake_entry = {"id": "img-1", "provider": "image_gen", "api_key": "k", "model": "flux-1"}
    monkeypatch.setattr(cpg, "_resolve_image_gen_entry", lambda novel_id: fake_entry)
    monkeypatch.setattr(cpg, "build_portrait_prompt", lambda tags, base_model: (f"{tags}, style", "bad hands"))

    class _FakeProvider:
        def __init__(self, *, api_key: str, model: str):
            assert api_key == "k"
            assert model == "flux-1"

        async def generate(self, prompt, *, negative_prompt=""):
            assert prompt == "1girl, silver hair, style"
            assert negative_prompt == "bad hands"
            return b"PNGDATA"

    monkeypatch.setattr(
        cpg, "build_image_provider",
        lambda entry: _FakeProvider(api_key=entry.get("api_key", ""), model=entry.get("model", "")),
    )
    monkeypatch.setattr(cpg, "store_portrait", lambda name, image_bytes: "甲-123.png")

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    await cpg._run_portrait_generation("n", "甲")

    assert hub.broadcasts[0] == {
        "type": "portrait_generation_started", "novel_id": "n", "character": "甲",
    }
    assert hub.broadcasts[1] == {
        "type": "portrait_generation_done", "novel_id": "n",
        "character": "甲", "portrait_path": "甲-123.png",
    }


@pytest.mark.asyncio
async def test_run_portrait_generation_extracts_tags_when_cache_missing(monkeypatch):
    from engine.setup_chat import character_portrait_generation as cpg

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "given_name": "甲"}]  # 老角色，没有 portrait_visual_tags

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)

    fake_entry = {"id": "img-1", "provider": "image_gen", "api_key": "k", "model": "flux-1"}
    monkeypatch.setattr(cpg, "_resolve_image_gen_entry", lambda novel_id: fake_entry)
    monkeypatch.setattr(cpg, "build_portrait_prompt", lambda tags, base_model: (f"{tags}, style", ""))

    extract_calls = []

    async def fake_extract_and_persist(novel_id, name, char):
        extract_calls.append((novel_id, name))
        return "1girl, extracted"

    monkeypatch.setattr(
        "media.portrait.visual_tags.extract_and_persist_visual_tags", fake_extract_and_persist,
    )

    class _FakeProvider:
        def __init__(self, *, api_key: str, model: str):
            pass

        async def generate(self, prompt, *, negative_prompt=""):
            assert prompt == "1girl, extracted, style"
            return b"PNGDATA"

    monkeypatch.setattr(
        cpg, "build_image_provider",
        lambda entry: _FakeProvider(api_key=entry.get("api_key", ""), model=entry.get("model", "")),
    )
    monkeypatch.setattr(cpg, "store_portrait", lambda name, image_bytes: "甲-123.png")

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    await cpg._run_portrait_generation("n", "甲")

    assert extract_calls == [("n", "甲")]
    assert hub.broadcasts[-1]["portrait_path"] == "甲-123.png"


@pytest.mark.asyncio
async def test_run_portrait_generation_failure_broadcasts_error(monkeypatch):
    from engine.setup_chat import character_portrait_generation as cpg

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "given_name": "甲", "portrait_visual_tags": "1girl"}]

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)

    fake_entry = {"id": "img-1", "provider": "image_gen", "api_key": "k", "model": "flux-1"}
    monkeypatch.setattr(cpg, "_resolve_image_gen_entry", lambda novel_id: fake_entry)
    monkeypatch.setattr(cpg, "build_portrait_prompt", lambda tags, base_model: (tags, ""))

    class _FailingProvider:
        def __init__(self, *, api_key: str, model: str):
            pass

        async def generate(self, prompt, *, negative_prompt=""):
            raise RuntimeError("novita unreachable")

    monkeypatch.setattr(
        cpg, "build_image_provider",
        lambda entry: _FailingProvider(api_key=entry.get("api_key", ""), model=entry.get("model", "")),
    )

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    await cpg._run_portrait_generation("n", "甲")

    assert hub.broadcasts[1]["error"] == "novita unreachable"


@pytest.mark.asyncio
async def test_run_portrait_generation_retries_transient_failures_then_succeeds(monkeypatch):
    from engine.setup_chat import character_portrait_generation as cpg

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "given_name": "甲", "portrait_visual_tags": "1girl"}]

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)

    fake_entry = {"id": "img-1", "provider": "image_gen", "api_key": "k", "model": "flux-1"}
    monkeypatch.setattr(cpg, "_resolve_image_gen_entry", lambda novel_id: fake_entry)
    monkeypatch.setattr(cpg, "build_portrait_prompt", lambda tags, base_model: (tags, ""))

    attempts = []

    class _FlakyProvider:
        def __init__(self, *, api_key: str, model: str):
            pass

        async def generate(self, prompt, *, negative_prompt=""):
            attempts.append(1)
            if len(attempts) < 3:
                raise httpx.ConnectError("boom")
            return b"PNGDATA"

    monkeypatch.setattr(
        cpg, "build_image_provider",
        lambda entry: _FlakyProvider(api_key=entry.get("api_key", ""), model=entry.get("model", "")),
    )
    monkeypatch.setattr(cpg, "store_portrait", lambda name, image_bytes: "甲-123.png")

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    await cpg._run_portrait_generation("n", "甲")

    assert len(attempts) == 3
    assert hub.broadcasts[-1] == {
        "type": "portrait_generation_done", "novel_id": "n",
        "character": "甲", "portrait_path": "甲-123.png",
    }


@pytest.mark.asyncio
async def test_run_portrait_generation_reports_error_after_exhausting_all_retries(monkeypatch):
    from engine.setup_chat import character_portrait_generation as cpg

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "given_name": "甲", "portrait_visual_tags": "1girl"}]

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)

    fake_entry = {"id": "img-1", "provider": "image_gen", "api_key": "k", "model": "flux-1"}
    monkeypatch.setattr(cpg, "_resolve_image_gen_entry", lambda novel_id: fake_entry)
    monkeypatch.setattr(cpg, "build_portrait_prompt", lambda tags, base_model: (tags, ""))

    attempts = []

    class _AlwaysFailingProvider:
        def __init__(self, *, api_key: str, model: str):
            pass

        async def generate(self, prompt, *, negative_prompt=""):
            attempts.append(1)
            raise httpx.ConnectError("down")

    monkeypatch.setattr(
        cpg, "build_image_provider",
        lambda entry: _AlwaysFailingProvider(api_key=entry.get("api_key", ""), model=entry.get("model", "")),
    )

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    await cpg._run_portrait_generation("n", "甲")

    assert len(attempts) >= 1
    assert hub.broadcasts[-1]["error"]


@pytest.mark.asyncio
async def test_run_portrait_generation_silently_returns_when_character_deleted(monkeypatch):
    from engine.setup_chat import character_portrait_generation as cpg

    class _FakeRepo:
        def list_raw(self):
            return []

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    await cpg._run_portrait_generation("n", "甲")

    assert hub.broadcasts == []


def test_resolve_image_gen_entry_returns_none_when_none_configured(monkeypatch):
    from engine.setup_chat import character_portrait_generation as cpg

    monkeypatch.setattr("domain.model_catalog.load_custom_models", lambda: [])
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {}},
    )
    assert cpg._resolve_image_gen_entry("n") is None


def test_resolve_image_gen_entry_defaults_to_sole_entry(monkeypatch):
    from engine.setup_chat import character_portrait_generation as cpg

    entry = {"id": "img-1", "provider": "image_gen", "api_key": "k", "model": "flux-1"}
    monkeypatch.setattr("domain.model_catalog.load_custom_models", lambda: [entry])
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {}},
    )
    assert cpg._resolve_image_gen_entry("n") == entry


def test_resolve_image_gen_entry_returns_none_when_multiple_and_unset(monkeypatch):
    from engine.setup_chat import character_portrait_generation as cpg

    entries = [
        {"id": "img-1", "provider": "image_gen", "api_key": "k1", "model": "flux-1"},
        {"id": "img-2", "provider": "image_gen", "api_key": "k2", "model": "flux-2"},
    ]
    monkeypatch.setattr("domain.model_catalog.load_custom_models", lambda: entries)
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {}},
    )
    assert cpg._resolve_image_gen_entry("n") is None


def test_resolve_image_gen_entry_uses_explicit_model_ref(monkeypatch):
    from engine.setup_chat import character_portrait_generation as cpg

    entries = [
        {"id": "img-1", "provider": "image_gen", "api_key": "k1", "model": "flux-1"},
        {"id": "img-2", "provider": "image_gen", "api_key": "k2", "model": "flux-2"},
    ]
    monkeypatch.setattr("domain.model_catalog.load_custom_models", lambda: entries)
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {"character_portrait": {"model_ref": "img-2"}}},
    )
    assert cpg._resolve_image_gen_entry("n")["id"] == "img-2"


@pytest.mark.asyncio
async def test_run_portrait_generation_fails_clearly_when_no_model_configured(monkeypatch):
    from engine.setup_chat import character_portrait_generation as cpg

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "given_name": "甲"}]

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)
    monkeypatch.setattr(cpg, "_resolve_image_gen_entry", lambda novel_id: None)

    hub = _FakeHub()
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    await cpg._run_portrait_generation("n", "甲")

    assert hub.broadcasts[-1]["error"] == "未配置生图模型，请到「流水线→对话」页为「立绘生成」节点选择模型"


@pytest.mark.asyncio
async def test_run_portrait_generation_passes_entry_base_model_to_prompt_builder(monkeypatch):
    from engine.setup_chat import character_portrait_generation as cpg

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "given_name": "甲", "portrait_visual_tags": "1girl"}]

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)

    fake_entry = {"id": "img-1", "provider": "image_gen", "api_key": "k", "model": "pony-v6", "base_model": "Pony"}
    monkeypatch.setattr(cpg, "_resolve_image_gen_entry", lambda novel_id: fake_entry)

    captured = {}

    def fake_build_portrait_prompt(tags, base_model):
        captured["tags"] = tags
        captured["base_model"] = base_model
        return "prompt", "negative"

    monkeypatch.setattr(cpg, "build_portrait_prompt", fake_build_portrait_prompt)

    class _FakeProvider:
        def __init__(self, *, api_key: str, model: str):
            pass

        async def generate(self, prompt, *, negative_prompt=""):
            return b"PNGDATA"

    monkeypatch.setattr(
        cpg, "build_image_provider",
        lambda entry: _FakeProvider(api_key=entry.get("api_key", ""), model=entry.get("model", "")),
    )
    monkeypatch.setattr(cpg, "store_portrait", lambda name, image_bytes: "甲-123.png")

    class _FakeHub:
        async def broadcast(self, event):
            pass

    monkeypatch.setattr("api.routes._hub_instance", lambda: _FakeHub())

    await cpg._run_portrait_generation("n", "甲")

    assert captured == {"tags": "1girl", "base_model": "Pony"}


@pytest.mark.asyncio
async def test_run_portrait_generation_dispatches_novelai_service(monkeypatch):
    from engine.setup_chat import character_portrait_generation as cpg

    class _FakeRepo:
        def list_raw(self):
            return [{"name": "甲", "given_name": "甲", "portrait_visual_tags": "1girl"}]

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)

    entry = {"id": "img-1", "provider": "image_gen", "service": "novelai",
             "api_key": "tok", "model": "nai-diffusion-4-5-full"}
    monkeypatch.setattr(cpg, "_resolve_image_gen_entry", lambda novel_id: entry)
    monkeypatch.setattr(cpg, "build_portrait_prompt", lambda tags, base_model: (tags, ""))

    seen = {}

    def fake_build_image_provider(e):
        seen["service"] = e.get("service")

        class _P:
            async def generate(self, prompt, *, negative_prompt=""):
                return b"PNGDATA"

        return _P()

    monkeypatch.setattr(cpg, "build_image_provider", fake_build_image_provider)
    monkeypatch.setattr(cpg, "store_portrait", lambda name, image_bytes: "甲-1.png")

    class _Hub:
        async def broadcast(self, event):
            pass

    monkeypatch.setattr("api.routes._hub_instance", lambda: _Hub())

    await cpg._run_portrait_generation("n", "甲")
    assert seen["service"] == "novelai"
