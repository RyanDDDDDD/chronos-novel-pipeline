"""Tests for tool_router pipeline-focus and vector branches."""
from unittest.mock import MagicMock

import engine.setup_chat.tool_router as tr
import engine.setup_chat.world_pipeline as wp


def _fake_tool(name: str, description: str = "") -> MagicMock:
    t = MagicMock()
    t.name = name
    t.description = description or name
    return t


def _unit_vec(hot_index: int, dim: int = 4) -> list[float]:
    v = [0.0] * dim
    v[hot_index] = 1.0
    return v


def test_world_pipeline_focus_routes_target_tools(monkeypatch):
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: False)
    names = tr.route_tool_names("随便说点什么", all_tools=[])
    assert "set_world_background" in names
    assert tr.CORE_TOOL_NAMES <= names


def test_world_pipeline_reactive_block_routes_missing_stage_not_target(monkeypatch):
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: False)
    wp.gate(wp.resolve_chain("add_character", {"given_name": "甲"}))
    try:
        names = tr.route_tool_names("建角色", all_tools=[])
        assert "set_world_background" in names  # missing stage (world), not target (character)
        assert "add_character" not in names
    finally:
        wp._ACTIVE_TARGET = None


def test_world_pipeline_timeline_missing_chapters_routes_write_character_archive(monkeypatch):
    """Reactive block with missing_timeline_chapters must route to
    write_character_archive (the actual unblocking action), not the target
    stage's own tool."""
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: stage.kind != "timeline")
    monkeypatch.setattr("engine.setup_chat.plan_runner._missing_prior_timeline_chapters",
                        lambda ch: [1])
    monkeypatch.setattr("engine.setup_chat.construction_plan._plot_chapters", lambda: {1, 2})
    wp.gate(wp.resolve_chain("write_character_archive", {"chapter": 2, "name": "甲"}))
    try:
        names = tr.route_tool_names("推进度", all_tools=[])
        assert names == {"write_character_archive"} | tr.CORE_TOOL_NAMES
    finally:
        wp._ACTIVE_TARGET = None


def test_skeleton_pipeline_focus_routes_phase_tool(monkeypatch):
    import engine.setup_chat.skeleton_pipeline as sp
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: True)
    monkeypatch.setattr("engine.setup_chat.plan_runner._chapter_timeline_done", lambda ch: True)
    monkeypatch.setattr(sp, "_ACTIVE_CHAPTER", 2)
    sp._DIRECTION_SET.discard(2)
    try:
        names = tr.route_tool_names("扩写", all_tools=[])
        assert names == {"set_chapter_direction"} | tr.CORE_TOOL_NAMES
    finally:
        sp._DIRECTION_SET.discard(2)


def test_world_pipeline_checked_before_skeleton_pipeline(monkeypatch):
    import engine.setup_chat.skeleton_pipeline as sp
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: False)
    monkeypatch.setattr(sp, "_ACTIVE_CHAPTER", 2)  # would also have a focus, but world wins
    sp._DIRECTION_SET.discard(2)
    try:
        names = tr.route_tool_names("随便", all_tools=[])
        assert "set_world_background" in names
        assert "set_chapter_direction" not in names
    finally:
        sp._DIRECTION_SET.discard(2)


def test_vector_branch_returns_top_k_plus_core(monkeypatch):
    import engine.setup_chat.skeleton_pipeline as sp

    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: True)
    monkeypatch.setattr("engine.setup_chat.plan_runner._chapter_timeline_done", lambda ch: True)
    monkeypatch.setattr(sp, "_ACTIVE_CHAPTER", None)

    tools = [_fake_tool(f"tool_{i}") for i in range(4)]
    vectors = {t.name: _unit_vec(i) for i, t in enumerate(tools)}

    def fake_embed(texts: list[str]) -> list[list[float]]:
        assert texts == ["查一下资料"]
        return [_unit_vec(2)]  # closest to tool_2

    names = tr.route_tool_names(
        "查一下资料", tools, embed_fn=fake_embed, tool_vectors=vectors,
    )
    assert "tool_2" in names
    assert tr.CORE_TOOL_NAMES <= names
    assert len(names - tr.CORE_TOOL_NAMES) <= tr.TOP_K


