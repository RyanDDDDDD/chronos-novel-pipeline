import asyncio

import pytest
from api.services.message_hub import MessageHub
from engine.story_sandbox.state import SandboxStepType
import api.services.message_hub as mh_mod


@pytest.fixture(autouse=True)
def _isolated_story_sandbox_checkpoint(monkeypatch, tmp_path):
    """start_story_sandbox_turn/stop_story_sandbox_turn now call snapshot_state/restore_state
    for real on every call, whether or not an individual test mocks them out -- without this
    isolation, tests here would hit the real production checkpoint file, AND leak the
    module-global checkpointer (graph.ensure_checkpointer() only opens a new connection when it's
    still None) into tests/engine/story_sandbox/test_graph.py's own tmp_path-isolated tests if
    both files run in the same pytest session. Mirrors test_graph.py's own isolation fixture."""
    monkeypatch.setattr(
        "utils.paths.story_sandbox_checkpoint_path", lambda: str(tmp_path / "sandbox.sqlite"),
    )
    yield
    from engine.story_sandbox.graph import close_checkpointer

    # asyncio.run() (not get_event_loop()) -- this file mixes sync and @pytest.mark.asyncio
    # tests, so by the time this autouse fixture's teardown runs, pytest-asyncio's own
    # function-scoped loop may already be gone, and get_event_loop() raises "no current event
    # loop" in that case. asyncio.run() always creates its own loop, sidestepping that entirely.
    asyncio.run(close_checkpointer())


@pytest.fixture(autouse=True)
def _isolated_sandbox_llm_routing(monkeypatch):
    """llm_params/sandbox_llm_params live in the live, gitignored
    config/pipelines/<id>/author_loop_skill_prefs.json. If a developer has a per-node local
    provider override configured there (e.g. routing the sandbox "prose" node to a local model),
    bind_node_llm swaps to that real client regardless of get_cloud_llm mocking (see
    bind_node_llm's provider=="local" branch) -- silently making guard/rewrite tests depend on
    whatever's on the machine. Stub load_dialogue_prefs to the defaults so they stay hermetic."""
    import engine.modes.author_loop_skill_prefs as prefs_mod

    monkeypatch.setattr(
        prefs_mod, "load_dialogue_prefs",
        lambda: {
            "target_words": prefs_mod.DEFAULT_TARGET_WORDS,
            "disabled_buildtime_review_hooks": [], "disabled_runtime_review_hooks": [],
            "llm_params": {}, "sandbox_llm_params": {},
        },
    )


@pytest.mark.asyncio
async def test_start_story_sandbox_turn_runs_and_broadcasts_final(monkeypatch):
    hub = MessageHub()
    seen = []

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        yield {"type": SandboxStepType.INITIAL_STATE,
               "states": {"甲": {"psychology": "外冷内热"}},
               "scene_state": {"description": "昏暗的书房"}}
        yield {"type": SandboxStepType.PROSE, "text": "定稿正文",
               "recall_context": "## 相关历史/设定回收\n- 甲做了事"}
        yield {"type": SandboxStepType.STATE,
               "states": {"甲": {"psychology": "平静", "posture": "", "clothing": ""}},
               "scene_state": {"description": "凌乱的书房"}}
        yield {"type": SandboxStepType.SUGGESTIONS, "options": ["建议A", "建议B"]}

    async def fake_broadcast(ev):
        seen.append(ev)

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    assert {
        "type": "story_sandbox_initial_states",
        "states": {"甲": {"psychology": "外冷内热"}},
        "scene_state": {"description": "昏暗的书房"},
    } in seen
    assert {"type": "story_sandbox_final", "content": "定稿正文", "active_cast": []} in seen
    assert {
        "type": "story_sandbox_recall_context",
        "recall_context": "## 相关历史/设定回收\n- 甲做了事",
        "recalled_settings": [],
    } in seen
    assert {
        "type": "story_sandbox_states",
        "states": {"甲": {"psychology": "平静", "posture": "", "clothing": ""}},
        "scene_state": {"description": "凌乱的书房"},
        "active_cast": [],
    } in seen
    assert {"type": "story_sandbox_suggestions", "options": ["建议A", "建议B"], "round_id": None} in seen
    assert {"type": "story_sandbox_done"} in seen
    order = [e["type"] for e in seen]
    assert order.index("story_sandbox_initial_states") < order.index("story_sandbox_final")
    assert order.index("story_sandbox_final") < order.index("story_sandbox_states")
    assert order.index("story_sandbox_states") < order.index("story_sandbox_suggestions")
    assert order.index("story_sandbox_suggestions") < order.index("story_sandbox_done")


@pytest.mark.asyncio
async def test_start_story_sandbox_turn_broadcasts_event_log(monkeypatch):
    hub = MessageHub()
    seen = []

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        yield {
            "type": SandboxStepType.EVENT_LOG,
            "entries": [{"summary": "甲做了事", "time": "之后"}],
            "rolling_summary": "目前为止的摘要",
        }

    async def fake_broadcast(ev):
        seen.append(ev)

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    assert {
        "type": "story_sandbox_event_log",
        "entries": [{"summary": "甲做了事", "time": "之后"}],
        "rolling_summary": "目前为止的摘要",
    } in seen


@pytest.mark.asyncio
async def test_start_story_sandbox_turn_broadcasts_profile_mutation(monkeypatch):
    hub = MessageHub()
    seen = []

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        yield {
            "type": SandboxStepType.PROFILE_MUTATION,
            "mutation": {"甲": {"race": "精灵"}},
        }

    async def fake_broadcast(ev):
        seen.append(ev)

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    assert {
        "type": "story_sandbox_profile_mutation", "relationship_mutation": None,
        "mutation": {"甲": {"race": "精灵"}},
    } in seen


@pytest.mark.asyncio
async def test_start_story_sandbox_turn_partial_broadcasts_survive_a_later_failure(monkeypatch):
    hub = MessageHub()
    seen = []

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        yield {"type": SandboxStepType.PROSE, "text": "定稿正文", "initial_states": None}
        raise RuntimeError("模型挂了")

    async def fake_broadcast(ev):
        seen.append(ev)

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    assert {"type": "story_sandbox_final", "content": "定稿正文", "active_cast": []} in seen
    assert {"type": "story_sandbox_error", "error": "模型挂了"} in seen


@pytest.mark.asyncio
async def test_start_story_sandbox_turn_broadcasts_error_on_failure(monkeypatch):
    hub = MessageHub()
    seen = []

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        raise RuntimeError("模型挂了")
        yield  # pragma: no cover -- keeps this an async generator function; unreachable

    async def fake_broadcast(ev):
        seen.append(ev)

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    assert {"type": "story_sandbox_error", "error": "模型挂了"} in seen


@pytest.mark.asyncio
async def test_start_story_sandbox_turn_broadcasts_code_on_derivation_validation_error(monkeypatch):
    from engine.story_sandbox.derivation_retry import DerivationValidationError, SandboxErrorCode

    hub = MessageHub()
    seen = []

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        raise DerivationValidationError(SandboxErrorCode.STATE_DERIVE_FAILED, "不是JSON")
        yield  # pragma: no cover -- keeps this an async generator function; unreachable

    async def fake_broadcast(ev):
        seen.append(ev)

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    errors = [e for e in seen if e["type"] == "story_sandbox_error"]
    assert len(errors) == 1
    assert errors[0]["code"] == "STATE_DERIVE_FAILED"


@pytest.mark.asyncio
async def test_start_story_sandbox_turn_rejects_concurrent_calls():
    hub = MessageHub()
    hub._story_sandbox_tasks[mh_mod.active_novel_id()] = type("T", (), {"done": lambda self: False})()
    with pytest.raises(RuntimeError):
        await hub.start_story_sandbox_turn(1, "继续")


@pytest.mark.asyncio
async def test_story_sandbox_history_returns_rounds(monkeypatch):
    hub = MessageHub()
    seen = []

    async def fake_peek_state(novel_id, chapter, branch_id=None):
        seen.append((novel_id, chapter))
        return {
            "turns": [{
                "instruction": "继续", "prose": "他抬起头。",
                "character_states": {"甲": {"personality": "平静"}},
                "suggestions": ["之前的建议"],
            }],
            "rolling_summary": "",
            "character_states": {"甲": {"personality": "平静"}},
            "suggestions": ["之前的建议"],
        }

    monkeypatch.setattr("engine.story_sandbox.graph.peek_state", fake_peek_state)
    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "fallback-novel")
    result = await hub.story_sandbox_history(1, novel_id="novel-explicit")
    assert seen == [("novel-explicit", 1)]
    assert result == {
        "rounds": [{
            "instruction": "继续", "prose": "他抬起头。",
            "character_states": {"甲": {"personality": "平静"}},
            "suggestions": ["之前的建议"],
        }],
        "active_cast": [],
        "live_round": None,
    }


@pytest.mark.asyncio
async def test_delete_story_sandbox_branch_calls_graph_reset_when_idle(monkeypatch):
    hub = MessageHub()
    called = []

    async def fake_reset_chapter(novel_id, chapter, branch_id=None):
        called.append((novel_id, chapter, branch_id))

    def fake_delete_branch(chapter, branch_id):
        return {"id": branch_id, "chapter": chapter}

    monkeypatch.setattr("engine.story_sandbox.graph.reset_chapter", fake_reset_chapter)
    monkeypatch.setattr("engine.story_sandbox.branches.delete_branch", fake_delete_branch)
    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "novel-x")
    result = await hub.delete_story_sandbox_branch(3, "branch-1")
    assert called == [("novel-x", 3, "branch-1")]
    assert result == {"id": "branch-1", "chapter": 3}


@pytest.mark.asyncio
async def test_delete_story_sandbox_branch_rejects_while_busy():
    hub = MessageHub()
    hub._story_sandbox_tasks[mh_mod.active_novel_id()] = type("T", (), {"done": lambda self: False})()
    with pytest.raises(RuntimeError):
        await hub.delete_story_sandbox_branch(3, "branch-1")


