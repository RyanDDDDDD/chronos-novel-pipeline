import json

import pytest
from engine.setup_chat.tools import construct_world, load_skill, read_setup_summary, refine_world
from pydantic import ValidationError

from repo_test_helpers import get_world, init_store, seed_lore, seed_world


def test_read_world_returns_summary():
    seed_world({"background": "X", "tone": "冷峻"})
    out = read_setup_summary.invoke({"target": "world"})
    assert "世界背景" in out and "X" in out
    assert "{" not in out


def test_read_missing_returns_hint():
    init_store()
    out = read_setup_summary.invoke({"target": "world"})
    assert "尚未构建" in out


def test_read_bad_target():
    out = read_setup_summary.invoke({"target": "bogus"})
    assert "未知" in out or "world" in out


def test_read_archetypes_target_rejected():
    out = read_setup_summary.invoke({"target": "archetypes"})
    assert "未知" in out


def test_read_cast_summary():
    seed_lore([{"given_name": "甲", "role": "lead"}])
    out = read_setup_summary.invoke({"target": "cast"})
    assert "甲" in out and "lead" in out
    assert "role=" not in out
    assert "{" not in out


def _world_args(**overrides):
    item = {"name": "n", "desc": "d"}
    base = {
        "tone": "T", "background": "B",
        "factions": [item], "geography": [item], "races": [item],
        "power_system": [item], "core_themes": [item],
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_refine_world_ok():
    seed_world({"logline": "orig"})

    args = _world_args(tone="黑暗")
    out = await refine_world.ainvoke(args)
    assert "已更新世界观" in out
    assert "基调" in out
    saved = get_world()
    assert saved is not None
    assert saved["tone"] == "黑暗"


@pytest.mark.asyncio
async def test_refine_world_missing_bible():
    init_store()
    out = await refine_world.ainvoke(_world_args())
    assert "尚未构建" in out


@pytest.mark.asyncio
async def test_construct_world_writes():
    init_store()
    out = await construct_world.ainvoke(_world_args(tone="冷峻"))
    assert "已写入世界观" in out
    saved = get_world()
    assert saved is not None
    assert saved["tone"] == "冷峻"


@pytest.mark.asyncio
async def test_construct_world_invalid_rejected():
    init_store()
    args = _world_args(background="")
    with pytest.raises(ValidationError):
        await construct_world.ainvoke(args)


@pytest.mark.asyncio
async def test_construct_world_invalidates_entity_vocab_cache(monkeypatch):
    """construct_world always writes the whole bible (factions/geography/races/power_system
    included every call) -- the process-level entity vocab cache must be invalidated so recall
    picks up any new/renamed named entries on the very next sandbox turn."""
    init_store()
    calls = []
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.invalidate_entity_vocab_cache",
        lambda: calls.append(1),
    )
    await construct_world.ainvoke(_world_args())
    assert calls == [1]


@pytest.mark.asyncio
async def test_refine_world_invalidates_entity_vocab_cache(monkeypatch):
    seed_world({"logline": "orig"})
    calls = []
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.invalidate_entity_vocab_cache",
        lambda: calls.append(1),
    )
    await refine_world.ainvoke(_world_args())
    assert calls == [1]


def test_load_skill_tool_hit_returns_body():
    out = load_skill.invoke({"name": "world-interview"})
    assert "落字成档" in out
    assert "不深挖支线" in out


def test_load_skill_tool_miss_lists_available():
    out = load_skill.invoke({"name": "no-such-skill"})
    assert "未找到技能" in out
    assert "world-interview" in out  #List available skill names


def test_present_choices_returns_confirmation():
    from engine.setup_chat.tools import present_choices
    out = present_choices.invoke({"question": "选哪个？", "options": ["A", "B"], "recommended": "A"})
    assert "2" in out and "本轮" in out


def test_present_choices_manual_mode_waits(monkeypatch):
    from engine.setup_chat import mode
    monkeypatch.setattr(mode, "_AUTO", False)
    from engine.setup_chat.tools import present_choices
    out = present_choices.invoke({"question": "选哪个？", "options": ["A", "B"], "recommended": "A"})
    assert "本轮" in out and "等待" in out


def test_present_choices_auto_mode_picks_recommended_and_continues(monkeypatch):
    from engine.setup_chat import mode
    monkeypatch.setattr(mode, "_AUTO", True)
    from engine.setup_chat.tools import present_choices
    out = present_choices.invoke({"question": "选哪个？", "options": ["A", "B"], "recommended": "B"})
    assert "B" in out
    assert "本轮" not in out
    assert "继续" in out