def test_vector_branch_fallback_returns_all_tools_on_embed_error(monkeypatch):
    import engine.setup_chat.skeleton_pipeline as sp

    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: True)
    monkeypatch.setattr("engine.setup_chat.plan_runner._chapter_timeline_done", lambda ch: True)
    monkeypatch.setattr(sp, "_ACTIVE_CHAPTER", None)

    tools = [_fake_tool("a"), _fake_tool("b")]

    def broken_embed(texts: list[str]) -> list[list[float]]:
        raise RuntimeError("model not loaded")

    names = tr.route_tool_names("随便", tools, embed_fn=broken_embed, tool_vectors={})
    assert names == {"a", "b"}


def test_pipeline_focus_branch_never_calls_embed_fn(monkeypatch):
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: False)
    called = []
    tools = [_fake_tool("tool_0")]
    vectors = {"tool_0": _unit_vec(0)}
    tr.route_tool_names(
        "随便", tools,
        embed_fn=lambda texts: called.append(texts) or [[0.0]],
        tool_vectors=vectors,
    )
    assert called == []


def test_build_tool_vectors_calls_embed_once_per_tool_list(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n1")
    calls = []

    class _FakeEmbedFn:
        model_name = "fake-model"

        def __call__(self, texts: list[str]) -> list[list[float]]:
            calls.append(texts)
            return [[float(i)] for i in range(len(texts))]

    monkeypatch.setattr(
        "rag.embedding.get_embedding_function", lambda: _FakeEmbedFn(),
    )
    tools = [_fake_tool("x", "does x"), _fake_tool("y", "does y")]
    vectors = tr.build_tool_vectors(tools)
    assert set(vectors) == {"x", "y"}
    assert len(calls) == 1 and len(calls[0]) == 2


def test_build_tool_vectors_second_call_hits_disk_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n1")
    calls = []

    class _FakeEmbedFn:
        model_name = "fake-model"

        def __call__(self, texts: list[str]) -> list[list[float]]:
            calls.append(texts)
            return [[float(i)] for i in range(len(texts))]

    monkeypatch.setattr("rag.embedding.get_embedding_function", lambda: _FakeEmbedFn())
    tools = [_fake_tool("x", "does x"), _fake_tool("y", "does y")]

    first = tr.build_tool_vectors(tools)
    second = tr.build_tool_vectors(tools)

    assert len(calls) == 1  # embed only ran once -- second call hit the disk cache
    assert first == second


def test_build_tool_vectors_recomputes_when_tool_text_changes(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n1")
    calls = []

    class _FakeEmbedFn:
        model_name = "fake-model"

        def __call__(self, texts: list[str]) -> list[list[float]]:
            calls.append(texts)
            return [[float(i)] for i in range(len(texts))]

    monkeypatch.setattr("rag.embedding.get_embedding_function", lambda: _FakeEmbedFn())

    tr.build_tool_vectors([_fake_tool("x", "does x"), _fake_tool("y", "does y")])
    tr.build_tool_vectors([_fake_tool("x", "does x DIFFERENTLY"), _fake_tool("y", "does y")])

    assert len(calls) == 2  # description changed -> cache key changed -> recomputed

    # a third call with the same (changed) tool set as the second call should now hit cache
    tr.build_tool_vectors([_fake_tool("x", "does x DIFFERENTLY"), _fake_tool("y", "does y")])
    assert len(calls) == 2


def test_build_tool_vectors_recomputes_when_model_name_changes(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n1")
    calls = []

    class _FakeEmbedFn:
        def __init__(self, model_name):
            self.model_name = model_name

        def __call__(self, texts: list[str]) -> list[list[float]]:
            calls.append(texts)
            return [[float(i)] for i in range(len(texts))]

    tools = [_fake_tool("x", "does x"), _fake_tool("y", "does y")]

    monkeypatch.setattr("rag.embedding.get_embedding_function", lambda: _FakeEmbedFn("model-a"))
    tr.build_tool_vectors(tools)
    monkeypatch.setattr("rag.embedding.get_embedding_function", lambda: _FakeEmbedFn("model-b"))
    tr.build_tool_vectors(tools)

    assert len(calls) == 2  # same tools, different model identity -> cache key changed


def test_build_tool_vectors_caches_are_isolated_per_novel(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    calls = []

    class _FakeEmbedFn:
        model_name = "fake-model"

        def __call__(self, texts: list[str]) -> list[list[float]]:
            calls.append(texts)
            return [[float(i)] for i in range(len(texts))]

    monkeypatch.setattr("rag.embedding.get_embedding_function", lambda: _FakeEmbedFn())
    tools = [_fake_tool("x", "does x")]

    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "novel-1")
    tr.build_tool_vectors(tools)
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "novel-2")
    tr.build_tool_vectors(tools)

    assert len(calls) == 2  # each novel's chronos.sqlite3 has its own cache, no cross-novel hit


def test_build_tool_vectors_treats_malformed_cache_doc_as_a_miss(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n1")

    class _FakeEmbedFn:
        model_name = "fake-model"

        def __call__(self, texts: list[str]) -> list[list[float]]:
            return [[float(i)] for i in range(len(texts))]

    monkeypatch.setattr("rag.embedding.get_embedding_function", lambda: _FakeEmbedFn())

    from repositories.sqlite_store import SqliteStore
    store = SqliteStore("n1")
    store.save_doc(tr._TOOL_VECTORS_CACHE_DOC_KEY, "", {"hash": "some-hash", "vectors": {"x": None}})

    tools = [_fake_tool("x", "does x")]
    vectors = tr.build_tool_vectors(tools)  # must not raise despite the malformed prior cache
    assert set(vectors) == {"x"}


def test_core_tool_names_includes_rename_novel_title():
    assert "rename_novel_title" in tr.CORE_TOOL_NAMES


def test_world_focus_returns_auto_build_setup_when_auto_mode_and_world_missing(monkeypatch):
    from engine.setup_chat.construction_plan import TaskKind

    fake_stage = type("S", (), {"kind": TaskKind.WORLD, "tools": frozenset({"construct_world"})})()
    fake_chain = type("C", (), {
        "target": fake_stage, "missing_stages": [], "missing_timeline_chapters": [],
    })()
    monkeypatch.setattr("engine.setup_chat.world_pipeline.active_chain", lambda: None)
    monkeypatch.setattr("engine.setup_chat.world_pipeline.next_focus", lambda: fake_chain)
    monkeypatch.setattr("engine.setup_chat.mode.is_auto_mode", lambda: True)

    assert tr._world_focus_tool_names() == frozenset({"auto_build_setup"})


def test_world_focus_keeps_world_tools_in_manual_mode(monkeypatch):
    from engine.setup_chat.construction_plan import TaskKind
    from engine.setup_chat.world_tools import WORLD_PIPELINE_TOOL_NAMES

    fake_stage = type("S", (), {"kind": TaskKind.WORLD, "tools": WORLD_PIPELINE_TOOL_NAMES})()
    fake_chain = type("C", (), {
        "target": fake_stage, "missing_stages": [], "missing_timeline_chapters": [],
    })()
    monkeypatch.setattr("engine.setup_chat.world_pipeline.active_chain", lambda: None)
    monkeypatch.setattr("engine.setup_chat.world_pipeline.next_focus", lambda: fake_chain)
    monkeypatch.setattr("engine.setup_chat.mode.is_auto_mode", lambda: False)

    assert tr._world_focus_tool_names() == WORLD_PIPELINE_TOOL_NAMES


def test_skeleton_focus_returns_auto_expand_when_auto_mode_and_chapter_virgin(monkeypatch):
    from engine.setup_chat.skeleton_pipeline import SkeletonPhase

    fake_chain = type("C", (), {
        "chapter": 3, "stage_num": None, "target": SkeletonPhase.DIRECTION, "missing": [],
        "missing_timeline_chars": [],
    })()
    monkeypatch.setattr("engine.setup_chat.skeleton_pipeline.active_chain", lambda: None)
    monkeypatch.setattr("engine.setup_chat.skeleton_pipeline.next_focus", lambda: fake_chain)
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_pipeline.chapter_remaining_stage_nums", lambda ch: [1, 2],
    )
    monkeypatch.setattr("engine.setup_chat.mode.is_auto_mode", lambda: True)

    assert tr._skeleton_focus_tool_names() == frozenset({"auto_expand_skeleton"})


def test_skeleton_focus_returns_auto_expand_when_auto_mode_and_chapter_has_partial_progress(
    monkeypatch,
):
    """A chapter with some stages already manually expanded (e.g. the user switched into AUTO
    mid-chapter) must still steer toward the resumable auto tool, not the interactive one --
    otherwise the ReAct loop tries to plow through the remaining stages one tool call at a time
    and can blow the recursion limit on large chapters."""
    from engine.setup_chat.skeleton_pipeline import SkeletonPhase

    fake_chain = type("C", (), {
        "chapter": 3, "stage_num": 2, "target": SkeletonPhase.LENS, "missing": [],
        "missing_timeline_chars": [],
    })()
    monkeypatch.setattr("engine.setup_chat.skeleton_pipeline.active_chain", lambda: None)
    monkeypatch.setattr("engine.setup_chat.skeleton_pipeline.next_focus", lambda: fake_chain)
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_pipeline.chapter_remaining_stage_nums", lambda ch: [2],
    )
    monkeypatch.setattr("engine.setup_chat.mode.is_auto_mode", lambda: True)

    assert tr._skeleton_focus_tool_names() == frozenset({"auto_expand_skeleton"})


def test_skeleton_focus_keeps_set_chapter_direction_when_chapter_fully_expanded(monkeypatch):
    """No stage left to expand at all -- AUTO mode has nothing to steer toward, falls through to
    the normal interactive phase tool (which the chain resolves to target=DIRECTION here only as
    a stand-in; in practice next_focus() would return None for a fully-expanded chapter, this
    just isolates the "no remaining stages" branch)."""
    from engine.setup_chat.skeleton_pipeline import SkeletonPhase

    fake_chain = type("C", (), {
        "chapter": 3, "stage_num": None, "target": SkeletonPhase.DIRECTION, "missing": [],
        "missing_timeline_chars": [],
    })()
    monkeypatch.setattr("engine.setup_chat.skeleton_pipeline.active_chain", lambda: None)
    monkeypatch.setattr("engine.setup_chat.skeleton_pipeline.next_focus", lambda: fake_chain)
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_pipeline.chapter_remaining_stage_nums", lambda ch: [],
    )
    monkeypatch.setattr("engine.setup_chat.mode.is_auto_mode", lambda: True)

    assert tr._skeleton_focus_tool_names() == frozenset({"set_chapter_direction"})


def test_skeleton_focus_keeps_set_chapter_direction_in_manual_mode(monkeypatch):
    from engine.setup_chat.skeleton_pipeline import SkeletonPhase

    fake_chain = type("C", (), {
        "chapter": 3, "stage_num": None, "target": SkeletonPhase.DIRECTION, "missing": [],
        "missing_timeline_chars": [],
    })()
    monkeypatch.setattr("engine.setup_chat.skeleton_pipeline.active_chain", lambda: None)
    monkeypatch.setattr("engine.setup_chat.skeleton_pipeline.next_focus", lambda: fake_chain)
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_pipeline.chapter_remaining_stage_nums", lambda ch: [1],
    )
    monkeypatch.setattr("engine.setup_chat.mode.is_auto_mode", lambda: False)

    assert tr._skeleton_focus_tool_names() == frozenset({"set_chapter_direction"})
