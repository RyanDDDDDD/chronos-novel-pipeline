"""Per-turn tool routing: narrows which tool schemas are bound to the LLM's
function-calling call this turn. Two branches -- deterministic (a pipeline focus
is known) or semantic (free-form, vector similarity against the latest user
message). See
docs/superpowers/specs/2026-07-19-setup-chat-plan-execute-tool-routing-design.md."""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

CORE_TOOL_NAMES: frozenset[str] = frozenset({
    "present_choices", "load_skill", "read_setup_summary", "rename_novel_title",
})

TOP_K = 8

_TOOL_VECTORS_CACHE_DOC_KEY = "tool_vectors_cache"


def _tool_vectors_cache_key(texts: list[str], model_name: str) -> str:
    import hashlib

    payload = model_name + "\n" + "\n".join(texts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _world_focus_tool_names() -> frozenset[str] | None:
    from engine.setup_chat import world_pipeline
    from engine.setup_chat.construction_plan import TaskKind
    from engine.setup_chat.mode import is_auto_mode

    chain = world_pipeline.active_chain() or world_pipeline.next_focus()
    if chain is None:
        return None
    if chain.missing_timeline_chapters:
        return frozenset({"write_character_archive"})
    if chain.missing_stages:
        return frozenset(chain.missing_stages[0].tools)
    if chain.target.kind == TaskKind.WORLD and is_auto_mode():
        # AUTO mode + world not built yet -- steer toward the one-shot construction tool
        # instead of the interactive construct_world (see plan_runner.gate_tool_call for the
        # execution-time backstop against construct_world still somehow getting called).
        return frozenset({"auto_build_setup"})
    return frozenset(chain.target.tools)


def _skeleton_focus_tool_names() -> frozenset[str] | None:
    from engine.setup_chat import skeleton_pipeline
    from engine.setup_chat.mode import is_auto_mode

    chain = skeleton_pipeline.active_chain() or skeleton_pipeline.next_focus()
    if chain is None:
        return None
    if chain.missing_timeline_chars:
        return frozenset({"write_character_archive"})
    if is_auto_mode() and skeleton_pipeline.chapter_remaining_stage_nums(chain.chapter):
        # AUTO mode + this chapter still has at least one stage left to expand -- steer toward
        # the one-shot resumable tool instead of the interactive phase tools (see
        # plan_runner.gate_tool_call for the execution-time backstop). Covers both a virgin
        # chapter (nothing done yet) and one with partial manual progress from before an
        # in-turn switch into AUTO -- the latter used to fall through to the interactive tools
        # unchanged, letting the ReAct loop try to plow through the remaining stages one tool
        # call at a time and blow the recursion limit on large chapters.
        return frozenset({"auto_expand_skeleton"})
    phase = chain.missing[0] if chain.missing else chain.target
    return frozenset({skeleton_pipeline._PHASE_TOOLS[phase]})


def _pipeline_focus_tool_names() -> frozenset[str] | None:
    """world_pipeline checked first -- skeleton work depends on plot existing,
    which is a world_pipeline stage, so skeleton_pipeline is only consulted once
    world_pipeline reports no focus at all."""
    return _world_focus_tool_names() or _skeleton_focus_tool_names()


def build_tool_vectors(all_tools: list["BaseTool"]) -> dict[str, list[float]]:
    """Process-lifetime input, cached to disk (see docs/superpowers/specs/2026-08-09-tool-
    vector-cache-persistence-design.md): the ~70 tool name+description texts are fixed by
    the current code version (not derived from novel content), so re-embedding them on every
    process restart recomputes an identical result -- verified as the single largest
    contributor to startup RSS (ONNX Runtime batches unequal-length texts padded to the
    batch's longest sequence, permanently allocating memory it never returns to the OS).
    A disk-persisted cache keyed by a hash of (model name + tool texts) turns every restart
    after the first into a cheap read instead of a ~1.3GB recompute."""
    from rag.embedding import get_embedding_function
    from repositories.sqlite_store import SqliteStore
    from utils.paths import active_novel_id

    embed = get_embedding_function()
    names = [t.name for t in all_tools]
    texts = [f"{t.name}: {t.description}" for t in all_tools]
    cache_key = _tool_vectors_cache_key(texts, embed.model_name)

    store = SqliteStore(active_novel_id())
    cached = store.get_doc(_TOOL_VECTORS_CACHE_DOC_KEY, "")
    if isinstance(cached, dict) and cached.get("hash") == cache_key:
        vectors_by_name = cached.get("vectors")
        if isinstance(vectors_by_name, dict) and all(n in vectors_by_name for n in names):
            return {n: vectors_by_name[n] for n in names}

    vectors = embed(texts)
    result = dict(zip(names, vectors, strict=True))
    store.save_doc(_TOOL_VECTORS_CACHE_DOC_KEY, "", {"hash": cache_key, "vectors": result})
    return result


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)  # type: ignore[no-any-return]


def _vector_top_k(
    user_text: str,
    all_tools: list["BaseTool"],
    *,
    embed_fn: Callable[[list[str]], list[list[float]]],
    tool_vectors: dict[str, list[float]],
) -> set[str]:
    query_vec = embed_fn([user_text])[0]
    scored = sorted(
        (
            (_cosine(query_vec, tool_vectors[t.name]), t.name)
            for t in all_tools if t.name in tool_vectors
        ),
        key=lambda pair: pair[0], reverse=True,
    )
    return {name for _, name in scored[:TOP_K]}


def route_tool_names(
    user_text: str,
    all_tools: list["BaseTool"],
    *,
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
    tool_vectors: dict[str, list[float]] | None = None,
) -> set[str]:
    """Returns the tool names to bind this turn. Production callers (agent.py)
    pass the real bge-small-zh embed_fn (rag.embedding.get_embedding_function())
    and the precomputed build_tool_vectors() result; tests inject fakes. Any
    routing failure (embed_fn missing/raising) falls back to the full tool list --
    routing must never block the conversation."""
    focus = _pipeline_focus_tool_names()
    if focus is not None:
        return set(focus) | set(CORE_TOOL_NAMES)

    if embed_fn is None or tool_vectors is None:
        return {t.name for t in all_tools}
    try:
        top = _vector_top_k(user_text, all_tools, embed_fn=embed_fn, tool_vectors=tool_vectors)
    except Exception:  # noqa: BLE001 -- routing failure must never block the turn
        return {t.name for t in all_tools}
    return top | set(CORE_TOOL_NAMES)