@pytest.mark.asyncio
async def test_reset_story_sandbox_branch_calls_graph_reset_and_touches_branch(monkeypatch):
    hub = MessageHub()
    reset_called = []
    touch_called = []

    async def fake_reset_chapter(novel_id, chapter, branch_id=None):
        reset_called.append((novel_id, chapter, branch_id))

    def fake_touch_branch(chapter, branch_id):
        touch_called.append((chapter, branch_id))

    def fake_get_branch(chapter, branch_id):
        return {"id": branch_id, "chapter": chapter, "name": "故事线1"}

    monkeypatch.setattr("engine.story_sandbox.graph.reset_chapter", fake_reset_chapter)
    monkeypatch.setattr("engine.story_sandbox.branches.touch_branch", fake_touch_branch)
    monkeypatch.setattr("engine.story_sandbox.branches.get_branch", fake_get_branch)
    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "novel-x")
    result = await hub.reset_story_sandbox_branch(3, "branch-1")
    assert reset_called == [("novel-x", 3, "branch-1")]
    assert touch_called == [(3, "branch-1")]
    assert result == {"id": "branch-1", "chapter": 3, "name": "故事线1"}


@pytest.mark.asyncio
async def test_reset_story_sandbox_branch_rejects_while_busy():
    hub = MessageHub()
    hub._story_sandbox_tasks[mh_mod.active_novel_id()] = type("T", (), {"done": lambda self: False})()
    with pytest.raises(RuntimeError):
        await hub.reset_story_sandbox_branch(3, "branch-1")


@pytest.mark.asyncio
async def test_create_story_sandbox_branch_without_source_just_creates_blank(monkeypatch):
    hub = MessageHub()
    called = []

    def fake_create_branch(chapter, name):
        called.append((chapter, name))
        return {"id": "new-id", "chapter": chapter, "name": "故事线1", "created_at": "t", "updated_at": "t"}

    monkeypatch.setattr("engine.story_sandbox.branches.create_branch", fake_create_branch)
    result = await hub.create_story_sandbox_branch(8)
    assert result["id"] == "new-id"
    assert called == [(8, None)]


@pytest.mark.asyncio
async def test_create_story_sandbox_branch_with_source_forks_state_and_memory(monkeypatch):
    hub = MessageHub()
    fork_calls = []
    event_log_calls = []
    vector_calls = []

    def fake_create_branch(chapter, name):
        return {"id": "new-id", "chapter": chapter, "name": "故事线2", "created_at": "t", "updated_at": "t"}

    async def fake_fork_branch(novel_id, chapter, source_branch_id, dest_branch_id):
        fork_calls.append((novel_id, chapter, source_branch_id, dest_branch_id))
        return {"old-1": "new-1"}

    async def fake_copy_entries_for_branch(chapter, dest_branch_id, id_remap):
        event_log_calls.append((chapter, dest_branch_id, id_remap))

    class FakeVectorRepo:
        async def copy_branch(self, chapter, source_branch_id, dest_branch_id, id_remap):
            vector_calls.append((chapter, source_branch_id, dest_branch_id, id_remap))

    monkeypatch.setattr("engine.story_sandbox.branches.create_branch", fake_create_branch)
    monkeypatch.setattr("engine.story_sandbox.graph.fork_branch", fake_fork_branch)
    monkeypatch.setattr("engine.memory_recall.event_log.copy_entries_for_branch", fake_copy_entries_for_branch)
    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "novel-x")
    monkeypatch.setattr("repositories.get_sandbox_vector_memory_repo", lambda: FakeVectorRepo())

    result = await hub.create_story_sandbox_branch(8, source_branch_id="src-id")

    assert result["id"] == "new-id"
    assert fork_calls == [("novel-x", 8, "src-id", "new-id")]
    assert event_log_calls == [(8, "new-id", {"old-1": "new-1"})]
    assert vector_calls == [(8, "src-id", "new-id", {"old-1": "new-1"})]


@pytest.mark.asyncio
async def test_create_story_sandbox_branch_with_source_but_empty_remap_skips_copy_calls(monkeypatch):
    hub = MessageHub()
    copy_called = []

    def fake_create_branch(chapter, name):
        return {"id": "new-id", "chapter": chapter, "name": "故事线2", "created_at": "t", "updated_at": "t"}

    async def fake_fork_branch(novel_id, chapter, source_branch_id, dest_branch_id):
        return {}

    async def fake_copy_entries_for_branch(chapter, dest_branch_id, id_remap):
        copy_called.append(True)

    monkeypatch.setattr("engine.story_sandbox.branches.create_branch", fake_create_branch)
    monkeypatch.setattr("engine.story_sandbox.graph.fork_branch", fake_fork_branch)
    monkeypatch.setattr("engine.memory_recall.event_log.copy_entries_for_branch", fake_copy_entries_for_branch)
    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "novel-x")

    await hub.create_story_sandbox_branch(8, source_branch_id="src-id")
    assert copy_called == []


@pytest.mark.asyncio
async def test_create_story_sandbox_branch_rejects_while_busy():
    hub = MessageHub()
    hub._story_sandbox_tasks[mh_mod.active_novel_id()] = type("T", (), {"done": lambda self: False})()
    with pytest.raises(RuntimeError):
        await hub.create_story_sandbox_branch(8, source_branch_id="src-id")


@pytest.mark.asyncio
async def test_reset_story_sandbox_closes_checkpointer_when_idle(monkeypatch):
    hub = MessageHub()
    called = []

    # Optional novel_id, matching the real close_checkpointer's signature -- this file's own
    # autouse teardown fixture calls close_checkpointer() bare (no args) after every test, and
    # this monkeypatch is still active at that point.
    async def fake_close(novel_id=None):
        called.append(novel_id)

    monkeypatch.setattr("engine.story_sandbox.graph.close_checkpointer", fake_close)
    await hub.reset_story_sandbox()
    assert called == [mh_mod.active_novel_id()]


@pytest.mark.asyncio
async def test_reset_story_sandbox_skips_close_while_busy(monkeypatch):
    hub = MessageHub()
    hub._story_sandbox_tasks[mh_mod.active_novel_id()] = type("T", (), {"done": lambda self: False})()
    called = []

    async def fake_close(novel_id=None):
        called.append(novel_id)

    monkeypatch.setattr("engine.story_sandbox.graph.close_checkpointer", fake_close)
    await hub.reset_story_sandbox()
    assert called == []


@pytest.mark.asyncio
async def test_regenerate_story_sandbox_suggestions_calls_graph_when_idle(monkeypatch):
    hub = MessageHub()
    seen = []

    async def fake_broadcast(ev):
        seen.append(ev)

    async def fake_regenerate(novel_id, chapter, call_llm, *, guard_text, hint="", run_skill_agent=None, branch_id=None):
        assert novel_id == "novel-x"
        assert chapter == 3
        return ["新建议A", "新建议B"]

    monkeypatch.setattr("engine.story_sandbox.graph.regenerate_suggestions", fake_regenerate)
    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "novel-x")
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    await hub.regenerate_story_sandbox_suggestions(3)
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    assert {
        "type": "story_sandbox_suggestions_regenerated", "options": ["新建议A", "新建议B"],
    } in seen
    assert mh_mod.active_novel_id() not in hub._story_sandbox_tasks
    #Frontend infers busy purely from story_sandbox_* event prefixes -- without this leading
    #event, the novel-switch guard never locks for this one-shot (non-streaming) call.
    regenerating_idx = next(i for i, ev in enumerate(seen) if ev["type"] == "story_sandbox_suggestions_regenerating")
    regenerated_idx = next(i for i, ev in enumerate(seen) if ev["type"] == "story_sandbox_suggestions_regenerated")
    assert regenerating_idx < regenerated_idx


@pytest.mark.asyncio
async def test_regenerate_story_sandbox_suggestions_rejects_while_busy():
    hub = MessageHub()
    hub._story_sandbox_tasks[mh_mod.active_novel_id()] = type("T", (), {"done": lambda self: False})()
    with pytest.raises(RuntimeError):
        await hub.regenerate_story_sandbox_suggestions(3)


@pytest.mark.asyncio
async def test_regenerate_story_sandbox_suggestions_forwards_hint(monkeypatch):
    hub = MessageHub()
    seen = {}

    async def fake_broadcast(ev):
        pass

    async def fake_regenerate(novel_id, chapter, call_llm, *, guard_text, hint="", run_skill_agent=None, branch_id=None):
        seen["hint"] = hint
        return ["新建议A"]

    monkeypatch.setattr("engine.story_sandbox.graph.regenerate_suggestions", fake_regenerate)
    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "novel-x")
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    await hub.regenerate_story_sandbox_suggestions(3, hint="往乙这边的反应上靠一点")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    assert seen["hint"] == "往乙这边的反应上靠一点"


@pytest.mark.asyncio
async def test_regenerate_story_sandbox_suggestions_defaults_hint_to_empty(monkeypatch):
    hub = MessageHub()
    seen = {}

    async def fake_broadcast(ev):
        pass

    async def fake_regenerate(novel_id, chapter, call_llm, *, guard_text, hint="", run_skill_agent=None, branch_id=None):
        seen["hint"] = hint
        return []

    monkeypatch.setattr("engine.story_sandbox.graph.regenerate_suggestions", fake_regenerate)
    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "novel-x")
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    await hub.regenerate_story_sandbox_suggestions(3)
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    assert seen["hint"] == ""


@pytest.mark.asyncio
async def test_regenerate_story_sandbox_suggestions_passes_a_run_skill_agent(monkeypatch):
    hub = MessageHub()
    seen = {}

    async def fake_broadcast(ev):
        pass

    async def fake_regenerate(novel_id, chapter, call_llm, *, guard_text, hint="", run_skill_agent=None, branch_id=None):
        seen["run_skill_agent"] = run_skill_agent
        return []

    monkeypatch.setattr("engine.story_sandbox.graph.regenerate_suggestions", fake_regenerate)
    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "novel-x")
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    await hub.regenerate_story_sandbox_suggestions(3)
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    assert callable(seen["run_skill_agent"])