def test_present_choices_auto_mode_falls_back_when_recommended_not_in_options(monkeypatch):
    from engine.setup_chat import mode
    monkeypatch.setattr(mode, "_AUTO", True)
    from engine.setup_chat.tools import present_choices
    out = present_choices.invoke({"question": "选哪个？", "options": ["A", "B"], "recommended": "C"})
    assert "A" in out  # falls back to options[0]


def test_strip_manuscript_metadata_keeps_header_and_process_only():
    from engine.setup_chat.tools import _strip_manuscript_metadata
    block = (
        "### 【阶段一：开场】\n\n"
        "- **【地点场景】**：客厅\n\n"
        "- **【摘要】**：她推开了门\n\n"
        "- **【角色状态】**：\n  - **甲**：\n    - 着装：便装\n    - 生理：（未设定）\n\n"
        "- **【过程描述】**：她推开门走了进去。"
    )
    out = _strip_manuscript_metadata(block)
    assert "### 【阶段一：开场】" in out
    assert "她推开门走了进去。" in out
    assert "地点场景" not in out
    assert "摘要" not in out
    assert "角色状态" not in out
    assert "着装" not in out


def test_read_author_manuscript_tool_hides_metadata(monkeypatch, tmp_path):
    import engine.setup_chat.tools as t
    from api.services import pipeline_catalog as pc

    ch_dir = tmp_path / "chapters" / "第1章"
    ch_dir.mkdir(parents=True)
    md_path = ch_dir / "第1章_主笔.md"
    md_path.write_text(
        "### 【阶段一：开场】\n\n"
        "- **【地点场景】**：客厅\n\n"
        "- **【角色状态】**：\n  - **甲**：\n    - 着装：便装\n\n"
        "- **【过程描述】**：她推开门走了进去。",
        encoding="utf-8",
    )
    monkeypatch.setattr(pc, "chapters_dir", lambda: tmp_path / "chapters")

    out = t.read_author_manuscript.invoke({"chapter": 1, "stage_num": 1})
    assert "她推开门走了进去。" in out
    assert "地点场景" not in out
    assert "角色状态" not in out
    assert "着装" not in out


def _write_novel_meta(novels_root, nid: str, name: str) -> None:
    novel_dir = novels_root / nid
    novel_dir.mkdir(parents=True, exist_ok=True)
    (novel_dir / "novel.json").write_text(
        json.dumps({"name": name}, ensure_ascii=False), encoding="utf-8",
    )


def test_rename_novel_title_rejects_blank(monkeypatch):
    from engine.setup_chat.tools import rename_novel_title

    called = {"hit": False}

    def _fake_rename(nid: str, name: str) -> None:
        called["hit"] = True

    monkeypatch.setattr("api.services.novels.rename_novel", _fake_rename)
    result = rename_novel_title.invoke({"new_title": "   "})
    assert result == "标题不能为空，未修改。"
    assert called["hit"] is False


def test_rename_novel_title_updates_novel_json(tmp_path, monkeypatch):
    from api.services.novels import get_novel_name
    from engine.setup_chat.tools import rename_novel_title
    from tests.conftest import seed_registry_novel

    novels_root = tmp_path / "novels"
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(novels_root))
    seed_registry_novel(novels_root, "novel-1", "旧标题")
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "novel-1")

    result = rename_novel_title.invoke({"new_title": "星海彼岸的旅人"})

    assert result == "已将小说标题改为「星海彼岸的旅人」。"
    assert get_novel_name("novel-1") == "星海彼岸的旅人"


