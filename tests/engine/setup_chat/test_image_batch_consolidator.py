import pytest
from engine.setup_chat.image_batch_consolidator import (
    ImagePageDescription,
    consolidate_descriptions,
    iter_batch_windows,
    recognize_image_batch,
    run_vision_and_consolidation_pipeline,
)


def test_iter_batch_windows_single_batch():
    windows = iter_batch_windows(8, batch_size=10, overlap=2)
    assert len(windows) == 1
    assert windows[0].new_start == 0
    assert windows[0].new_end == 8
    assert windows[0].overlap_start == 0


def test_iter_batch_windows_two_batches_with_overlap():
    windows = iter_batch_windows(20, batch_size=10, overlap=2)
    assert len(windows) == 2
    assert windows[0].new_start == 0 and windows[0].new_end == 10 and windows[0].overlap_start == 0
    assert windows[1].new_start == 10 and windows[1].new_end == 20 and windows[1].overlap_start == 8


@pytest.mark.asyncio
async def test_recognize_image_batch_parses_per_page_markers():
    class _FakeResp:
        content = (
            "=== 第1页 (1.jpg) ===\n一名魁梧剑士站在城门口\n\n"
            "=== 第2页 (2.jpg) ===\n他拔剑迎敌"
        )

    class _FakeLlm:
        async def ainvoke(self, messages):
            return _FakeResp()

    new_images = [("1.jpg", b"raw1"), ("2.jpg", b"raw2")]
    out = await recognize_image_batch(new_images, vision_llm=_FakeLlm(), new_start_index=0)
    assert len(out) == 2
    assert out[0] == ImagePageDescription(index=0, filename="1.jpg", text="一名魁梧剑士站在城门口")
    assert out[1] == ImagePageDescription(index=1, filename="2.jpg", text="他拔剑迎敌")


@pytest.mark.asyncio
async def test_recognize_image_batch_assigns_correct_page_numbers_mid_book():
    class _FakeResp:
        content = "=== 第11页 (a.jpg) ===\n描述A\n\n=== 第12页 (b.jpg) ===\n描述B"

    class _FakeLlm:
        async def ainvoke(self, messages):
            return _FakeResp()

    new_images = [("a.jpg", b"raw1"), ("b.jpg", b"raw2")]
    out = await recognize_image_batch(new_images, vision_llm=_FakeLlm(), new_start_index=10)
    assert [p.index for p in out] == [10, 11]
    assert [p.text for p in out] == ["描述A", "描述B"]


@pytest.mark.asyncio
async def test_recognize_image_batch_falls_back_to_shared_text_when_unparseable():
    class _FakeResp:
        content = "画面里两个人在打斗，没有按格式分页。"

    class _FakeLlm:
        async def ainvoke(self, messages):
            return _FakeResp()

    new_images = [("1.jpg", b"raw1"), ("2.jpg", b"raw2")]
    out = await recognize_image_batch(new_images, vision_llm=_FakeLlm(), new_start_index=0)
    assert len(out) == 2
    assert out[0].text == "画面里两个人在打斗，没有按格式分页。"
    assert out[1].text == out[0].text
    assert [p.filename for p in out] == ["1.jpg", "2.jpg"]


@pytest.mark.asyncio
async def test_recognize_image_batch_sends_context_images_and_new_images():
    captured = {}

    class _FakeResp:
        content = "=== 第3页 (c.jpg) ===\n描述C"

    class _FakeLlm:
        async def ainvoke(self, messages):
            captured["messages"] = messages
            return _FakeResp()

    await recognize_image_batch(
        [("c.jpg", b"raw-c")],
        vision_llm=_FakeLlm(),
        new_start_index=2,
        context_images=[("a.jpg", b"raw-a"), ("b.jpg", b"raw-b")],
    )
    human_content = captured["messages"][1].content
    # 2 context images + 1 new image => 3 image blocks + 3 text tags = 6 content items
    image_blocks = [c for c in human_content if isinstance(c, dict) and c["type"] == "image_url"]
    text_tags = [c["text"] for c in human_content if isinstance(c, dict) and c["type"] == "text"]
    assert len(image_blocks) == 3
    assert text_tags == ["[上下文页: a.jpg]", "[上下文页: b.jpg]", "[第3页: c.jpg]"]


@pytest.mark.asyncio
async def test_consolidate_descriptions_passthrough_single_page():
    pages = [ImagePageDescription(index=0, filename="1.jpg", text="一名魁梧剑士")]
    out, roster = await consolidate_descriptions(pages, llm=object())
    assert out == pages
    assert roster == ""