@pytest.mark.asyncio
async def test_start_story_sandbox_rewrite_runs_and_broadcasts_done(monkeypatch):
    hub = MessageHub()
    seen = []

    async def fake_rewrite_last_round(novel_id, chapter, feedback, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        assert feedback == "语气再冷淡一点"

        async def _gen():
            yield {"type": SandboxStepType.PROSE, "text": "重写后的正文",
                   "initial_states": None, "initial_scene_state": None}
            yield {"type": SandboxStepType.STATE, "states": {"甲": {"psychology": "冷淡"}},
                   "scene_state": {"description": "被打翻的书房"}}
            yield {"type": SandboxStepType.SUGGESTIONS, "options": ["建议A"]}
        return _gen()

    async def fake_broadcast(ev):
        seen.append(ev)

    monkeypatch.setattr(
        "engine.story_sandbox.graph.rewrite_last_round", fake_rewrite_last_round,
    )
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_rewrite(1, "语气再冷淡一点")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    assert {
        "type": "story_sandbox_states",
        "states": {"甲": {"psychology": "冷淡"}},
        "scene_state": {"description": "被打翻的书房"},
        "active_cast": [],
    } in seen
    assert {"type": "story_sandbox_suggestions", "options": ["建议A"]} in seen
    assert {
        "type": "story_sandbox_rewrite_done",
        "content": "重写后的正文",
        "states": {"甲": {"psychology": "冷淡"}},
        "scene_state": {"description": "被打翻的书房"},
        "suggestions": ["建议A"],
        "recall_context": "",
        "recalled_settings": [],
        "active_cast": [],
        "entries": [],
        "rolling_summary": "",
        "mutation": None,
        "relationship_mutation": None,
    } in seen


@pytest.mark.asyncio
async def test_start_story_sandbox_rewrite_bundles_event_log_and_profile_mutation_into_done(monkeypatch):
    """rewrite re-derives event_log/profile_mutation from the rewritten prose -- these must
    reach story_sandbox_rewrite_done so the frontend can refresh the round instead of leaving
    the pre-rewrite entry/mutation stuck on screen (there is no dedicated "pending" UI for
    these two fields, so rewrite_done is the only place they can be corrected)."""
    hub = MessageHub()
    seen = []

    async def fake_rewrite_last_round(novel_id, chapter, feedback, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        async def _gen():
            yield {"type": SandboxStepType.PROSE, "text": "重写后的正文",
                   "initial_states": None, "initial_scene_state": None}
            yield {"type": SandboxStepType.STATE, "states": {}, "scene_state": {}}
            yield {
                "type": SandboxStepType.EVENT_LOG,
                "entries": [{"summary": "甲摔门离开", "time": "傍晚"}],
                "rolling_summary": "折叠后的摘要",
            }
            yield {
                "type": SandboxStepType.PROFILE_MUTATION,
                "mutation": {"甲": {"sliders": {"warmth": 1}}},
            }
            yield {"type": SandboxStepType.SUGGESTIONS, "options": []}
        return _gen()

    async def fake_broadcast(ev):
        seen.append(ev)

    monkeypatch.setattr(
        "engine.story_sandbox.graph.rewrite_last_round", fake_rewrite_last_round,
    )
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_rewrite(1, "反馈")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    done = next(e for e in seen if e["type"] == "story_sandbox_rewrite_done")
    assert done["entries"] == [{"summary": "甲摔门离开", "time": "傍晚"}]
    assert done["rolling_summary"] == "折叠后的摘要"
    assert done["mutation"] == {"甲": {"sliders": {"warmth": 1}}}


@pytest.mark.asyncio
async def test_start_story_sandbox_turn_broadcasts_empty_recall_context(monkeypatch):
    hub = MessageHub()
    seen = []

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        yield {"type": SandboxStepType.PROSE, "text": "定稿正文", "initial_states": None}

    async def fake_broadcast(ev):
        seen.append(ev)

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    assert {"type": "story_sandbox_recall_context", "recall_context": "", "recalled_settings": []} in seen


@pytest.mark.asyncio
async def test_start_story_sandbox_rewrite_bundles_recall_context_into_done(monkeypatch):
    hub = MessageHub()
    seen = []

    async def fake_rewrite_last_round(novel_id, chapter, feedback, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        async def _gen():
            yield {
                "type": SandboxStepType.PROSE, "text": "重写后的正文",
                "initial_states": None, "initial_scene_state": None,
                "recall_context": "重写后的召回内容",
            }
            yield {"type": SandboxStepType.STATE, "states": {}, "scene_state": {}}
            yield {"type": SandboxStepType.SUGGESTIONS, "options": []}
        return _gen()

    async def fake_broadcast(ev):
        seen.append(ev)

    monkeypatch.setattr(
        "engine.story_sandbox.graph.rewrite_last_round", fake_rewrite_last_round,
    )
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_rewrite(1, "反馈")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    done = next(e for e in seen if e["type"] == "story_sandbox_rewrite_done")
    assert done["recall_context"] == "重写后的召回内容"


@pytest.mark.asyncio
async def test_start_story_sandbox_rewrite_broadcasts_error_on_failure(monkeypatch):
    hub = MessageHub()
    seen = []

    async def fake_rewrite_last_round(novel_id, chapter, feedback, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        raise RuntimeError("模型挂了")

    async def fake_broadcast(ev):
        seen.append(ev)

    monkeypatch.setattr(
        "engine.story_sandbox.graph.rewrite_last_round", fake_rewrite_last_round,
    )
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_rewrite(1, "反馈")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    assert {"type": "story_sandbox_error", "error": "模型挂了"} in seen


@pytest.mark.asyncio
async def test_start_story_sandbox_rewrite_broadcasts_code_on_derivation_validation_error(monkeypatch):
    from engine.story_sandbox.derivation_retry import DerivationValidationError, SandboxErrorCode

    hub = MessageHub()
    seen = []

    async def fake_rewrite_last_round(novel_id, chapter, feedback, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        raise DerivationValidationError(SandboxErrorCode.SCENE_DERIVE_FAILED, "不是JSON")

    async def fake_broadcast(ev):
        seen.append(ev)

    monkeypatch.setattr(
        "engine.story_sandbox.graph.rewrite_last_round", fake_rewrite_last_round,
    )
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_rewrite(1, "反馈")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    errors = [e for e in seen if e["type"] == "story_sandbox_error"]
    assert len(errors) == 1
    assert errors[0]["code"] == "SCENE_DERIVE_FAILED"


@pytest.mark.asyncio
async def test_start_story_sandbox_rewrite_rejects_concurrent_calls():
    hub = MessageHub()
    hub._story_sandbox_tasks[mh_mod.active_novel_id()] = type("T", (), {"done": lambda self: False})()
    with pytest.raises(RuntimeError):
        await hub.start_story_sandbox_rewrite(1, "反馈")


@pytest.mark.asyncio
async def test_start_story_sandbox_turn_forwards_submitted_directions(monkeypatch):
    hub = MessageHub()
    seen = {}

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        seen["submitted_directions"] = submitted_directions
        yield {"type": SandboxStepType.PROSE, "text": "正文", "initial_states": None}
        yield {"type": SandboxStepType.STATE, "states": {}}
        yield {"type": SandboxStepType.SUGGESTIONS, "options": []}

    async def fake_broadcast(ev):
        pass

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "- 建议一", submitted_directions=["建议一"])
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    assert seen["submitted_directions"] == ["建议一"]


@pytest.mark.asyncio
async def test_start_story_sandbox_turn_defaults_submitted_directions_to_none(monkeypatch):
    hub = MessageHub()
    seen = {}

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        seen["submitted_directions"] = submitted_directions
        yield {"type": SandboxStepType.PROSE, "text": "正文", "initial_states": None}
        yield {"type": SandboxStepType.STATE, "states": {}}
        yield {"type": SandboxStepType.SUGGESTIONS, "options": []}

    async def fake_broadcast(ev):
        pass

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    assert seen["submitted_directions"] is None


@pytest.mark.asyncio
async def test_stop_story_sandbox_turn_cancels_and_restores(monkeypatch):
    hub = MessageHub()
    seen = []
    started = asyncio.Event()

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        started.set()
        await asyncio.sleep(3600)
        yield {"type": SandboxStepType.SUGGESTIONS, "options": []}  # pragma: no cover -- never reached

    async def fake_broadcast(ev):
        seen.append(ev)

    async def fake_snapshot_state(novel_id, chapter, branch_id=None):
        return {"rolling_summary": "轮前状态"}

    restored = {}

    async def fake_restore_state(novel_id, chapter, values, branch_id=None):
        restored["values"] = values

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)
    monkeypatch.setattr("api.services.message_hub.snapshot_story_sandbox_state", fake_snapshot_state)
    monkeypatch.setattr("api.services.message_hub.restore_story_sandbox_state", fake_restore_state)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    # get_cloud_llm() is a module-global-cached singleton (llm/factory.py::_cloud_llm_instance)
    # wrapping a real httpx.AsyncClient. Actually cancelling an in-flight task (unlike every
    # other pre-existing test here, which lets the fake generator run to natural completion)
    # exposed a cross-event-loop hang when that real client got constructed and then abandoned
    # -- mock it so this test never touches it (root-caused via bisection against the full suite).
    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: object())

    await hub.start_story_sandbox_turn(1, "继续")
    await asyncio.wait_for(started.wait(), timeout=1)
    await hub.stop_story_sandbox_turn(1)

    assert restored["values"] == {"rolling_summary": "轮前状态"}
    assert {
        "type": "story_sandbox_turn_cancelled", "chapter": 1, "rollback_failed": False,
        "novel_id": mh_mod.active_novel_id(),
    } in seen
    assert mh_mod.active_novel_id() not in hub._story_sandbox_tasks


@pytest.mark.asyncio
async def test_stop_story_sandbox_turn_with_no_running_task_is_a_noop(monkeypatch):
    hub = MessageHub()
    seen = []

    async def fake_broadcast(ev):
        seen.append(ev)

    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    await hub.stop_story_sandbox_turn(1)
    assert seen == []


@pytest.mark.asyncio
async def test_stop_story_sandbox_turn_marks_rollback_failed_on_restore_error(monkeypatch):
    hub = MessageHub()
    seen = []
    started = asyncio.Event()

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        started.set()
        await asyncio.sleep(3600)
        yield {"type": SandboxStepType.SUGGESTIONS, "options": []}  # pragma: no cover

    async def fake_broadcast(ev):
        seen.append(ev)

    async def fake_snapshot_state(novel_id, chapter, branch_id=None):
        return {}

    async def fake_restore_state_raises(novel_id, chapter, values, branch_id=None):
        raise OSError("disk full")

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)
    monkeypatch.setattr("api.services.message_hub.snapshot_story_sandbox_state", fake_snapshot_state)
    monkeypatch.setattr("api.services.message_hub.restore_story_sandbox_state", fake_restore_state_raises)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    # See the get_cloud_llm mock comment in test_stop_story_sandbox_turn_cancels_and_restores above.
    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: object())

    await hub.start_story_sandbox_turn(1, "继续")
    await asyncio.wait_for(started.wait(), timeout=1)
    await hub.stop_story_sandbox_turn(1)

    assert {
        "type": "story_sandbox_turn_cancelled", "chapter": 1, "rollback_failed": True,
        "novel_id": mh_mod.active_novel_id(),
    } in seen


