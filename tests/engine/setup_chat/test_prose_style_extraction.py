import json

import pytest
from engine.setup_chat.novel_import import TextChunk
from engine.setup_chat.prose_style_extraction import (
    _CATEGORIES,
    ChunkStyleError,
    extract_style_chunk,
    reduce_style_samples,
    run_style_extraction_pipeline,
    run_style_map_stage,
    synthesize_style_card,
)


class _FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    async def ainvoke(self, messages):
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return type("R", (), {"content": resp})()


@pytest.mark.asyncio
async def test_extract_style_chunk_uses_pack_override_system_prompt(monkeypatch):
    sentinel = "SENTINEL文风抽取覆写"
    monkeypatch.setattr(
        "engine.setup_chat.prose_style_extraction.active_prose_style_extraction_prompt",
        lambda: sentinel,
    )
    captured: dict[str, str] = {}

    class _CapturingLLM:
        async def ainvoke(self, messages):
            captured["system"] = messages[0].content
            return type("R", (), {"content": (
                '{"环境": [], "台词": [], "动作": [], "亲密描写": [], "心理": []}'
            )})()

    await extract_style_chunk(TextChunk(index=0, text="正文……"), llm=_CapturingLLM())
    assert captured["system"] == sentinel


@pytest.mark.asyncio
async def test_extract_style_chunk_parses_all_categories():
    llm = _FakeLLM([
        '{"环境": ["夜色浓稠地压下来。"], "台词": ["“别走。”"], "动作": ["她攥紧了衣角。"], '
        '"亲密描写": [], "心理": ["他心里一沉。"]}',
    ])
    result = await extract_style_chunk(TextChunk(index=0, text="正文……"), llm=llm)
    assert set(result.keys()) == set(_CATEGORIES)
    assert result["环境"] == ["夜色浓稠地压下来。"]
    assert result["亲密描写"] == []


@pytest.mark.asyncio
async def test_extract_style_chunk_missing_category_defaults_to_empty():
    llm = _FakeLLM(['{"环境": ["A"]}'])
    result = await extract_style_chunk(TextChunk(index=0, text="x"), llm=llm)
    assert result["台词"] == []
    assert result["心理"] == []


@pytest.mark.asyncio
async def test_extract_style_chunk_retries_then_succeeds():
    llm = _FakeLLM([
        RuntimeError("网络错误"),
        RuntimeError("网络错误"),
        '{"环境": [], "台词": [], "动作": [], "亲密描写": [], "心理": []}',
    ])
    result = await extract_style_chunk(TextChunk(index=1, text="x"), llm=llm)
    assert result == {cat: [] for cat in _CATEGORIES}


@pytest.mark.asyncio
async def test_extract_style_chunk_raises_after_exhausting_retries():
    llm = _FakeLLM([RuntimeError("a"), RuntimeError("b"), RuntimeError("c")])
    with pytest.raises(ChunkStyleError) as exc:
        await extract_style_chunk(TextChunk(index=2, text="x"), llm=llm)
    assert exc.value.chunk_index == 2


@pytest.mark.asyncio
async def test_run_style_map_stage_skips_failed_chunk_and_keeps_others():
    chunks = [TextChunk(index=0, text="a"), TextChunk(index=1, text="b")]
    llm = _FakeLLM([
        '{"环境": ["A"], "台词": [], "动作": [], "亲密描写": [], "心理": []}',
        RuntimeError("x"), RuntimeError("x"), RuntimeError("x"),
    ])
    results = await run_style_map_stage(chunks, llm=llm, concurrency=None)
    assert len(results) == 1
    assert results[0]["环境"] == ["A"]


def test_reduce_style_samples_dedupes_across_chunks():
    chunk_results = [
        {"环境": ["夜色浓稠。"], "台词": [], "动作": [], "亲密描写": [], "心理": []},
        {"环境": ["夜色浓稠。", "月光洒落。"], "台词": [], "动作": [], "亲密描写": [], "心理": []},
    ]
    reduced = reduce_style_samples(chunk_results)
    assert reduced["环境"].count("夜色浓稠。") == 1
    assert "月光洒落。" in reduced["环境"]


def test_reduce_style_samples_prefers_in_band_length_and_caps_at_five():
    too_short = "短。"
    in_band = "这是一句长度落在三十到两百字符区间之内、读起来比较自然完整的示例摘录句子文本内容。" * 2
    in_band = in_band[:120]
    chunk_results = [{
        "环境": [too_short] + [f"{in_band}{i}" for i in range(6)],
        "台词": [], "动作": [], "亲密描写": [], "心理": [],
    }]
    reduced = reduce_style_samples(chunk_results)
    assert len(reduced["环境"]) == 5
    assert too_short not in reduced["环境"]


def test_reduce_style_samples_empty_category_stays_empty():
    chunk_results = [{"环境": ["A"], "台词": [], "动作": [], "亲密描写": [], "心理": []}]
    reduced = reduce_style_samples(chunk_results)
    assert reduced["亲密描写"] == []


def test_reduce_style_samples_truncates_overlong_excerpt_to_sentence_end():
    long_text = "第一句到此为止。" + "填充字符" * 200 + "第二句到此为止。"
    chunk_results = [{"环境": [long_text], "台词": [], "动作": [], "亲密描写": [], "心理": []}]
    reduced = reduce_style_samples(chunk_results)
    assert reduced["环境"][0].endswith("。")
    assert len(reduced["环境"][0]) < len(long_text)