@pytest.mark.asyncio
async def test_auto_build_setup_logs_each_internal_llm_call(monkeypatch):
    """auto_build_setup's internal call_llm previously called llm.ainvoke() with zero
    PromptLogger wiring -- completely undiagnosable via prompt_parse.py. Every call must now
    be logged under the auto_build_setup agent label with a per-call incrementing step."""
    from engine.setup_chat import auto_construct as ac_mod

    logged_calls: list[dict] = []

    class _FakePromptLogger:
        def __init__(self, chapter):
            self.chapter = chapter
            self.closed = False

        def log_llm_call(self, **kwargs):
            logged_calls.append(kwargs)

        def close(self):
            self.closed = True

    monkeypatch.setattr("llm.prompt_logger.PromptLogger", _FakePromptLogger)

    class _FakeResp:
        content = "ok"
        usage_metadata = {"input_tokens": 10, "output_tokens": 5}

    class _FakeLLM:
        model = "fake-model"

        async def ainvoke(self, _messages):
            return _FakeResp()

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {
            "auto_build_character_count": 1, "auto_build_chapter_count": 1,
            "import_llm_params": {},
        },
    )

    async def fake_run_auto_build(brief, character_count, chapter_count, call_llm):
        assert character_count == 1 and chapter_count == 1
        # Exercises the real call_llm closure the way build_world + one character draft would.
        await call_llm("sys1", "user1")
        await call_llm("sys2", "user2")
        return "done"

    monkeypatch.setattr(ac_mod, "run_auto_build", fake_run_auto_build)

    from engine.setup_chat.tools import auto_build_setup
    result = await auto_build_setup.ainvoke({"brief": "brief"})

    assert result == "done"
    assert len(logged_calls) == 2
    assert [c["step"] for c in logged_calls] == [1, 2]
    assert all(c["agent"] == "auto_build_setup" for c in logged_calls)
    assert logged_calls[0]["tokens_in"] == 10
    assert logged_calls[0]["tokens_out"] == 5
    assert logged_calls[0]["system"] == "sys1" and logged_calls[0]["user"] == "user1"


@pytest.mark.asyncio
async def test_auto_build_setup_applies_configured_node_model_ref(monkeypatch):
    """auto_build_setup previously called get_cloud_llm() with no per-node override at all --
    a "对话" tab node config for it had nothing to attach to. It must now resolve the
    "auto_build_setup" node id (not some other node's id) through the same import_llm_params
    sidecar image_recognition/text_recognition/chat_identity/review already use."""
    from engine.setup_chat import auto_construct as ac_mod

    class _FakeResp:
        content = "ok"
        usage_metadata = {"input_tokens": 1, "output_tokens": 1}

    class _SwappedLLM:
        model = "swapped-model"

        async def ainvoke(self, _messages):
            return _FakeResp()

    seen_agents: list[str] = []

    def fake_resolve_node_base_llm(_llm, agent, _params):
        seen_agents.append(agent)
        return _SwappedLLM()

    monkeypatch.setattr("llm.prompt_logger.PromptLogger", lambda chapter: type(
        "P", (), {"log_llm_call": lambda self, **kw: None, "close": lambda self: None},
    )())
    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: object())
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.resolve_node_base_llm", fake_resolve_node_base_llm,
    )
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {
            "auto_build_character_count": 1, "auto_build_chapter_count": 1,
            "import_llm_params": {"auto_build_setup": {"model_ref": "custom-1"}},
        },
    )

    async def fake_run_auto_build(brief, character_count, chapter_count, call_llm):
        await call_llm("sys", "user")
        return "done"

    monkeypatch.setattr(ac_mod, "run_auto_build", fake_run_auto_build)

    from engine.setup_chat.tools import auto_build_setup
    result = await auto_build_setup.ainvoke({"brief": "brief"})

    assert result == "done"
    assert seen_agents == ["auto_build_setup"]


@pytest.mark.asyncio
async def test_add_character_core_schedules_visual_tags_extraction(monkeypatch, tmp_path):
    from engine.setup_chat import tools

    class _FakeRepo:
        def list_raw(self):
            return []

        def save_all(self, roster):
            pass

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)
    monkeypatch.setattr("engine.setup_chat.tools.validate_character_edit", lambda char, roster, **_kw: [])
    monkeypatch.setattr(
        "engine.setup_chat.character_background_review.schedule_character_quality_review",
        lambda name, **_kwargs: None,
    )
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"auto_build_character_count": 5},
    )

    schedule_calls = []
    monkeypatch.setattr(
        "engine.setup_chat.character_visual_tags.schedule_extract_visual_tags",
        lambda name: schedule_calls.append(name),
    )

    ok, _msg, _char = await tools._add_character_core(
        given_name="甲", role="submissive", gender="female",
        causal_anchors={}, physique={}, clothing_color_palette=[],
        clothing_materials=[], clothing_signature_outfit="", clothing_accessories=[],
        sliders={}, personality="", identity_background="",
    )

    assert ok is True
    assert schedule_calls == ["甲"]