def test_story_sandbox_stop_endpoint_calls_hub(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient

    calls = []

    async def fake_stop(chapter, branch_id=None):
        calls.append(chapter)

    from api import routes

    monkeypatch.setattr(routes._hub_instance(), "stop_story_sandbox_turn", fake_stop)
    client = TestClient(app)
    res = client.post("/api/story-sandbox/stop", json={"chapter": 3, "branch_id": "b1"})
    assert res.status_code == 200
    assert calls == [3]


@pytest.mark.asyncio
async def test_start_story_sandbox_turn_records_token_ledger(monkeypatch, tmp_path):
    """call_llm_derive_char must feed extracted usage into the token ledger, not just
    return the response text and discard usage entirely."""
    from langchain_core.messages import AIMessage

    class _FakeLLM:
        model = "test-model"

        def bind(self, **kwargs):
            return self

        async def ainvoke(self, messages):
            return AIMessage(
                content="{}",
                usage_metadata={
                    "input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                    "input_token_details": {},
                },
            )

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "default")
    (tmp_path / "default").mkdir()

    hub = MessageHub()
    captured = {}

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        captured["call_llm_derive_char"] = call_llm_derive_char
        yield {"type": SandboxStepType.SUGGESTIONS, "options": []}

    async def fake_broadcast(ev):
        pass

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t

    await captured["call_llm_derive_char"]("system", "user")

    from api.services import token_ledger
    ledger = token_ledger.load_ledger()
    cell = ledger["story_sandbox"]["1"]
    assert cell["tokens_in"] == 10
    assert cell["tokens_out"] == 5


@pytest.mark.asyncio
async def test_delete_story_sandbox_branch_does_not_touch_token_ledger(monkeypatch, tmp_path):
    """Unlike the old whole-chapter reset, deleting a single branch must NOT zero the
    chapter's ledger cell -- cost accounting stays chapter-scoped, shared across that
    chapter's still-live sibling branches (see delete_story_sandbox_branch's docstring)."""
    from engine.story_sandbox import branches as sandbox_branches
    from engine.story_sandbox import graph as sandbox_graph

    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "default")
    (tmp_path / "default").mkdir()

    async def fake_reset_chapter(novel_id, chapter, branch_id=None):
        pass

    def fake_delete_branch(chapter, branch_id):
        return {"id": branch_id, "chapter": chapter}

    monkeypatch.setattr(sandbox_graph, "reset_chapter", fake_reset_chapter)
    monkeypatch.setattr(sandbox_branches, "delete_branch", fake_delete_branch)

    from api.services import token_ledger
    token_ledger.add_to_cell("story_sandbox", "1", 100, 50, 0, "test-model")

    hub = MessageHub()
    await hub.delete_story_sandbox_branch(1, "branch-1")

    ledger = token_ledger.load_ledger()
    assert ledger["story_sandbox"]["1"] == {
        "tokens_in": 100, "tokens_out": 50, "tokens_cached": 0, "model": "test-model",
    }


@pytest.mark.asyncio
async def test_reset_story_sandbox_branch_does_not_touch_token_ledger(monkeypatch, tmp_path):
    """Same rule as delete: cost accounting stays chapter-scoped, shared across that chapter's
    other branches -- resetting one branch's content must not zero the shared ledger cell."""
    from engine.story_sandbox import branches as sandbox_branches
    from engine.story_sandbox import graph as sandbox_graph

    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "default")
    (tmp_path / "default").mkdir()

    async def fake_reset_chapter(novel_id, chapter, branch_id=None):
        pass

    def fake_touch_branch(chapter, branch_id):
        pass

    def fake_get_branch(chapter, branch_id):
        return {"id": branch_id, "chapter": chapter}

    monkeypatch.setattr(sandbox_graph, "reset_chapter", fake_reset_chapter)
    monkeypatch.setattr(sandbox_branches, "touch_branch", fake_touch_branch)
    monkeypatch.setattr(sandbox_branches, "get_branch", fake_get_branch)

    from api.services import token_ledger
    token_ledger.add_to_cell("story_sandbox", "1", 100, 50, 0, "test-model")

    hub = MessageHub()
    await hub.reset_story_sandbox_branch(1, "branch-1")

    ledger = token_ledger.load_ledger()
    assert ledger["story_sandbox"]["1"] == {
        "tokens_in": 100, "tokens_out": 50, "tokens_cached": 0, "model": "test-model",
    }