@pytest.mark.asyncio
async def test_synthesize_style_card_parses_structured_fields():
    captured = {}

    class _CapturingLLM:
        async def ainvoke(self, messages):
            captured["human"] = messages[-1].content
            return type("R", (), {"content": json.dumps({
                "title": "清冷疏离",
                "opening": "开场定位一段。",
                "techniques": ["**留白**：只写动作「示例」"],
                "examples": [{"label": "开场铺垫", "text": "夜色浓稠。"}],
                "taboos": ["忌堆砌形容词：会显得腻"],
            }, ensure_ascii=False)})()

    result = await synthesize_style_card(
        {"环境": ["夜色浓稠。"], "台词": [], "动作": [], "亲密描写": [], "心理": []},
        novel_title="测试小说",
        llm=_CapturingLLM(),
    )
    assert result["title"] == "清冷疏离"
    assert result["opening"] == "开场定位一段。"
    assert result["techniques"] == ["**留白**：只写动作「示例」"]
    assert result["examples"] == [{"label": "开场铺垫", "text": "夜色浓稠。"}]
    assert result["taboos"] == ["忌堆砌形容词：会显得腻"]
    assert "夜色浓稠。" in captured["human"]
    assert "测试小说" in captured["human"]


@pytest.mark.asyncio
async def test_synthesize_style_card_falls_back_title_when_unparseable():
    class _BadLLM:
        async def ainvoke(self, messages):
            return type("R", (), {"content": "不是 JSON"})()

    result = await synthesize_style_card(
        {"环境": ["A"], "台词": [], "动作": [], "亲密描写": [], "心理": []},
        novel_title="测试小说",
        llm=_BadLLM(),
    )
    assert result["title"] == "测试小说风格"
    assert result["opening"] == ""
    assert result["techniques"] == []
    assert result["examples"] == []
    assert result["taboos"] == []


@pytest.mark.asyncio
async def test_run_style_extraction_pipeline_writes_preset_file(tmp_path, monkeypatch):
    import engine.setup_chat.prose_style_extraction as mod

    monkeypatch.setattr(mod, "prose_styles_dir", lambda: str(tmp_path))
    chunks = [TextChunk(index=0, text="正文……")]
    llm = _FakeLLM([
        '{"环境": ["夜色浓稠地压下来。"], "台词": [], "动作": [], "亲密描写": [], "心理": []}',
        json.dumps({
            "title": "清冷疏离",
            "opening": "开场定位一段。",
            "techniques": ["**留白**：只写动作「示例」"],
            "examples": [{"label": "开场铺垫", "text": "夜色浓稠地压下来。"}],
            "taboos": ["忌堆砌形容词：会显得腻"],
        }, ensure_ascii=False),
    ])
    result = await run_style_extraction_pipeline(
        chunks, novel_id="nov1", novel_title="测试小说", llm=llm, concurrency=None,
    )
    assert result == {"id": "auto-nov1", "name": "清冷疏离"}
    on_disk = (tmp_path / "auto-nov1.md").read_text(encoding="utf-8")
    assert on_disk.startswith("# 语感调色：清冷疏离")
    assert "夜色浓稠地压下来。" in on_disk


@pytest.mark.asyncio
async def test_run_style_extraction_pipeline_returns_none_when_all_chunks_fail(tmp_path, monkeypatch):
    import engine.setup_chat.prose_style_extraction as mod

    monkeypatch.setattr(mod, "prose_styles_dir", lambda: str(tmp_path))
    chunks = [TextChunk(index=0, text="x")]
    llm = _FakeLLM([RuntimeError("a"), RuntimeError("b"), RuntimeError("c")])
    result = await run_style_extraction_pipeline(
        chunks, novel_id="nov1", novel_title="测试小说", llm=llm, concurrency=None,
    )
    assert result is None
    assert not (tmp_path / "auto-nov1.md").exists()


@pytest.mark.asyncio
async def test_run_style_extraction_pipeline_returns_none_when_all_categories_empty(tmp_path, monkeypatch):
    import engine.setup_chat.prose_style_extraction as mod

    monkeypatch.setattr(mod, "prose_styles_dir", lambda: str(tmp_path))
    chunks = [TextChunk(index=0, text="x")]
    llm = _FakeLLM(['{"环境": [], "台词": [], "动作": [], "亲密描写": [], "心理": []}'])
    result = await run_style_extraction_pipeline(
        chunks, novel_id="nov1", novel_title="测试小说", llm=llm, concurrency=None,
    )
    assert result is None
    assert not (tmp_path / "auto-nov1.md").exists()


def test_bound_llm_routes_through_prose_style_extraction_node(monkeypatch):
    import engine.setup_chat.prose_style_extraction as mod

    bind_calls: list[tuple[str, dict]] = []

    def fake_bind_node_llm(llm, agent, params):
        bind_calls.append((agent, params))
        return object()

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: object())
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {"prose_style_extraction": {"enable_thinking": False}}},
    )
    monkeypatch.setattr("engine.modes.author_loop_skill_prefs.bind_node_llm", fake_bind_node_llm)

    mod._bound_llm()
    assert bind_calls == [(
        "prose_style_extraction", {"prose_style_extraction": {"enable_thinking": False}},
    )]
