"""Shared fixtures for tests/engine/setup_chat/."""
import pytest


@pytest.fixture(autouse=True)
def _rebuild_character_tool_schemas():
    """add_character/edit_character are @tool(args_schema=<static placeholder>)-decorated;
    the placeholder has no content-pack custom fields, only build_agent()
    overwrites .args_schema with the real, dynamically-rebuilt one per call (see agent.py).
    Tests in this directory invoke these tools directly via .ainvoke(...) without going
    through build_agent() first, so without this fixture, any active pack's required custom
    field silently gets dropped by the placeholder before ever reaching the underlying
    function -- previously masked only by test collection order accidentally leaking
    build_agent()'s rebuilt schema as global mutable state from test_agent.py running first
    (the exact hazard test_cast_tools.py's own docstring already flags for edit_character's
    `name` field); testmon's selective re-runs don't guarantee that order."""
    from engine.setup_chat.tool_args import build_add_character_args, build_edit_character_args
    from engine.setup_chat.tools import add_character, edit_character

    add_character.args_schema = build_add_character_args()
    edit_character.args_schema = build_edit_character_args()


@pytest.fixture(autouse=True)
def _low_stage_count_floor(monkeypatch):
    """Force target_words low enough that suggested_min_stage_count() == 1 by default, so the
    many single-stage plot fixtures across this test directory keep passing under the
    generate_one_chapter/patch_chapter hard stage-count gate (see
    engine.setup.plot.validator.validate_plot_chapters). Wraps the real load_dialogue_prefs
    instead of replacing it wholesale, so every other key (chat_identity, import_llm_params,
    auto_build_character_count, ...) still reflects real defaults/config for tests that read
    them. Tests exercising the floor itself override load_dialogue_prefs with their own
    monkeypatch.setattr call, which simply wins for that test."""
    import engine.modes.author_loop_skill_prefs as prefs_mod

    real = prefs_mod.load_dialogue_prefs

    def _patched() -> dict:
        prefs = real()
        prefs["target_words"] = 350
        from engine.setup_chat import setup_quality_review as sqr

        prefs["disabled_setup_review_hooks"] = list(
            sqr.SETUP_WORLD_HOOK_NAMES + sqr.SETUP_CAST_HOOK_NAMES
        )
        return prefs

    monkeypatch.setattr(prefs_mod, "load_dialogue_prefs", _patched)


@pytest.fixture(autouse=True)
def _stub_dialogue_draft(monkeypatch):
    """Default-stub engine.setup_chat.dialogue_draft._call_llm to a fast no-op returning ""
    for every test in this directory -- write_chapter_skeleton now calls draft_beat_dialogue
    once per generated beat (see tools._fill_dialogue_drafts), and the many existing tests
    across this directory that invoke the real write_chapter_skeleton tool were written before
    that step existed and don't expect a real LLM call. Tests exercising the dialogue-draft
    step itself override _call_llm or draft_beat_dialogue with their own monkeypatch.setattr
    call, which simply wins for that test (same convention as _low_stage_count_floor above)."""
    import engine.setup_chat.dialogue_draft as dd_mod

    async def _stub(system, user, **kwargs):
        return ""
    monkeypatch.setattr(dd_mod, "_call_llm", _stub)