def test_story_sandbox_message_endpoint_accepts_chapter_zero(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient
    from api import routes

    calls = []

    async def fake_start(chapter, text, submitted_directions=None, branch_id=None):
        calls.append(chapter)

    monkeypatch.setattr(routes._hub_instance(), "start_story_sandbox_turn", fake_start)
    client = TestClient(app)
    res = client.post(
        "/api/story-sandbox/message",
        json={"chapter": 0, "text": "开始自由创作", "branch_id": "b1"},
    )
    assert res.status_code == 200
    assert calls == [0]


def test_story_sandbox_message_endpoint_still_rejects_negative_chapter():
    from api.hub import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    res = client.post(
        "/api/story-sandbox/message", json={"chapter": -1, "text": "文本", "branch_id": "b1"},
    )
    assert res.status_code == 400


def test_story_sandbox_branches_endpoint_lists_existing(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(
        "engine.story_sandbox.branches.list_branches",
        lambda chapter: [{"id": "b1", "chapter": chapter, "name": "故事线1", "created_at": "t", "updated_at": "t"}],
    )
    client = TestClient(app)
    res = client.get("/api/story-sandbox/branches", params={"chapter": 8})
    assert res.status_code == 200
    assert res.json()["branches"][0]["id"] == "b1"


def test_story_sandbox_branches_endpoint_auto_registers_default_when_empty(monkeypatch):
    """A brand-new novel/chapter has no registry entries and no pre-existing checkpoint thread --
    the endpoint must still seed a default '故事线1' branch (via register_legacy_branch) so the
    frontend's story-line dropdown is never empty, not just adopt a pre-existing legacy thread."""
    from api.hub import app
    from fastapi.testclient import TestClient

    calls = []

    def fake_list_branches(chapter):
        calls.append(chapter)
        if len(calls) == 1:
            return []
        return [{"id": "legacy", "chapter": chapter, "name": "故事线1", "created_at": "t", "updated_at": "t"}]

    registered = []
    monkeypatch.setattr("engine.story_sandbox.branches.list_branches", fake_list_branches)
    monkeypatch.setattr(
        "engine.story_sandbox.branches.register_legacy_branch",
        lambda chapter: registered.append(chapter),
    )

    client = TestClient(app)
    res = client.get("/api/story-sandbox/branches", params={"chapter": 8})

    assert res.status_code == 200
    assert registered == [8]
    assert res.json()["branches"][0]["id"] == "legacy"


def test_story_sandbox_branches_endpoint_honors_explicit_novel_id_over_ambient_active(monkeypatch):
    """Regression: the frontend always passes novel_id explicitly (useStorySandboxBranches), and
    this must be honored even when the backend's ambient active_novel_id() currently points at a
    DIFFERENT novel (e.g. another browser action just switched focus elsewhere) -- otherwise a
    user switching back to a novel sees the wrong (or empty) branch list until something else
    happens to resync the ambient pointer. list_branches(chapter) itself has no novel_id
    parameter and resolves its file path via ambient active_novel_id() -- the endpoint must wrap
    the call in use_novel(nid) rather than calling it bare."""
    from api.hub import app
    from fastapi.testclient import TestClient
    from utils.paths import active_novel_id

    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "novel-B")
    assert active_novel_id() == "novel-B"

    seen_novel_ids = []

    def fake_list_branches(chapter):
        seen_novel_ids.append(active_novel_id())
        return [{"id": "a1", "chapter": chapter, "name": "A线", "created_at": "t", "updated_at": "t"}]

    monkeypatch.setattr("engine.story_sandbox.branches.list_branches", fake_list_branches)

    client = TestClient(app)
    res = client.get("/api/story-sandbox/branches", params={"chapter": 8, "novel_id": "novel-A"})

    assert res.status_code == 200
    assert res.json()["branches"][0]["id"] == "a1"
    assert seen_novel_ids == ["novel-A"]
    # Ambient pointer must be restored afterwards -- use_novel() is a context manager, not a
    # permanent override.
    assert active_novel_id() == "novel-B"


def test_story_sandbox_create_branch_endpoint(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(
        "engine.story_sandbox.branches.create_branch",
        lambda chapter, name=None: {"id": "new", "chapter": chapter, "name": name or "故事线1", "created_at": "t", "updated_at": "t"},
    )
    client = TestClient(app)
    res = client.post("/api/story-sandbox/branches", json={"chapter": 8})
    assert res.status_code == 200
    assert res.json()["branch"]["id"] == "new"


def test_story_sandbox_create_branch_endpoint_threads_source_branch_id(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient
    from api import routes

    calls = []

    async def fake_create(chapter, name=None, source_branch_id=None):
        calls.append((chapter, name, source_branch_id))
        return {"id": "new-id", "chapter": chapter, "name": "故事线2", "created_at": "t", "updated_at": "t"}

    monkeypatch.setattr(routes._hub_instance(), "create_story_sandbox_branch", fake_create)
    client = TestClient(app)
    res = client.post(
        "/api/story-sandbox/branches", json={"chapter": 8, "source_branch_id": "src-id"},
    )
    assert res.status_code == 200
    assert calls == [(8, None, "src-id")]


def test_story_sandbox_create_branch_endpoint_409_when_busy(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient
    from api import routes

    async def fake_create(chapter, name=None, source_branch_id=None):
        raise RuntimeError("上一轮沙盒回合还在进行，请稍候")

    monkeypatch.setattr(routes._hub_instance(), "create_story_sandbox_branch", fake_create)
    client = TestClient(app)
    res = client.post("/api/story-sandbox/branches", json={"chapter": 8})
    assert res.status_code == 409


def test_story_sandbox_rename_branch_endpoint_404_when_missing(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient

    def fake_rename(chapter, branch_id, name):
        raise ValueError("故事线不存在: x")

    monkeypatch.setattr("engine.story_sandbox.branches.rename_branch", fake_rename)
    client = TestClient(app)
    res = client.patch(
        "/api/story-sandbox/branches/x", params={"chapter": 8}, json={"name": "新名字"},
    )
    assert res.status_code == 404


def test_story_sandbox_delete_branch_endpoint_calls_hub(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient
    from api import routes

    calls = []

    async def fake_delete(chapter, branch_id):
        calls.append((chapter, branch_id))
        return {"id": "next", "chapter": chapter, "name": "故事线2", "created_at": "t", "updated_at": "t"}

    monkeypatch.setattr(routes._hub_instance(), "delete_story_sandbox_branch", fake_delete)
    client = TestClient(app)
    res = client.delete("/api/story-sandbox/branches/old", params={"chapter": 8})
    assert res.status_code == 200
    assert calls == [(8, "old")]
    assert res.json()["branch"]["id"] == "next"


def test_story_sandbox_delete_branch_endpoint_409_when_busy(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient
    from api import routes

    async def fake_delete(chapter, branch_id):
        raise RuntimeError("上一轮沙盒回合还在进行，请稍候")

    monkeypatch.setattr(routes._hub_instance(), "delete_story_sandbox_branch", fake_delete)
    client = TestClient(app)
    res = client.delete("/api/story-sandbox/branches/old", params={"chapter": 8})
    assert res.status_code == 409


def test_story_sandbox_reset_branch_endpoint_calls_hub(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient
    from api import routes

    calls = []

    async def fake_reset(chapter, branch_id):
        calls.append((chapter, branch_id))
        return {"id": branch_id, "chapter": chapter, "name": "故事线1", "created_at": "t", "updated_at": "t2"}

    monkeypatch.setattr(routes._hub_instance(), "reset_story_sandbox_branch", fake_reset)
    client = TestClient(app)
    res = client.post("/api/story-sandbox/branches/b1/reset", params={"chapter": 8})
    assert res.status_code == 200
    assert calls == [(8, "b1")]
    assert res.json()["branch"]["id"] == "b1"


def test_story_sandbox_reset_branch_endpoint_409_when_busy(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient
    from api import routes

    async def fake_reset(chapter, branch_id):
        raise RuntimeError("上一轮沙盒回合还在进行，请稍候")

    monkeypatch.setattr(routes._hub_instance(), "reset_story_sandbox_branch", fake_reset)
    client = TestClient(app)
    res = client.post("/api/story-sandbox/branches/b1/reset", params={"chapter": 8})
    assert res.status_code == 409


def test_story_sandbox_reset_branch_endpoint_404_when_missing(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient
    from api import routes

    async def fake_reset(chapter, branch_id):
        raise ValueError("故事线不存在: b1")

    monkeypatch.setattr(routes._hub_instance(), "reset_story_sandbox_branch", fake_reset)
    client = TestClient(app)
    res = client.post("/api/story-sandbox/branches/b1/reset", params={"chapter": 8})
    assert res.status_code == 404


def test_story_sandbox_message_endpoint_requires_branch_id(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    res = client.post("/api/story-sandbox/message", json={"chapter": 0, "text": "开始"})
    assert res.status_code == 400


def test_story_sandbox_regenerate_endpoint_accepts_chapter_zero(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient
    from api import routes

    calls = []

    async def fake_regenerate(chapter, hint="", branch_id=None):
        calls.append(chapter)

    monkeypatch.setattr(routes._hub_instance(), "regenerate_story_sandbox_suggestions", fake_regenerate)
    client = TestClient(app)
    res = client.post(
        "/api/story-sandbox/suggestions/regenerate", json={"chapter": 0, "branch_id": "b1"},
    )
    assert res.status_code == 200
    assert calls == [0]


def test_story_sandbox_rewrite_endpoint_accepts_chapter_zero(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient
    from api import routes

    calls = []

    async def fake_rewrite(chapter, feedback, branch_id=None):
        calls.append(chapter)

    monkeypatch.setattr(routes._hub_instance(), "start_story_sandbox_rewrite", fake_rewrite)
    client = TestClient(app)
    res = client.post(
        "/api/story-sandbox/rewrite", json={"chapter": 0, "feedback": "反馈", "branch_id": "b1"},
    )
    assert res.status_code == 200
    assert calls == [0]


def test_story_sandbox_rewrite_selection_endpoint_accepts_chapter_zero(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient
    from api import routes

    calls = []

    async def fake_rewrite_selection(chapter, original_text, anchor_offset, feedback, round_id=None, branch_id=None):
        calls.append((chapter, original_text, anchor_offset, feedback, round_id))

    monkeypatch.setattr(
        routes._hub_instance(), "start_story_sandbox_selection_rewrite", fake_rewrite_selection,
    )
    client = TestClient(app)
    res = client.post(
        "/api/story-sandbox/rewrite-selection",
        json={
            "chapter": 0, "original_text": "看向窗外", "anchor_offset": 3, "feedback": "反馈",
            "round_id": "round-1", "branch_id": "b1",
        },
    )
    assert res.status_code == 200
    assert calls == [(0, "看向窗外", 3, "反馈", "round-1")]


def test_story_sandbox_rewrite_selection_endpoint_rejects_blank_original_text():
    from api.hub import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    res = client.post(
        "/api/story-sandbox/rewrite-selection",
        json={"chapter": 0, "original_text": "  ", "anchor_offset": 0, "feedback": "", "branch_id": "b1"},
    )
    assert res.status_code == 400


def test_story_sandbox_rewrite_selection_endpoint_rejects_negative_chapter():
    from api.hub import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    res = client.post(
        "/api/story-sandbox/rewrite-selection",
        json={"chapter": -1, "original_text": "文字", "anchor_offset": 0, "feedback": "", "branch_id": "b1"},
    )
    assert res.status_code == 400


def test_story_sandbox_rewrite_selection_endpoint_returns_409_when_busy(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient
    from api import routes

    async def fake_rewrite_selection(chapter, original_text, anchor_offset, feedback, round_id=None, branch_id=None):
        raise RuntimeError("有任务运行中，无法开始重写")

    monkeypatch.setattr(
        routes._hub_instance(), "start_story_sandbox_selection_rewrite", fake_rewrite_selection,
    )
    client = TestClient(app)
    res = client.post(
        "/api/story-sandbox/rewrite-selection",
        json={"chapter": 0, "original_text": "文字", "anchor_offset": 0, "feedback": "", "branch_id": "b1"},
    )
    assert res.status_code == 409


def test_story_sandbox_cast_archives_empty_names_returns_empty_characters():
    from api.hub import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    res = client.get("/api/story-sandbox/cast-archives?chapter=3")
    assert res.status_code == 200
    assert res.json() == {"characters": []}


def test_story_sandbox_cast_archives_returns_resolved_characters(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient

    async def fake_resolve(chapter: int, names: list[str], novel_id: str) -> list[dict]:
        assert chapter == 3
        assert names == ["甲", "乙"]
        return [{"name": "乙", "role": "role-乙"}, {"name": "甲", "role": "role-甲"}]

    monkeypatch.setattr("engine.story_sandbox.cast.resolve_active_cast_archives", fake_resolve)
    client = TestClient(app)
    res = client.get("/api/story-sandbox/cast-archives?chapter=3&names=甲,乙")
    assert res.status_code == 200
    data = res.json()
    assert [entry["name"] for entry in data["characters"]] == ["乙", "甲"]


def test_story_sandbox_cast_archives_missing_chapter_returns_422():
    from api.hub import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    res = client.get("/api/story-sandbox/cast-archives")
    assert res.status_code == 422


def test_story_sandbox_cast_archives_malformed_chapter_returns_422():
    from api.hub import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    res = client.get("/api/story-sandbox/cast-archives?chapter=abc")
    assert res.status_code == 422


def test_story_sandbox_related_cast_archives_empty_present_returns_empty_characters():
    from api.hub import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    res = client.get("/api/story-sandbox/related-cast-archives?chapter=3")
    assert res.status_code == 200
    assert res.json() == {"characters": []}


def test_story_sandbox_related_cast_archives_returns_resolved_characters(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient

    async def fake_resolve(chapter: int, present: list[str], novel_id: str) -> list[dict]:
        assert chapter == 3
        assert present == ["甲", "乙"]
        return [{"name": "丙", "role": "role-丙"}]

    monkeypatch.setattr("engine.story_sandbox.cast.resolve_related_cast_archives", fake_resolve)
    client = TestClient(app)
    res = client.get("/api/story-sandbox/related-cast-archives?chapter=3&present=甲,乙")
    assert res.status_code == 200
    data = res.json()
    assert [entry["name"] for entry in data["characters"]] == ["丙"]


def test_story_sandbox_related_cast_archives_missing_chapter_returns_422():
    from api.hub import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    res = client.get("/api/story-sandbox/related-cast-archives")
    assert res.status_code == 422


def test_story_sandbox_memory_archive_returns_entries(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient

    def fake_list(chapter: int, branch_id: str | None, origin: str) -> list[dict]:
        assert chapter == 5
        assert branch_id == "b1"
        assert origin == "sandbox"
        return [{"id": "e1", "chapter": 3, "turn_index": 1, "summary": "旧事件"}]

    monkeypatch.setattr("engine.memory_recall.event_log.list_memory_archive", fake_list)
    client = TestClient(app)
    res = client.get("/api/story-sandbox/memory-archive?chapter=5&branch_id=b1")
    assert res.status_code == 200
    assert res.json() == {"entries": [{"id": "e1", "chapter": 3, "turn_index": 1, "summary": "旧事件"}]}


def test_story_sandbox_memory_archive_without_branch_id_passes_none(monkeypatch):
    from api.hub import app
    from fastapi.testclient import TestClient

    def fake_list(chapter: int, branch_id: str | None, origin: str) -> list[dict]:
        assert branch_id is None
        return []

    monkeypatch.setattr("engine.memory_recall.event_log.list_memory_archive", fake_list)
    client = TestClient(app)
    res = client.get("/api/story-sandbox/memory-archive?chapter=1")
    assert res.status_code == 200
    assert res.json() == {"entries": []}


def test_story_sandbox_memory_archive_missing_chapter_returns_422():
    from api.hub import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    res = client.get("/api/story-sandbox/memory-archive")
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_story_sandbox_word_guard_persists_across_turns(monkeypatch):
    """单独一轮"仿佛"不足以触发（阈值 1），但同一 (novel_id, chapter) 下第二轮累计超过阈值后
    应该触发局部重写 -- 证明 guard 跨轮复用，不是每轮清零。"""
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: [])
    monkeypatch.setattr(style_guard_mod, "WORD_THRESHOLDS", {"仿佛": 1})
    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "novel-x")

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    call_n = {"n": 0}
    rewrite_n = {"n": 0}

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            call_n["n"] += 1
            text = "他仿佛笑了。" if call_n["n"] == 1 else "她仿佛也笑了。"
            for ch in text:
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            rewrite_n["n"] += 1
            return _Resp("她似乎也笑了。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        result = await write_turn("system", "packet")
        yield {"type": SandboxStepType.PROSE, "text": result}

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)

    async def fake_broadcast(ev):
        pass

    hub = MessageHub()
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    assert rewrite_n["n"] == 0  # 第一轮仅 1 次，未超阈值
    assert hub._story_sandbox_word_guard("novel-x", 1, "legacy")._counts["仿佛"] == 1  # noqa: SLF001

    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    assert rewrite_n["n"] >= 1  # 第二轮累计超标，触发局部重写


@pytest.mark.asyncio
async def test_story_sandbox_turn_rewrite_prompt_includes_trigger_word(monkeypatch):
    """sandbox 正文流词密度触发的 rewrite ainvoke 应在 user prompt 里带上命中的词。"""
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: [])
    monkeypatch.setattr(style_guard_mod, "WORD_THRESHOLDS", {"仿佛": 0})
    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "novel-x")

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    rewrite_users: list[str] = []

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            for ch in "他仿佛笑了。":
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            rewrite_users.append(msgs[1].content)
            return _Resp("他似乎笑了。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        result = await write_turn("system", "packet")
        yield {"type": SandboxStepType.PROSE, "text": result}

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)

    async def fake_broadcast(ev):
        pass

    hub = MessageHub()
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t

    assert len(rewrite_users) == 1
    assert "「仿佛」" in rewrite_users[0]


@pytest.mark.asyncio
async def test_story_sandbox_word_guard_isolated_per_chapter(monkeypatch):
    """不同 chapter 各自独立计数，互不影响。"""
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: [])
    monkeypatch.setattr(style_guard_mod, "WORD_THRESHOLDS", {"仿佛": 1})
    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "novel-x")

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            for ch in "他仿佛笑了。":
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            return _Resp("她似乎也笑了。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        result = await write_turn("system", "packet")
        yield {"type": SandboxStepType.PROSE, "text": result}

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)

    async def fake_broadcast(ev):
        pass

    hub = MessageHub()
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    await hub.start_story_sandbox_turn(2, "继续")  # 不同章节
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t

    guard_ch1 = hub._story_sandbox_word_guard("novel-x", 1, "legacy")
    guard_ch2 = hub._story_sandbox_word_guard("novel-x", 2, "legacy")
    assert guard_ch1.check("") == []  # 各自只出现 1 次，未过阈值 1
    assert guard_ch2.check("") == []


@pytest.mark.asyncio
async def test_stop_story_sandbox_turn_rolls_back_word_guard(monkeypatch):
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: [])
    monkeypatch.setattr(style_guard_mod, "WORD_THRESHOLDS", {"仿佛": 100})  # 只关心 record 是否回滚，不关心是否触发重写
    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "novel-x")

    started = asyncio.Event()

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            # flush_every defaults to 4; a paragraph break forces an early flush so record runs
            # before we hang mid-stream for the cancel.
            yield _Chunk("他仿佛笑了。\n\n")
            started.set()
            await asyncio.sleep(3600)

        async def ainvoke(self, msgs):
            return type("R", (), {"content": "占位"})()

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        await write_turn("system", "packet")
        yield {"type": SandboxStepType.SUGGESTIONS, "options": []}  # pragma: no cover -- never reached

    async def fake_snapshot_state(novel_id, chapter, branch_id=None):
        return {}

    async def fake_restore_state(novel_id, chapter, values, branch_id=None):
        pass

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)
    monkeypatch.setattr("api.services.message_hub.snapshot_story_sandbox_state", fake_snapshot_state)
    monkeypatch.setattr("api.services.message_hub.restore_story_sandbox_state", fake_restore_state)

    hub = MessageHub()

    async def fake_broadcast(ev):
        pass

    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续")
    await asyncio.wait_for(started.wait(), timeout=1)

    guard = hub._story_sandbox_word_guard("novel-x", 1, "legacy")
    assert guard._counts["仿佛"] == 1  # noqa: SLF001 -- 白盒验证 record 确实发生了

    await hub.stop_story_sandbox_turn(1)

    assert guard._counts["仿佛"] == 0  # noqa: SLF001 -- 白盒验证已回滚


@pytest.mark.asyncio
async def test_story_sandbox_rewrite_does_not_double_count_replaced_round(monkeypatch):
    """turn1 写出含 1 次 "仿佛" 的正文成功落定；rewrite 用新文本（同样含 1 次 "仿佛"）替换它。
    如果旧正文的计数没被撤销，guard 会看到"1(旧,未撤销) + 1(新) = 2"，阈值 1 会被误触发局部重写。
    正确行为是只看到新正文的 1 次，不触发。"""
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: [])
    monkeypatch.setattr(style_guard_mod, "WORD_THRESHOLDS", {"仿佛": 1})
    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "novel-x")

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            for ch in "他仿佛笑了。":  # turn1 和 rewrite 共用同一个 fake LLM，都产出这段含 1 次"仿佛"的文本
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            return _Resp("她似乎也笑了。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        result = await write_turn("system", "packet")
        yield {"type": SandboxStepType.PROSE, "text": result}

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)

    async def fake_rewrite_last_round(novel_id, chapter, feedback, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        async def _gen():
            result = await write_turn("system", "packet")
            yield {"type": SandboxStepType.PROSE, "text": result}
        return _gen()

    monkeypatch.setattr(
        "engine.story_sandbox.graph.rewrite_last_round", fake_rewrite_last_round,
    )

    async def fake_snapshot_state(novel_id, chapter, branch_id=None):
        return {}

    async def fake_restore_state(novel_id, chapter, values, branch_id=None):
        pass

    monkeypatch.setattr("api.services.message_hub.snapshot_story_sandbox_state", fake_snapshot_state)
    monkeypatch.setattr("api.services.message_hub.restore_story_sandbox_state", fake_restore_state)

    hub = MessageHub()
    deltas: list[str] = []

    async def fake_broadcast(ev):
        if ev.get("type") == "story_sandbox_rewrite_token":
            deltas.append(ev["delta"])

    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t

    await hub.start_story_sandbox_rewrite(1, "重写反馈")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t

    rewritten_text = "".join(deltas)
    assert "仿佛" in rewritten_text  # 没有被误判超标改写掉
    assert "似乎" not in rewritten_text  # 没有触发局部重写


@pytest.mark.asyncio
async def test_start_story_sandbox_rewrite_snapshots_pre_state_for_cancel(monkeypatch):
    """既有 bug 顺带修复:重写开始前必须像普通回合一样 snapshot_state，否则取消重写时
    restore_story_sandbox_state 会被传空字典，落到 seed_state() 把整章清空。"""
    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "novel-x")

    snapshot_calls = []

    async def fake_snapshot_state(novel_id, chapter, branch_id=None):
        snapshot_calls.append((novel_id, chapter))
        return {"rolling_summary": "重写前状态"}

    started = asyncio.Event()

    async def fake_rewrite_last_round(novel_id, chapter, feedback, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        async def _gen():
            started.set()
            await asyncio.sleep(3600)
            yield {"type": SandboxStepType.SUGGESTIONS, "options": []}  # pragma: no cover
        return _gen()

    monkeypatch.setattr(
        "engine.story_sandbox.graph.rewrite_last_round", fake_rewrite_last_round,
    )
    monkeypatch.setattr("api.services.message_hub.snapshot_story_sandbox_state", fake_snapshot_state)

    restored = {}

    async def fake_restore_state(novel_id, chapter, values, branch_id=None):
        restored["values"] = values

    monkeypatch.setattr("api.services.message_hub.restore_story_sandbox_state", fake_restore_state)
    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: object())

    hub = MessageHub()

    async def fake_broadcast(ev):
        pass

    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_rewrite(1, "重写反馈")
    await asyncio.wait_for(started.wait(), timeout=1)
    await hub.stop_story_sandbox_turn(1)

    assert snapshot_calls == [("novel-x", 1)]
    assert restored["values"] == {"rolling_summary": "重写前状态"}  # 不是 {} -> 不会被 seed_state() 清空


@pytest.mark.asyncio
async def test_delete_story_sandbox_branch_clears_word_guard_cache(monkeypatch):
    from api.services.message_hub import MessageHub
    from engine.execution.style_guard import WordDensityGuard

    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "novel-x")

    async def fake_reset_chapter(novel_id, chapter, branch_id=None):
        pass

    def fake_delete_branch(chapter, branch_id):
        return {"id": branch_id, "chapter": chapter}

    import engine.story_sandbox.branches as branches_mod
    import engine.story_sandbox.graph as graph_mod
    monkeypatch.setattr(graph_mod, "reset_chapter", fake_reset_chapter)
    monkeypatch.setattr(branches_mod, "delete_branch", fake_delete_branch)

    hub = MessageHub()
    original_guard = WordDensityGuard()
    hub._story_sandbox_word_guards[("novel-x", 1, "branch-1")] = original_guard
    hub._story_sandbox_last_round_word_guard_snapshot[("novel-x", 1, "branch-1")] = original_guard.snapshot()

    await hub.delete_story_sandbox_branch(1, "branch-1")

    assert ("novel-x", 1, "branch-1") not in hub._story_sandbox_word_guards
    assert ("novel-x", 1, "branch-1") not in hub._story_sandbox_last_round_word_guard_snapshot


@pytest.mark.asyncio
async def test_reset_story_sandbox_branch_clears_word_guard_cache(monkeypatch):
    from api.services.message_hub import MessageHub
    from engine.execution.style_guard import WordDensityGuard

    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "novel-x")

    async def fake_reset_chapter(novel_id, chapter, branch_id=None):
        pass

    def fake_touch_branch(chapter, branch_id):
        pass

    def fake_get_branch(chapter, branch_id):
        return {"id": branch_id, "chapter": chapter}

    import engine.story_sandbox.branches as branches_mod
    import engine.story_sandbox.graph as graph_mod
    monkeypatch.setattr(graph_mod, "reset_chapter", fake_reset_chapter)
    monkeypatch.setattr(branches_mod, "touch_branch", fake_touch_branch)
    monkeypatch.setattr(branches_mod, "get_branch", fake_get_branch)

    hub = MessageHub()
    original_guard = WordDensityGuard()
    hub._story_sandbox_word_guards[("novel-x", 1, "branch-1")] = original_guard
    hub._story_sandbox_last_round_word_guard_snapshot[("novel-x", 1, "branch-1")] = original_guard.snapshot()

    await hub.reset_story_sandbox_branch(1, "branch-1")

    assert ("novel-x", 1, "branch-1") not in hub._story_sandbox_word_guards
    assert ("novel-x", 1, "branch-1") not in hub._story_sandbox_last_round_word_guard_snapshot


@pytest.mark.asyncio
async def test_reset_story_sandbox_clears_only_that_novels_word_guard_caches(monkeypatch):
    """reset_story_sandbox(novel_id) is a per-novel operation -- must not wipe another novel's
    word guards just because it happens to share the process-wide cache dict."""
    from api.services.message_hub import MessageHub
    from engine.execution.style_guard import WordDensityGuard

    async def fake_close_checkpointer(novel_id=None):
        pass

    import engine.story_sandbox.graph as graph_mod
    monkeypatch.setattr(graph_mod, "close_checkpointer", fake_close_checkpointer)

    hub = MessageHub()
    hub._story_sandbox_word_guards[("novel-x", 1, "b")] = WordDensityGuard()
    hub._story_sandbox_word_guards[("novel-y", 3, "b")] = WordDensityGuard()

    await hub.reset_story_sandbox("novel-x")

    assert ("novel-x", 1, "b") not in hub._story_sandbox_word_guards
    assert ("novel-y", 3, "b") in hub._story_sandbox_word_guards


@pytest.mark.asyncio
async def test_reset_all_story_sandbox_clears_every_novels_word_guard_caches(monkeypatch):
    from api.services.message_hub import MessageHub
    from engine.execution.style_guard import WordDensityGuard

    async def fake_close_checkpointer(novel_id=None):
        pass

    import engine.story_sandbox.graph as graph_mod
    monkeypatch.setattr(graph_mod, "close_checkpointer", fake_close_checkpointer)

    hub = MessageHub()
    hub._story_sandbox_word_guards[("novel-x", 1, "b")] = WordDensityGuard()
    hub._story_sandbox_word_guards[("novel-y", 3, "b")] = WordDensityGuard()

    await hub.reset_all_story_sandbox()

    assert hub._story_sandbox_word_guards == {}
    assert hub._story_sandbox_last_round_word_guard_snapshot == {}


@pytest.mark.asyncio
async def test_make_guard_text_rewrites_violating_text(monkeypatch):
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub
    from engine.execution.style_guard import WordDensityGuard

    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`"))

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def ainvoke(self, msgs):
            return _Resp("改写后的建议。")

    class _FakeAccountant:
        async def record(self, tin, tout, tcached):
            pass

    hub = MessageHub()
    guard = WordDensityGuard()
    monkeypatch.setattr("llm.factory.get_style_guard_llm", lambda: _FakeLLM())
    guard_text_for, _prompt_logger = hub._make_guard_text(
        chapter=1, word_guard=guard, accountant=_FakeAccountant(),
        sandbox_llm_params={},
    )
    guard_text_fn = guard_text_for("suggest")
    result = await guard_text_fn("他不是喜欢她，而是习惯了。")
    assert result == "改写后的建议。"
    assert await guard_text_fn("一条正常的建议") == "一条正常的建议"


@pytest.mark.asyncio
async def test_make_guard_text_rewrite_prompt_includes_trigger_pattern(monkeypatch):
    """_guard_suggestions 的 rewrite ainvoke 应在 user prompt 里带上命中的句式。"""
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub
    from engine.execution.style_guard import WordDensityGuard

    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`"))

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    rewrite_users: list[str] = []

    class _FakeLLM:
        model = "fake"

        async def ainvoke(self, msgs):
            rewrite_users.append(msgs[1].content)
            return _Resp("改写后的建议。")

    class _FakeAccountant:
        async def record(self, tin, tout, tcached):
            pass

    hub = MessageHub()
    guard = WordDensityGuard()
    monkeypatch.setattr("llm.factory.get_style_guard_llm", lambda: _FakeLLM())
    guard_text_for, _prompt_logger = hub._make_guard_text(
        chapter=1, word_guard=guard, accountant=_FakeAccountant(),
        sandbox_llm_params={},
    )
    guard_text_fn = guard_text_for("suggest")
    await guard_text_fn("他不是喜欢她，而是习惯了。")
    assert len(rewrite_users) == 1
    assert "「不是喜欢她，而是习惯了」" in rewrite_users[0]


@pytest.mark.asyncio
async def test_make_guard_text_shares_word_guard_budget_with_prose(monkeypatch):
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub
    from engine.execution.style_guard import WordDensityGuard

    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: [])

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def ainvoke(self, msgs):
            return _Resp("换个说法。")

    class _FakeAccountant:
        async def record(self, tin, tout, tcached):
            pass

    hub = MessageHub()
    guard = WordDensityGuard(thresholds={"仿佛": 0}, window_chars=1000)
    guard.record("仿佛")  # 模拟正文里已经用过一次
    monkeypatch.setattr("llm.factory.get_style_guard_llm", lambda: _FakeLLM())
    guard_text_for, _prompt_logger = hub._make_guard_text(
        chapter=1, word_guard=guard, accountant=_FakeAccountant(),
        sandbox_llm_params={},
    )
    guard_text_fn = guard_text_for("suggest")
    result = await guard_text_fn("他仿佛也这么想")
    assert "仿佛" not in result


@pytest.mark.asyncio
async def test_make_guard_text_accepts_last_rewrite_when_exhausted(monkeypatch):
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub
    from engine.execution.style_guard import WordDensityGuard

    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`"))

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def ainvoke(self, msgs):
            return _Resp("还是不是喜欢她，而是习惯了。")  # 重写仍然违规

    class _FakeAccountant:
        async def record(self, tin, tout, tcached):
            pass

    hub = MessageHub()
    guard = WordDensityGuard()
    original = "他不是喜欢她，而是习惯了。"
    monkeypatch.setattr("llm.factory.get_style_guard_llm", lambda: _FakeLLM())
    guard_text_for, _prompt_logger = hub._make_guard_text(
        chapter=1, word_guard=guard, accountant=_FakeAccountant(),
        sandbox_llm_params={},
    )
    guard_text_fn = guard_text_for("suggest")
    result = await guard_text_fn(original)
    assert result == "还是不是喜欢她，而是习惯了。"  # 耗尽不再回退，接受最后一次重写产出


@pytest.mark.asyncio
async def test_start_story_sandbox_turn_guards_suggestions(monkeypatch):
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    monkeypatch.setattr(
        style_guard_mod, "get_compiled_patterns",
        lambda: style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`"),
    )
    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "novel-x")

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            for ch in "正文没有违规。":
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            return _Resp("改写后的建议。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        assert callable(guard_text_suggest)
        result = await write_turn("system", "packet")
        yield {"type": SandboxStepType.PROSE, "text": result}
        guarded = await guard_text_suggest("他不是喜欢她，而是习惯了。")
        yield {"type": SandboxStepType.SUGGESTIONS, "options": [guarded]}

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)

    seen = []

    async def fake_broadcast(ev):
        seen.append(ev)

    hub = MessageHub()
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t

    suggestion_events = [e for e in seen if e.get("type") == "story_sandbox_suggestions"]
    assert suggestion_events == [
        {"type": "story_sandbox_suggestions", "options": ["改写后的建议。"], "round_id": None},
    ]


@pytest.mark.asyncio
async def test_start_story_sandbox_rewrite_guards_suggestions(monkeypatch):
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub
    from engine.story_sandbox.state import SandboxStepType

    monkeypatch.setattr(
        style_guard_mod, "get_compiled_patterns",
        lambda: style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`"),
    )
    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "novel-x")

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def astream(self, msgs, stream_usage=False):
            for ch in "重写正文没有违规。":
                yield _Chunk(ch)

        async def ainvoke(self, msgs):
            return _Resp("改写后的建议。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    async def fake_rewrite_last_round(novel_id, chapter, feedback, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        assert callable(guard_text_suggest)

        async def _gen():
            result = await write_turn("system", "packet")
            yield {"type": SandboxStepType.PROSE, "text": result}
            guarded = await guard_text_suggest("他不是喜欢她，而是习惯了。")
            yield {"type": SandboxStepType.SUGGESTIONS, "options": [guarded]}
        return _gen()

    monkeypatch.setattr("engine.story_sandbox.graph.rewrite_last_round", fake_rewrite_last_round)

    async def fake_snapshot_state(novel_id, chapter, branch_id=None):
        return {}

    async def fake_restore_state(novel_id, chapter, values, branch_id=None):
        pass

    monkeypatch.setattr("api.services.message_hub.snapshot_story_sandbox_state", fake_snapshot_state)
    monkeypatch.setattr("api.services.message_hub.restore_story_sandbox_state", fake_restore_state)

    hub = MessageHub()
    seen = []

    async def fake_broadcast(ev):
        seen.append(ev)

    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_rewrite(1, "重写反馈")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t

    suggestion_events = [e for e in seen if e.get("type") == "story_sandbox_suggestions"]
    assert suggestion_events == [
        {"type": "story_sandbox_suggestions", "options": ["改写后的建议。"]},
    ]
    done_events = [e for e in seen if e.get("type") == "story_sandbox_rewrite_done"]
    assert done_events[0]["suggestions"] == ["改写后的建议。"]  # final_suggestions 也是被 guard 过的版本


@pytest.mark.asyncio
async def test_regenerate_story_sandbox_suggestions_guards_result(monkeypatch):
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub

    monkeypatch.setattr(
        style_guard_mod, "get_compiled_patterns",
        lambda: style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`"),
    )
    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "novel-x")

    async def fake_regenerate(novel_id, chapter, call_llm, *, guard_text, hint="", run_skill_agent=None, branch_id=None):
        assert callable(guard_text)
        raw = ["他不是喜欢她，而是习惯了。", "一条正常的建议"]
        return [await guard_text(s) for s in raw]

    monkeypatch.setattr("engine.story_sandbox.graph.regenerate_suggestions", fake_regenerate)

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def ainvoke(self, msgs):
            return _Resp("改写后的建议。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    hub = MessageHub()
    seen = []

    async def fake_broadcast(ev):
        seen.append(ev)

    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    await hub.regenerate_story_sandbox_suggestions(3)
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    regenerated = [ev for ev in seen if ev["type"] == "story_sandbox_suggestions_regenerated"]
    assert regenerated == [{
        "type": "story_sandbox_suggestions_regenerated",
        "options": ["改写后的建议。", "一条正常的建议"],
    }]


@pytest.mark.asyncio
async def test_regenerate_story_sandbox_suggestions_uses_persistent_word_guard(monkeypatch):
    """确认这条此前完全没有 word_guard 的路径，现在正确取用了跟正文共享的持久化实例。"""
    import engine.execution.style_guard as style_guard_mod
    from api.services.message_hub import MessageHub

    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: [])
    monkeypatch.setattr("api.services.message_hub.active_novel_id", lambda: "novel-x")

    async def fake_regenerate(novel_id, chapter, call_llm, *, guard_text, hint="", run_skill_agent=None, branch_id=None):
        assert callable(guard_text)
        return [await guard_text("他仿佛也这么想")]

    monkeypatch.setattr("engine.story_sandbox.graph.regenerate_suggestions", fake_regenerate)

    class _Resp:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        model = "fake"

        async def ainvoke(self, msgs):
            return _Resp("换个说法。")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())

    hub = MessageHub()
    guard = hub._story_sandbox_word_guard("novel-x", 3, "legacy")
    guard._thresholds["仿佛"] = 0  # noqa: SLF001 -- 白盒注入一个必超标的阈值，逼出重写
    seen = []

    async def fake_broadcast(ev):
        seen.append(ev)

    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    await hub.regenerate_story_sandbox_suggestions(3)
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    regenerated = [ev for ev in seen if ev["type"] == "story_sandbox_suggestions_regenerated"]
    assert len(regenerated) == 1
    assert "仿佛" not in regenerated[0]["options"][0]


