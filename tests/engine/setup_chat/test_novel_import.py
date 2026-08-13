import asyncio

import httpx
import openai
import pytest
from engine.setup_chat.novel_import import (
    ChunkMapError,
    TextChunk,
    chunk_text,
    map_chunk,
    reduce_chunks,
    run_map_stage,
    run_novel_import_pipeline,
    split_fine_grained,
)
from repositories.entities import ResearchChunk


def _rate_limit_error() -> openai.RateLimitError:
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(429, request=request)
    return openai.RateLimitError("rate limited", response=response, body=None)


class _FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    async def ainvoke(self, messages):
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return type("R", (), {"content": resp})()


def test_chunk_text_splits_on_paragraph_boundary_not_mid_line():
    text = "第一段。" * 20 + "\n" + "第二段。" * 20 + "\n" + "第三段。" * 20
    chunks = chunk_text(text, chunk_size=len("第一段。" * 20) + 5)
    assert all(
        c.text.strip() == "" or not c.text.rstrip("\n").endswith("第一段")
        for c in chunks
    )


def test_chunk_text_assigns_sequential_index_from_zero():
    text = "\n".join(["段落" + str(i) for i in range(50)])
    chunks = chunk_text(text, chunk_size=20)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_chunk_text_short_input_returns_single_chunk():
    chunks = chunk_text("很短的文本", chunk_size=10000)
    assert len(chunks) == 1
    assert chunks[0].index == 0


def test_chunk_text_empty_input_returns_empty_list():
    assert chunk_text("", chunk_size=10000) == []


@pytest.mark.asyncio
async def test_map_chunk_parses_structured_json():
    llm = _FakeLLM([
        '{"world": ["设定A"], "characters": [{"name": "甲", "personality": "冷静", '
        '"verbal_tic": "口头禅X"}], "plot": ["事件1"]}',
    ])
    result = await map_chunk(TextChunk(index=0, text="正文……"), llm=llm)
    assert result["world"] == ["设定A"]
    assert result["characters"][0]["name"] == "甲"


class _CapturingLLM:
    def __init__(self, response: str):
        self._response = response
        self.captured_system: str | None = None

    async def ainvoke(self, messages):
        self.captured_system = messages[0].content
        return type("R", (), {"content": self._response})()


@pytest.mark.asyncio
async def test_map_chunk_includes_context_in_system_prompt_when_provided():
    llm = _CapturingLLM('{"world": [], "characters": [], "plot": []}')
    await map_chunk(
        TextChunk(index=1, text="正文"), llm=llm,
        context='{"world": ["设定A"], "characters": [], "plot": []}',
    )
    assert "设定A" in llm.captured_system


@pytest.mark.asyncio
async def test_map_chunk_omits_context_preamble_when_context_empty():
    llm = _CapturingLLM('{"world": [], "characters": [], "plot": []}')
    await map_chunk(TextChunk(index=0, text="正文"), llm=llm)
    assert "已知设定" not in llm.captured_system


@pytest.mark.asyncio
async def test_map_chunk_retries_up_to_two_times_then_succeeds():
    llm = _FakeLLM([
        RuntimeError("网络错误"),
        RuntimeError("网络错误"),
        '{"world": [], "characters": [], "plot": []}',
    ])
    result = await map_chunk(TextChunk(index=1, text="x"), llm=llm)
    assert result == {"world": [], "characters": [], "plot": []}


@pytest.mark.asyncio
async def test_map_chunk_raises_chunk_map_error_after_exhausting_retries():
    llm = _FakeLLM([RuntimeError("a"), RuntimeError("b"), RuntimeError("c")])
    with pytest.raises(ChunkMapError) as exc:
        await map_chunk(TextChunk(index=2, text="x"), llm=llm)
    assert exc.value.chunk_index == 2


@pytest.mark.asyncio
async def test_map_chunk_raises_chunk_map_error_with_underlying_reason():
    llm = _FakeLLM([RuntimeError("upstream boom"), RuntimeError("upstream boom"), RuntimeError("upstream boom")])
    with pytest.raises(ChunkMapError) as exc:
        await map_chunk(TextChunk(index=0, text="x"), llm=llm)
    assert "upstream boom" in exc.value.reason
    assert "upstream boom" in str(exc.value)