@pytest.mark.asyncio
async def test_consolidate_descriptions_calls_llm_for_multiple_pages():
    class _FakeResp:
        content = (
            "=== 第1页 (1.jpg) ===\n魁梧剑士（后文称卡尔）站在城门口\n\n"
            "=== 第2页 (2.jpg) ===\n卡尔拔剑迎敌"
        )

    class _FakeLlm:
        def __init__(self) -> None:
            self.messages = None

        async def ainvoke(self, messages):
            self.messages = messages
            return _FakeResp()

    llm = _FakeLlm()
    pages = [
        ImagePageDescription(index=0, filename="1.jpg", text="一名魁梧剑士"),
        ImagePageDescription(index=1, filename="2.jpg", text="卡尔拔剑"),
    ]
    out, roster = await consolidate_descriptions(pages, llm=llm)
    assert llm.messages is not None
    assert len(out) == 2
    assert "卡尔" in out[0].text
    assert out[1].filename == "2.jpg"
    assert roster == ""  # no roster block in the fake response


@pytest.mark.asyncio
async def test_consolidate_descriptions_extracts_roster_block():
    # Uses 2 pages (not 1) to avoid the single-page-with-no-prior-context passthrough
    # shortcut at the top of consolidate_descriptions, which would skip the LLM call
    # entirely and never reach the roster-parsing code this test exercises.
    class _FakeResp:
        content = (
            "=== 第1页 (1.jpg) ===\n魁梧剑士站在城门口\n\n"
            "=== 第2页 (2.jpg) ===\n魁梧剑士拔剑迎敌\n\n"
            "=== 角色名册 ===\n"
            "卡尔：魁梧，黑色铠甲，配巨剑"
        )

    class _FakeLlm:
        async def ainvoke(self, messages):
            return _FakeResp()

    pages = [
        ImagePageDescription(index=0, filename="1.jpg", text="一名魁梧剑士"),
        ImagePageDescription(index=1, filename="2.jpg", text="魁梧剑士拔剑"),
    ]
    out, roster = await consolidate_descriptions(pages, llm=_FakeLlm(), prior_entity_context="")
    assert len(out) == 2
    assert out[0].text == "魁梧剑士站在城门口"
    assert roster == "卡尔：魁梧，黑色铠甲，配巨剑"


@pytest.mark.asyncio
async def test_consolidate_descriptions_passes_prior_roster_into_prompt():
    captured = {}

    class _FakeResp:
        content = "=== 第1页 (1.jpg) ===\n卡尔拔剑\n\n=== 角色名册 ===\n卡尔：魁梧剑士"

    class _FakeLlm:
        async def ainvoke(self, messages):
            captured["system"] = messages[0].content
            return _FakeResp()

    pages = [ImagePageDescription(index=0, filename="1.jpg", text="卡尔拔剑")]
    await consolidate_descriptions(
        pages, llm=_FakeLlm(), prior_entity_context="配角A：魁梧，黑色铠甲",
    )
    assert "配角A：魁梧，黑色铠甲" in captured["system"]


@pytest.mark.asyncio
async def test_consolidate_descriptions_keeps_prior_roster_when_block_missing():
    class _FakeResp:
        content = "=== 第1页 (1.jpg) ===\n卡尔拔剑"  # no roster block in the response

    class _FakeLlm:
        async def ainvoke(self, messages):
            return _FakeResp()

    pages = [ImagePageDescription(index=0, filename="1.jpg", text="卡尔拔剑")]
    out, roster = await consolidate_descriptions(
        pages, llm=_FakeLlm(), prior_entity_context="配角A：魁梧，黑色铠甲",
    )
    assert roster == "配角A：魁梧，黑色铠甲"


@pytest.mark.asyncio
async def test_run_pipeline_passes_overlap_images_to_later_batch(monkeypatch):
    batch_calls: list[dict] = []

    async def fake_recognize_batch(new_images, *, vision_llm, new_start_index, context_images=None):
        batch_calls.append({"new_start_index": new_start_index, "context_images": context_images})
        return [
            ImagePageDescription(index=new_start_index + i, filename=name, text=f"desc:{name}")
            for i, (name, _raw) in enumerate(new_images)
        ]

    async def fake_consolidate(pages, *, llm, prior_entity_context=""):
        return pages, prior_entity_context

    monkeypatch.setattr(
        "engine.setup_chat.image_batch_consolidator.recognize_image_batch", fake_recognize_batch,
    )
    monkeypatch.setattr(
        "engine.setup_chat.image_batch_consolidator.consolidate_descriptions", fake_consolidate,
    )

    images = [(f"{i}.jpg", f"bytes-{i}".encode()) for i in range(1, 13)]
    text, failed, pages = await run_vision_and_consolidation_pipeline(
        images, vision_llm=object(), consolidator_llm=object(), batch_size=10, overlap=2,
    )
    assert failed == []
    assert len(pages) == 12
    assert "desc:1.jpg" in text and "desc:12.jpg" in text
    assert len(batch_calls) == 2
    assert batch_calls[0]["context_images"] is None
    assert batch_calls[1]["new_start_index"] == 10
    assert [name for name, _ in batch_calls[1]["context_images"]] == ["9.jpg", "10.jpg"]