@pytest.mark.asyncio
async def test_start_story_sandbox_turn_records_node_override_model_in_ledger(monkeypatch, tmp_path):
    """A node configured with provider=local must have ITS OWN model name recorded in the
    ledger, not the outer cloud model -- otherwise switching a node to local LMStudio would
    silently misattribute its token usage to the cloud model in stats/logs."""
    from langchain_core.messages import AIMessage

    class _FakeCloudLLM:
        model = "cloud-model"

        def bind(self, **kwargs):
            return self

        async def ainvoke(self, messages):
            raise AssertionError("derive_char must not call the cloud client once overridden to local")

    class _FakeLocalLLM:
        model = "local-model"

        def bind(self, **kwargs):
            return self

        async def ainvoke(self, messages):
            return AIMessage(
                content="{}",
                usage_metadata={
                    "input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                    "input_token_details": {},
                },
            )

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeCloudLLM())
    monkeypatch.setattr("llm.factory.get_node_local_llm", lambda base_url, model: _FakeLocalLLM())
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"sandbox_llm_params": {
            "derive_char": {
                "provider": "local", "base_url": "http://localhost:1234/v1", "model": "local-model",
            },
        }},
    )
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "default")
    (tmp_path / "default").mkdir()

    hub = MessageHub()
    captured = {}

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        captured["call_llm_derive_char"] = call_llm_derive_char
        yield {"type": SandboxStepType.SUGGESTIONS, "options": []}

    async def fake_broadcast(ev):
        pass

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t

    await captured["call_llm_derive_char"]("system", "user")

    from api.services import token_ledger
    ledger = token_ledger.load_ledger()
    cell = ledger["story_sandbox"]["1"]
    assert cell["tokens_in"] == 10
    assert cell["model"] == "local-model"