@pytest.mark.asyncio
async def test_map_chunk_backs_off_between_attempts_on_rate_limit_error(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    llm = _FakeLLM([_rate_limit_error(), '{"world": [], "characters": [], "plot": []}'])

    result = await map_chunk(TextChunk(index=0, text="x"), llm=llm)

    assert result == {"world": [], "characters": [], "plot": []}
    assert sleeps == [5.0]  # RATE_LIMIT_BACKOFF_S[0]


@pytest.mark.asyncio
async def test_map_chunk_does_not_sleep_between_attempts_on_non_rate_limit_error(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    llm = _FakeLLM([RuntimeError("x"), '{"world": [], "characters": [], "plot": []}'])

    await map_chunk(TextChunk(index=0, text="x"), llm=llm)

    assert sleeps == []


@pytest.mark.asyncio
async def test_run_map_stage_processes_all_chunks_serially_and_reports_progress(monkeypatch):
    from repositories import get_research_repo

    monkeypatch.setattr(get_research_repo(), "replace_for_source", lambda source, chunks: len(chunks))
    chunks = [TextChunk(index=i, text=f"seg{i}") for i in range(3)]
    # 3 map calls + 1 final reduce_chunks call (always fires after the last chunk).
    llm = _FakeLLM(['{"world": [], "characters": [], "plot": []}'] * 4)
    progress_calls = []

    async def on_progress(index, total, ok, error):
        progress_calls.append((index, total, ok, error))

    written, failed = await run_map_stage(
        chunks, llm=llm, source="t.txt", compaction_interval=10, on_progress=on_progress,
    )
    assert failed == []
    assert progress_calls == [(1, 3, True, None), (2, 3, True, None), (3, 3, True, None)]
    assert written == 0  # split_fine_grained on all-empty world/characters/plot produces no chunks


@pytest.mark.asyncio
async def test_run_map_stage_skips_chunk_that_exhausts_retries(monkeypatch):
    from repositories import get_research_repo

    monkeypatch.setattr(get_research_repo(), "replace_for_source", lambda source, chunks: len(chunks))
    chunks = [TextChunk(index=0, text="a"), TextChunk(index=1, text="b")]
    llm = _FakeLLM([
        '{"world": [], "characters": [], "plot": []}',  # chunk0 map call succeeds
        RuntimeError("x"),  # chunk1 map call attempt 1
        RuntimeError("x"),  # chunk1 map call attempt 2
        RuntimeError("x"),  # chunk1 map call attempt 3 -- exhausted, chunk1 skipped
        '{"world": [], "characters": [], "plot": []}',  # final compaction's reduce_chunks call
        # (still fires because chunk0's successful-but-empty result is pending at completed==total)
    ])
    _written, failed = await run_map_stage(chunks, llm=llm, source="t.txt", compaction_interval=10)
    assert failed == [1]


@pytest.mark.asyncio
async def test_run_map_stage_feeds_prior_chunk_facts_as_context_to_next_chunk(monkeypatch):
    from repositories import get_research_repo

    # Mocked for speed/isolation like the other run_map_stage tests -- this test only cares
    # about what context map_chunk receives, not RAG persistence.
    monkeypatch.setattr(get_research_repo(), "replace_for_source", lambda source, chunks: len(chunks))
    # Three responses: chunk0's map call, chunk1's map call, and the reduce_chunks call that
    # always fires after the final chunk regardless of compaction_interval.
    responses_by_call = [
        '{"world": [], "characters": [{"name": "甲", "personality": "冷静", "verbal_tic": ""}], "plot": []}',
        '{"world": [], "characters": [], "plot": []}',
        '{"world": [], "characters": [], "plot": []}',
    ]

    class _SequentialCapturingLLM:
        def __init__(self):
            self.calls = 0
            self.captured_systems = []

        async def ainvoke(self, messages):
            self.captured_systems.append(messages[0].content)
            resp = responses_by_call[self.calls]
            self.calls += 1
            return type("R", (), {"content": resp})()

    llm = _SequentialCapturingLLM()
    chunks = [TextChunk(index=0, text="seg0"), TextChunk(index=1, text="seg1")]
    await run_map_stage(chunks, llm=llm, source="t.txt", compaction_interval=10)
    assert "甲" in llm.captured_systems[1]
    assert "甲" not in llm.captured_systems[0]


@pytest.mark.asyncio
async def test_run_map_stage_compacts_and_persists_every_interval_chunks(monkeypatch):
    from repositories import get_research_repo

    replace_calls = []
    monkeypatch.setattr(
        get_research_repo(), "replace_for_source",
        lambda source, chunks: replace_calls.append((source, len(chunks))) or len(chunks),
    )
    chunks = [TextChunk(index=i, text=f"seg{i}") for i in range(4)]
    llm = _FakeLLM([
        '{"world": ["A"], "characters": [], "plot": []}',
        '{"world": ["B"], "characters": [], "plot": []}',
        '{"world": ["merged-1"], "characters": [], "plot": []}',  # reduce_chunks call after chunk 2
        '{"world": ["C"], "characters": [], "plot": []}',
        '{"world": ["D"], "characters": [], "plot": []}',
        '{"world": ["merged-2"], "characters": [], "plot": []}',  # reduce_chunks call after chunk 4 (final)
    ])
    await run_map_stage(chunks, llm=llm, source="t.txt", compaction_interval=2)
    assert len(replace_calls) == 2  # one at chunk 2 (interval boundary), one at chunk 4 (final)
    assert all(call[0] == "t.txt" for call in replace_calls)


@pytest.mark.asyncio
async def test_run_map_stage_always_compacts_after_final_chunk_even_off_interval_boundary(monkeypatch):
    from repositories import get_research_repo

    replace_calls = []
    monkeypatch.setattr(
        get_research_repo(), "replace_for_source",
        lambda source, chunks: replace_calls.append(source) or len(chunks),
    )
    chunks = [TextChunk(index=i, text=f"seg{i}") for i in range(3)]
    llm = _FakeLLM([
        '{"world": ["A"], "characters": [], "plot": []}',
        '{"world": ["B"], "characters": [], "plot": []}',
        '{"world": ["C"], "characters": [], "plot": []}',
        '{"world": ["merged"], "characters": [], "plot": []}',  # single reduce at final chunk (3 < interval)
    ])
    await run_map_stage(chunks, llm=llm, source="t.txt", compaction_interval=10)
    assert replace_calls == ["t.txt"]


@pytest.mark.asyncio
async def test_run_map_stage_serializes_concurrent_writes_via_lock(monkeypatch):
    from repositories import get_research_repo

    current = 0
    max_concurrent = 0

    async def fake_write_async(source, chunks):
        nonlocal current, max_concurrent
        current += 1
        max_concurrent = max(max_concurrent, current)
        await asyncio.sleep(0)
        current -= 1
        return len(chunks)

    monkeypatch.setattr(get_research_repo(), "replace_for_source_async", fake_write_async)
    chunks = [TextChunk(index=i, text=f"seg{i}") for i in range(3)]
    # interval=1 -> every chunk triggers a compaction+write: 3 map + 3 reduce calls.
    llm = _FakeLLM(['{"world": [], "characters": [], "plot": []}'] * 6)
    await run_map_stage(chunks, llm=llm, source="t.txt", compaction_interval=1)
    assert max_concurrent == 1


@pytest.mark.asyncio
async def test_run_map_stage_does_not_wait_for_write_before_next_chunk_map(monkeypatch):
    from repositories import get_research_repo

    write_release = asyncio.Event()
    chunk1_map_started = asyncio.Event()

    async def fake_write_async(source, chunks):
        await write_release.wait()
        return len(chunks)

    monkeypatch.setattr(get_research_repo(), "replace_for_source_async", fake_write_async)

    class _SignalingLLM:
        def __init__(self, responses):
            self._responses = list(responses)
            self.calls = 0

        async def ainvoke(self, messages):
            self.calls += 1
            if self.calls == 3:  # call order: chunk0 map, chunk0 reduce, chunk1 map, chunk1 reduce
                chunk1_map_started.set()
            resp = self._responses.pop(0)
            return type("R", (), {"content": resp})()

    llm = _SignalingLLM(['{"world": [], "characters": [], "plot": []}'] * 4)
    chunks = [TextChunk(index=0, text="a"), TextChunk(index=1, text="b")]
    task = asyncio.create_task(
        run_map_stage(chunks, llm=llm, source="t.txt", compaction_interval=1),
    )
    # If this times out, the loop is (incorrectly) awaiting chunk0's write -- which never
    # releases -- before starting chunk1's map call.
    await asyncio.wait_for(chunk1_map_started.wait(), timeout=2.0)
    write_release.set()
    written, failed = await asyncio.wait_for(task, timeout=2.0)
    assert failed == []


@pytest.mark.asyncio
async def test_run_map_stage_returns_only_after_all_writes_complete(monkeypatch):
    from repositories import get_research_repo

    write_completed: list[int] = []

    async def fake_write_async(source, chunks):
        await asyncio.sleep(0)
        write_completed.append(len(chunks))
        return len(chunks)

    monkeypatch.setattr(get_research_repo(), "replace_for_source_async", fake_write_async)
    chunks = [TextChunk(index=i, text=f"seg{i}") for i in range(2)]
    llm = _FakeLLM(['{"world": [], "characters": [], "plot": []}'] * 4)
    await run_map_stage(chunks, llm=llm, source="t.txt", compaction_interval=1)
    assert len(write_completed) == 2


@pytest.mark.asyncio
async def test_run_map_stage_write_failure_surfaces_after_gather_not_mid_loop(monkeypatch):
    from repositories import get_research_repo

    async def failing_write_async(source, chunks):
        raise RuntimeError("db down")

    monkeypatch.setattr(get_research_repo(), "replace_for_source_async", failing_write_async)

    class _CountingLLM:
        def __init__(self, response):
            self._response = response
            self.calls = 0

        async def ainvoke(self, messages):
            self.calls += 1
            return type("R", (), {"content": self._response})()

    llm = _CountingLLM('{"world": [], "characters": [], "plot": []}')
    chunks = [TextChunk(index=i, text=f"seg{i}") for i in range(3)]
    with pytest.raises(RuntimeError, match="db down"):
        await run_map_stage(chunks, llm=llm, source="t.txt", compaction_interval=1)
    # All 3 chunks' map+reduce ran despite the first write already having failed --
    # writes no longer abort the loop early, they only surface at the final gather.
    assert llm.calls == 6


@pytest.mark.asyncio
async def test_reduce_chunks_merges_and_dedupes():
    llm = _FakeLLM([
        '{"world": ["设定A"], "characters": [{"name": "甲", "personality": "冷静→后期暴躁", '
        '"verbal_tic": "口头禅X"}], "plot": ["事件1", "事件2"]}',
    ])
    chunk_results = [
        {
            "world": ["设定A"],
            "characters": [{"name": "甲", "personality": "冷静", "verbal_tic": "口头禅X"}],
            "plot": ["事件1"],
        },
        {
            "world": [],
            "characters": [{"name": "甲", "personality": "暴躁", "verbal_tic": ""}],
            "plot": ["事件2"],
        },
    ]
    merged = await reduce_chunks(chunk_results, llm=llm)
    assert merged["characters"][0]["name"] == "甲"


def test_split_fine_grained_produces_one_chunk_per_character_and_fact():
    merged = {
        "world": ["设定A", "设定B"],
        "characters": [{"name": "甲", "personality": "冷静", "verbal_tic": "口头禅X"}],
        "plot": ["事件1"],
    }
    chunks = split_fine_grained(merged, source="test.txt")
    assert all(isinstance(c, ResearchChunk) for c in chunks)
    assert len(chunks) == 2 + 1 + 1
    char_chunk = next(c for c in chunks if c.topic == "甲")
    assert "冷静" in char_chunk.text and "口头禅X" in char_chunk.text
    assert char_chunk.category == "character"
    world_chunks = [c for c in chunks if c.text in ("设定A", "设定B")]
    assert all(c.category == "world" for c in world_chunks)
    plot_chunk = next(c for c in chunks if c.text == "事件1")
    assert plot_chunk.category == "plot"


def test_split_fine_grained_uses_character_mentions_when_provided():
    merged = {
        "world": [],
        "characters": [
            {"name": "甲", "personality": "冷静", "verbal_tic": ""},
            {"name": "乙", "personality": "活泼", "verbal_tic": ""},
        ],
        "plot": [],
    }
    chunks = split_fine_grained(merged, source="test.txt", character_mentions={"甲": 5})
    by_topic = {c.topic: c for c in chunks}
    assert by_topic["甲"].mention_count == 5
    assert by_topic["乙"].mention_count == 1  # not in the dict -- defaults to 1


def test_split_fine_grained_defaults_mention_count_to_one_without_the_param():
    merged = {"world": [], "characters": [{"name": "甲", "personality": "x", "verbal_tic": ""}], "plot": []}
    chunks = split_fine_grained(merged, source="test.txt")
    assert chunks[0].mention_count == 1


@pytest.mark.asyncio
async def test_run_map_stage_accumulates_character_mentions_across_chunks(monkeypatch):
    from repositories import get_research_repo

    upserted_chunks = []
    monkeypatch.setattr(
        get_research_repo(), "replace_for_source",
        lambda source, chunks: upserted_chunks.extend(chunks) or len(chunks),
    )
    # chunk0 mentions 甲; chunk1 mentions 甲 again + 乙; final reduce just echoes characters through.
    responses = [
        '{"world": [], "characters": [{"name": "甲", "personality": "p", "verbal_tic": ""}], "plot": []}',
        '{"world": [], "characters": [{"name": "甲", "personality": "p", "verbal_tic": ""}, '
        '{"name": "乙", "personality": "p2", "verbal_tic": ""}], "plot": []}',
        '{"world": [], "characters": [{"name": "甲", "personality": "p", "verbal_tic": ""}, '
        '{"name": "乙", "personality": "p2", "verbal_tic": ""}], "plot": []}',
    ]
    llm = _FakeLLM(responses)
    chunks = [TextChunk(index=0, text="a"), TextChunk(index=1, text="b")]
    await run_map_stage(chunks, llm=llm, source="t.txt", compaction_interval=10)

    by_topic = {c.topic: c for c in upserted_chunks if c.category == "character"}
    assert by_topic["甲"].mention_count == 2  # appeared in both chunk0 and chunk1's map results
    assert by_topic["乙"].mention_count == 1  # only chunk1


@pytest.mark.asyncio
async def test_run_novel_import_pipeline_end_to_end(monkeypatch):
    from repositories import get_research_repo

    upserted = []
    monkeypatch.setattr(
        get_research_repo(), "replace_for_source",
        lambda source, chunks: upserted.extend(chunks) or len(chunks),
    )
    llm = _FakeLLM([
        '{"world": ["A"], "characters": [], "plot": []}',
        '{"world": ["A"], "characters": [], "plot": []}',
        '{"world": ["A"], "characters": [], "plot": []}',
    ])
    n, failed = await run_novel_import_pipeline(
        "第一段\n" * 5 + "第二段\n" * 5,
        source="t.txt",
        chunk_size=20,
        compaction_interval=10,
        llm=llm,
    )
    assert failed == []
    assert n == len(upserted) > 0


@pytest.mark.asyncio
async def test_run_distillation_from_chunks_shares_precomputed_chunks(monkeypatch):
    from engine.setup_chat.novel_import import run_distillation_from_chunks
    from repositories import get_research_repo

    upserted = []
    monkeypatch.setattr(
        get_research_repo(), "replace_for_source",
        lambda source, chunks: upserted.extend(chunks) or len(chunks),
    )
    chunks = chunk_text("第一段\n" * 5 + "第二段\n" * 5, chunk_size=20)
    llm = _FakeLLM(['{"world": ["A"], "characters": [], "plot": []}'] * (len(chunks) + 1))
    n, failed = await run_distillation_from_chunks(
        chunks, source="t.txt", compaction_interval=10, llm=llm,
    )
    assert failed == []
    assert n == len(upserted) > 0