@pytest.mark.asyncio
async def test_run_pipeline_carries_roster_forward_across_batches(monkeypatch):
    consolidate_calls: list[str] = []

    async def fake_recognize_batch(new_images, *, vision_llm, new_start_index, context_images=None):
        return [
            ImagePageDescription(index=new_start_index + i, filename=name, text=f"desc:{name}")
            for i, (name, _raw) in enumerate(new_images)
        ]

    async def fake_consolidate(pages, *, llm, prior_entity_context=""):
        consolidate_calls.append(prior_entity_context)
        return pages, f"卡尔：魁梧剑士（第{len(consolidate_calls)}批）"

    monkeypatch.setattr(
        "engine.setup_chat.image_batch_consolidator.recognize_image_batch", fake_recognize_batch,
    )
    monkeypatch.setattr(
        "engine.setup_chat.image_batch_consolidator.consolidate_descriptions", fake_consolidate,
    )

    images = [(f"{i}.jpg", f"bytes-{i}".encode()) for i in range(1, 21)]  # 20 pages -> 2 batches
    text, failed, pages = await run_vision_and_consolidation_pipeline(
        images, vision_llm=object(), consolidator_llm=object(), batch_size=10, overlap=2,
    )
    assert failed == []
    assert len(consolidate_calls) == 2
    assert consolidate_calls[0] == ""
    assert consolidate_calls[1] == "卡尔：魁梧剑士（第1批）"
    assert text.startswith("[人物名册]\n卡尔：魁梧剑士（第2批）")


@pytest.mark.asyncio
async def test_run_pipeline_keeps_roster_when_consolidation_fails(monkeypatch):
    call_count = {"n": 0}

    async def fake_recognize_batch(new_images, *, vision_llm, new_start_index, context_images=None):
        return [
            ImagePageDescription(index=new_start_index + i, filename=name, text=f"desc:{name}")
            for i, (name, _raw) in enumerate(new_images)
        ]

    async def fake_consolidate(pages, *, llm, prior_entity_context=""):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("boom")
        return pages, "卡尔：魁梧剑士"

    monkeypatch.setattr(
        "engine.setup_chat.image_batch_consolidator.recognize_image_batch", fake_recognize_batch,
    )
    monkeypatch.setattr(
        "engine.setup_chat.image_batch_consolidator.consolidate_descriptions", fake_consolidate,
    )

    images = [(f"{i}.jpg", f"bytes-{i}".encode()) for i in range(1, 31)]  # 30 pages -> 3 batches
    text, failed, pages = await run_vision_and_consolidation_pipeline(
        images, vision_llm=object(), consolidator_llm=object(), batch_size=10, overlap=2,
    )
    assert failed == []
    # batch 2's consolidate call raised -> roster for batch 3 (and the final text) stays at batch 1's value
    assert text.startswith("[人物名册]\n卡尔：魁梧剑士")


@pytest.mark.asyncio
async def test_run_pipeline_marks_whole_batch_failed_on_vision_rate_limit(monkeypatch):
    import httpx
    import openai

    def _rate_limit_error() -> openai.RateLimitError:
        # Mirrors the helper in tests/engine/setup_chat/test_attachment_tool.py --
        # openai.RateLimitError requires a real httpx.Response, not a plain message.
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        response = httpx.Response(429, request=request)
        return openai.RateLimitError("rate limited", response=response, body=None)

    async def fake_recognize_batch(new_images, *, vision_llm, new_start_index, context_images=None):
        raise _rate_limit_error()

    progress: list[tuple[int, bool]] = []

    async def on_image_done(index, total, ok, error):
        progress.append((index, ok))

    monkeypatch.setattr(
        "engine.setup_chat.image_batch_consolidator.recognize_image_batch", fake_recognize_batch,
    )

    images = [(f"{i}.jpg", f"bytes-{i}".encode()) for i in range(1, 6)]  # 1 batch, 5 pages
    text, failed, pages = await run_vision_and_consolidation_pipeline(
        images, vision_llm=object(), consolidator_llm=object(), batch_size=10, overlap=2,
        on_image_done=on_image_done,
    )
    assert failed == [0, 1, 2, 3, 4]
    assert pages == []
    assert progress == [(i, False) for i in range(5)]