@pytest.mark.asyncio
async def test_edit_character_core_reextracts_when_physique_changes(monkeypatch):
    from engine.setup_chat import tools

    existing = {
        "name": "甲", "given_name": "甲", "role": "submissive", "gender": "female",
        "causal_anchors": {}, "physique": {"体型": "娇小"},
        "clothing_dna": {"color_palette": [], "materials_preference": [],
                          "signature_outfit": "", "accessories": []},
        "sliders": {}, "personality": "", "identity_background": "",
        "portrait_visual_tags": "1girl, old tags",
    }
    saved = {}

    class _FakeRepo:
        def list_raw(self):
            return [dict(existing)]

        def save_all(self, roster):
            saved["roster"] = roster

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)
    monkeypatch.setattr("engine.setup_chat.tools.validate_character_edit", lambda char, roster, **_kw: [])
    monkeypatch.setattr(
        "engine.setup_chat.character_background_review.cancel_active_character_fix",
        lambda novel_id, name: _async_none(),
    )
    monkeypatch.setattr(
        "engine.setup_chat.character_background_review.schedule_character_quality_review",
        lambda name, **_kwargs: None,
    )
    monkeypatch.setattr(
        "engine.archive.archive_view.delete_character_archives",
        lambda name: {"removed_stages": 0, "deleted_chapters": []},
    )
    monkeypatch.setattr(
        "engine.setup_chat.timeline_auto.schedule_timeline_cascade",
        lambda chapter, names, **_kwargs: None,
    )

    schedule_calls = []
    monkeypatch.setattr(
        "engine.setup_chat.character_visual_tags.schedule_extract_visual_tags",
        lambda name: schedule_calls.append(name),
    )

    ok, _msg, char = await tools._edit_character_core(
        name="甲", given_name="甲", role="submissive", gender="female",
        causal_anchors={}, physique={"体型": "高挑"},  # 变了
        clothing_color_palette=[], clothing_materials=[],
        clothing_signature_outfit="", clothing_accessories=[],
        sliders={}, personality="", identity_background="",
    )

    assert ok is True
    assert schedule_calls == ["甲"]
    assert "portrait_visual_tags" not in saved["roster"][0]


@pytest.mark.asyncio
async def test_edit_character_core_keeps_cache_when_appearance_unchanged(monkeypatch):
    from engine.setup_chat import tools

    existing = {
        "name": "甲", "given_name": "甲", "role": "submissive", "gender": "female",
        "causal_anchors": {}, "physique": {"体型": "娇小"},
        "clothing_dna": {"color_palette": [], "materials_preference": [],
                          "signature_outfit": "", "accessories": []},
        "sliders": {}, "personality": "旧性格", "identity_background": "",
        "portrait_visual_tags": "1girl, old tags",
    }
    saved = {}

    class _FakeRepo:
        def list_raw(self):
            return [dict(existing)]

        def save_all(self, roster):
            saved["roster"] = roster

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)
    monkeypatch.setattr("engine.setup_chat.tools.validate_character_edit", lambda char, roster, **_kw: [])
    monkeypatch.setattr(
        "engine.setup_chat.character_background_review.cancel_active_character_fix",
        lambda novel_id, name: _async_none(),
    )
    monkeypatch.setattr(
        "engine.setup_chat.character_background_review.schedule_character_quality_review",
        lambda name, **_kwargs: None,
    )
    monkeypatch.setattr(
        "engine.archive.archive_view.delete_character_archives",
        lambda name: {"removed_stages": 0, "deleted_chapters": []},
    )
    monkeypatch.setattr(
        "engine.setup_chat.timeline_auto.schedule_timeline_cascade",
        lambda chapter, names, **_kwargs: None,
    )

    schedule_calls = []
    monkeypatch.setattr(
        "engine.setup_chat.character_visual_tags.schedule_extract_visual_tags",
        lambda name: schedule_calls.append(name),
    )

    ok, _msg, char = await tools._edit_character_core(
        name="甲", given_name="甲", role="submissive", gender="female",
        causal_anchors={}, physique={"体型": "娇小"},  # 没变
        clothing_color_palette=[], clothing_materials=[],
        clothing_signature_outfit="", clothing_accessories=[],
        sliders={}, personality="新性格",  # 只改性格
        identity_background="",
    )

    assert ok is True
    assert schedule_calls == []
    assert saved["roster"][0]["portrait_visual_tags"] == "1girl, old tags"