@pytest.mark.asyncio
async def test_start_story_sandbox_turn_disable_style_guard_bypasses_short_field_guard(monkeypatch, tmp_path):
    """A node configured with disable_style_guard=True must skip guard_text entirely for that
    node -- banned-pattern text passes through unmodified and the rewrite LLM is never called."""
    import engine.execution.style_guard as style_guard_mod

    patterns = style_guard_mod.compile_negative_patterns("- `不是【】，而是【】`")
    monkeypatch.setattr(style_guard_mod, "get_compiled_patterns", lambda: patterns)

    class _FakeLLM:
        model = "fake"

        def bind(self, **kwargs):
            return self

        async def ainvoke(self, messages):
            raise AssertionError("rewrite LLM must not be called when disable_style_guard is set")

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: _FakeLLM())
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"sandbox_llm_params": {"derive_char": {"disable_style_guard": True}}},
    )
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "default")
    (tmp_path / "default").mkdir()

    hub = MessageHub()
    captured = {}

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        captured["guard_text_derive_char"] = guard_text_derive_char
        yield {"type": SandboxStepType.SUGGESTIONS, "options": []}

    async def fake_broadcast(ev):
        pass

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t

    violating = "他不是喜欢她，而是习惯了。"
    result = await captured["guard_text_derive_char"](violating)
    assert result == violating  # unmodified -- guard bypassed entirely