@pytest.mark.asyncio
async def test_edit_character_core_applies_manual_visual_tags_override(monkeypatch):
    """Cast detail panel manual edit: an explicit portrait_visual_tags value is saved
    as-is and does not trigger re-extraction when appearance fields didn't change."""
    from engine.setup_chat import tools

    existing = {
        "name": "甲", "given_name": "甲", "role": "submissive", "gender": "female",
        "causal_anchors": {}, "physique": {"体型": "娇小"},
        "clothing_dna": {"color_palette": [], "materials_preference": [],
                          "signature_outfit": "", "accessories": []},
        "sliders": {}, "personality": "", "identity_background": "",
        "portrait_visual_tags": "1girl, old tags",
    }
    saved = {}

    class _FakeRepo:
        def list_raw(self):
            return [dict(existing)]

        def save_all(self, roster):
            saved["roster"] = roster

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)
    monkeypatch.setattr("engine.setup_chat.tools.validate_character_edit", lambda char, roster, **_kw: [])
    monkeypatch.setattr(
        "engine.setup_chat.character_background_review.cancel_active_character_fix",
        lambda novel_id, name: _async_none(),
    )
    monkeypatch.setattr(
        "engine.setup_chat.character_background_review.schedule_character_quality_review",
        lambda name, **_kwargs: None,
    )
    monkeypatch.setattr(
        "engine.archive.archive_view.delete_character_archives",
        lambda name: {"removed_stages": 0, "deleted_chapters": []},
    )
    monkeypatch.setattr(
        "engine.setup_chat.timeline_auto.schedule_timeline_cascade",
        lambda chapter, names, **_kwargs: None,
    )

    schedule_calls = []
    monkeypatch.setattr(
        "engine.setup_chat.character_visual_tags.schedule_extract_visual_tags",
        lambda name: schedule_calls.append(name),
    )

    ok, _msg, char = await tools._edit_character_core(
        name="甲", given_name="甲", role="submissive", gender="female",
        causal_anchors={}, physique={"体型": "娇小"},  # 没变
        clothing_color_palette=[], clothing_materials=[],
        clothing_signature_outfit="", clothing_accessories=[],
        sliders={}, personality="", identity_background="",
        portrait_visual_tags="1girl, hand-typed tags",
    )

    assert ok is True
    assert schedule_calls == []
    assert saved["roster"][0]["portrait_visual_tags"] == "1girl, hand-typed tags"
    assert char["portrait_visual_tags"] == "1girl, hand-typed tags"


@pytest.mark.asyncio
async def test_edit_character_core_appearance_change_still_reextracts_over_manual_override(monkeypatch):
    """A same-edit appearance change (physique/gender/clothing) still wins over a manually
    typed portrait_visual_tags value -- the manual value is saved immediately but the
    scheduled re-extraction will supersede it shortly after, since the appearance is what
    actually changed."""
    from engine.setup_chat import tools

    existing = {
        "name": "甲", "given_name": "甲", "role": "submissive", "gender": "female",
        "causal_anchors": {}, "physique": {"体型": "娇小"},
        "clothing_dna": {"color_palette": [], "materials_preference": [],
                          "signature_outfit": "", "accessories": []},
        "sliders": {}, "personality": "", "identity_background": "",
        "portrait_visual_tags": "1girl, old tags",
    }
    saved = {}

    class _FakeRepo:
        def list_raw(self):
            return [dict(existing)]

        def save_all(self, roster):
            saved["roster"] = roster

    monkeypatch.setattr("repositories.get_lore_repo", _FakeRepo)
    monkeypatch.setattr("engine.setup_chat.tools.validate_character_edit", lambda char, roster, **_kw: [])
    monkeypatch.setattr(
        "engine.setup_chat.character_background_review.cancel_active_character_fix",
        lambda novel_id, name: _async_none(),
    )
    monkeypatch.setattr(
        "engine.setup_chat.character_background_review.schedule_character_quality_review",
        lambda name, **_kwargs: None,
    )
    monkeypatch.setattr(
        "engine.archive.archive_view.delete_character_archives",
        lambda name: {"removed_stages": 0, "deleted_chapters": []},
    )
    monkeypatch.setattr(
        "engine.setup_chat.timeline_auto.schedule_timeline_cascade",
        lambda chapter, names, **_kwargs: None,
    )

    schedule_calls = []
    monkeypatch.setattr(
        "engine.setup_chat.character_visual_tags.schedule_extract_visual_tags",
        lambda name: schedule_calls.append(name),
    )

    ok, _msg, char = await tools._edit_character_core(
        name="甲", given_name="甲", role="submissive", gender="female",
        causal_anchors={}, physique={"体型": "高挑"},  # 变了
        clothing_color_palette=[], clothing_materials=[],
        clothing_signature_outfit="", clothing_accessories=[],
        sliders={}, personality="", identity_background="",
        portrait_visual_tags="1girl, hand-typed tags",
    )

    assert ok is True
    assert schedule_calls == ["甲"]
    assert saved["roster"][0]["portrait_visual_tags"] == "1girl, hand-typed tags"


async def _async_none():
    return None