@pytest.mark.asyncio
async def test_start_story_sandbox_turn_broadcasts_recalled_settings(monkeypatch):
    hub = MessageHub()
    seen = []

    async def fake_run_turn(novel_id, chapter, text, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, submitted_directions=None, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        yield {
            "type": SandboxStepType.PROSE, "text": "定稿正文",
            "recall_context": "## 相关历史/设定回收\n- 【蛊虫】寄生方式驱动力量",
            "recalled_settings": [{"category": "power_system", "name": "蛊虫", "desc": "寄生方式驱动力量"}],
        }

    async def fake_broadcast(ev):
        seen.append(ev)

    monkeypatch.setattr("api.services.message_hub.run_story_sandbox_turn", fake_run_turn)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_turn(1, "继续")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    assert {
        "type": "story_sandbox_recall_context",
        "recall_context": "## 相关历史/设定回收\n- 【蛊虫】寄生方式驱动力量",
        "recalled_settings": [{"category": "power_system", "name": "蛊虫", "desc": "寄生方式驱动力量"}],
    } in seen


@pytest.mark.asyncio
async def test_start_story_sandbox_rewrite_bundles_recalled_settings_into_done(monkeypatch):
    hub = MessageHub()
    seen = []

    async def fake_rewrite_last_round(novel_id, chapter, feedback, *, write_turn, call_llm_derive_char, call_llm_derive_scene, call_llm_summary_fold, call_llm_event_extract, call_llm_profile_mutate, call_llm_suggest, guard_text_derive_char, guard_text_derive_scene, guard_text_summary_fold, guard_text_event_extract, guard_text_profile_mutate, guard_text_suggest, call_llm_identify=None, call_llm_dialogue_draft=None, branch_id=None):
        async def _gen():
            yield {
                "type": SandboxStepType.PROSE, "text": "重写后的正文",
                "initial_states": None, "initial_scene_state": None,
                "recalled_settings": [{"category": "races", "name": "人族", "desc": "凡躯"}],
            }
            yield {"type": SandboxStepType.STATE, "states": {}, "scene_state": {}}
            yield {"type": SandboxStepType.SUGGESTIONS, "options": []}
        return _gen()

    async def fake_broadcast(ev):
        seen.append(ev)

    monkeypatch.setattr(
        "engine.story_sandbox.graph.rewrite_last_round", fake_rewrite_last_round,
    )
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)

    await hub.start_story_sandbox_rewrite(1, "反馈")
    if (_t := hub._story_sandbox_tasks.get(mh_mod.active_novel_id())) is not None:
        await _t
    done = next(e for e in seen if e["type"] == "story_sandbox_rewrite_done")
    assert done["recalled_settings"] == [{"category": "races", "name": "人族", "desc": "凡躯"}]
