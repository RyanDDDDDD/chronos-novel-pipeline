import inspect

import httpx
import openai
import pytest
from langchain_core.runnables.base import Runnable
from engine.setup_chat import attachments as attachments_mod
from engine.setup_chat import style_source_cache
from engine.setup_chat.attachment_tool import (
    get_image_description,
    list_persisted_attachments,
    read_attachment,
    read_attachment_image,
    read_attachment_images,
    read_persisted_attachment,
)
from engine.setup_chat.attachments import store_attachment
from llm.retry import RetryingChatModel


def _rate_limit_error() -> openai.RateLimitError:
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(429, request=request)
    return openai.RateLimitError("rate limited", response=response, body=None)


@pytest.fixture(autouse=True)
def _clear_store():
    attachments_mod._ATTACHMENTS.clear()
    style_source_cache._STYLE_SOURCE_CHUNKS.clear()
    yield
    attachments_mod._ATTACHMENTS.clear()
    style_source_cache._STYLE_SOURCE_CHUNKS.clear()


class _FakeHub:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.image_progress_calls: list[dict] = []
        self.begin_image_calls: list[int] = []

    async def broadcast(self, event: dict) -> None:
        self.events.append(event)

    async def begin_image_recognition_progress(self, total: int, *, novel_id: str | None = None) -> None:
        self.begin_image_calls.append(total)

    async def advance_image_recognition_progress(self, *, ok: bool, error: str | None = None) -> None:
        self.image_progress_calls.append({"ok": ok, "error": error})

    async def note_novel_import_text_start(self, novel_id: str, total: int) -> None:
        await self.broadcast({"type": "novel_import_start", "total": total, "novel_id": novel_id})

    async def note_novel_import_text_progress(
        self, novel_id: str, *, index: int, total: int, ok: bool, error: str | None,
    ) -> None:
        await self.broadcast({
            "type": "novel_import_progress",
            "index": index,
            "total": total,
            "ok": ok,
            "error": error,
            "novel_id": novel_id,
        })

    async def note_novel_import_text_done(self, novel_id: str) -> None:
        await self.broadcast({"type": "novel_import_done", "novel_id": novel_id})


def _patch_common(monkeypatch, hub):
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)
    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: object())


@pytest.mark.asyncio
async def test_read_attachment_returns_pipeline_summary_not_raw_text(monkeypatch):
    async def fake_distill(chunks, *, source, compaction_interval, llm, on_progress=None):
        return 2, []

    fake_hub = _FakeHub()
    _patch_common(monkeypatch, fake_hub)
    monkeypatch.setattr("engine.setup_chat.novel_import.run_distillation_from_chunks", fake_distill)
    aid = store_attachment("novel.txt", "原始小说全文，讲述了赛博都市里阿明的故事……".encode("utf-8"))

    out = await read_attachment.ainvoke({"attachment_id": aid})

    assert "提炼完成" in out
    assert "原始小说全文" not in out
    assert "novel.txt" in out
    assert any(e["type"] == "novel_import_start" for e in fake_hub.events)
    assert any(e["type"] == "novel_import_done" for e in fake_hub.events)


@pytest.mark.asyncio
async def test_read_attachment_return_message_points_to_exhaustive_tools(monkeypatch):
    async def fake_distill(chunks, *, source, compaction_interval, llm, on_progress=None):
        return 2, []

    _patch_common(monkeypatch, _FakeHub())
    monkeypatch.setattr("engine.setup_chat.novel_import.run_distillation_from_chunks", fake_distill)
    aid = store_attachment("novel.txt", "原始小说全文……".encode("utf-8"))

    out = await read_attachment.ainvoke({"attachment_id": aid})

    assert "list_characters" in out
    assert "get_world_facts" in out
    assert "get_plot_points" in out


@pytest.mark.asyncio
async def test_read_attachment_return_message_mentions_style_followup(monkeypatch):
    async def fake_distill(chunks, **_kwargs):
        return 1, []

    _patch_common(monkeypatch, _FakeHub())
    monkeypatch.setattr("engine.setup_chat.novel_import.run_distillation_from_chunks", fake_distill)
    aid = store_attachment("novel.txt", "内容".encode("utf-8"))

    out = await read_attachment.ainvoke({"attachment_id": aid})

    assert "present_choices" in out
    assert "build_prose_style_from_import" in out


@pytest.mark.asyncio
async def test_read_attachment_caches_chunks_for_style_tool(monkeypatch):
    captured: dict = {}

    async def fake_distill(chunks, **_kwargs):
        captured["chunks"] = chunks
        return 1, []

    _patch_common(monkeypatch, _FakeHub())
    monkeypatch.setattr("engine.setup_chat.novel_import.run_distillation_from_chunks", fake_distill)
    aid = store_attachment("novel.txt", "内容".encode("utf-8"))

    await read_attachment.ainvoke({"attachment_id": aid})

    from utils.paths import active_novel_id
    cached = style_source_cache.get_chunks(active_novel_id())
    assert cached == captured["chunks"]


@pytest.mark.asyncio
async def test_read_attachment_is_single_use(monkeypatch):
    async def fake_distill(chunks, **_kwargs):
        return 1, []

    _patch_common(monkeypatch, _FakeHub())
    monkeypatch.setattr("engine.setup_chat.novel_import.run_distillation_from_chunks", fake_distill)
    aid = store_attachment("novel.txt", "内容".encode("utf-8"))

    await read_attachment.ainvoke({"attachment_id": aid})
    out = await read_attachment.ainvoke({"attachment_id": aid})

    assert "不存在" in out


@pytest.mark.asyncio
async def test_read_attachment_unknown_id_returns_friendly_error():
    out = await read_attachment.ainvoke({"attachment_id": "ghost"})
    assert "不存在" in out


@pytest.mark.asyncio
async def test_read_attachment_does_not_truncate_long_text(monkeypatch):
    captured: dict = {}

    async def fake_distill(chunks, *, source, compaction_interval, llm, on_progress=None):
        captured["text_len"] = sum(len(c.text) for c in chunks)
        return 1, []

    _patch_common(monkeypatch, _FakeHub())
    monkeypatch.setattr("engine.setup_chat.novel_import.run_distillation_from_chunks", fake_distill)
    long_text = "字" * 200_000
    aid = store_attachment("long.txt", long_text.encode("utf-8"))

    await read_attachment.ainvoke({"attachment_id": aid})

    assert captured["text_len"] == 200_000


@pytest.mark.asyncio
async def test_read_attachment_reports_failed_chunks(monkeypatch):
    async def fake_distill(chunks, **_kwargs):
        return 3, [2]

    _patch_common(monkeypatch, _FakeHub())
    monkeypatch.setattr("engine.setup_chat.novel_import.run_distillation_from_chunks", fake_distill)
    aid = store_attachment("novel.txt", "内容".encode("utf-8"))

    out = await read_attachment.ainvoke({"attachment_id": aid})

    assert "1 个分片提炼失败已跳过" in out


@pytest.mark.asyncio
async def test_read_attachment_image_without_model_ref_returns_friendly_error(monkeypatch):
    fake_hub = _FakeHub()
    _patch_common(monkeypatch, fake_hub)
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {}},
    )
    aid = store_attachment("page.png", b"\x89PNG fake bytes")

    out = await read_attachment_image.ainvoke({"attachment_id": aid})

    assert "图片识别" in out
    assert "对话" in out
    assert fake_hub.image_progress_calls == []
    assert fake_hub.begin_image_calls == []


@pytest.mark.asyncio
async def test_read_attachment_image_unknown_id_returns_friendly_error():
    out = await read_attachment_image.ainvoke({"attachment_id": "ghost"})
    assert "不存在" in out


@pytest.mark.asyncio
async def test_read_attachment_image_calls_vision_llm_then_distills(monkeypatch):
    class _FakeVisionResp:
        content = "画面描述：一个赛博都市场景，角色阿明说了一句台词。"

    class _FakeVisionLlm:
        def __init__(self) -> None:
            self.messages = None

        async def ainvoke(self, messages):
            self.messages = messages
            return _FakeVisionResp()

    vision_llm = _FakeVisionLlm()
    bind_calls: list[str] = []

    def fake_bind_node_llm(llm, agent, params):
        bind_calls.append(agent)
        if agent == "image_recognition":
            return vision_llm
        return llm  # text_recognition: identity passthrough for this test

    captured_distill: dict = {}

    async def fake_distill(chunks, *, source, compaction_interval, llm, on_progress=None):
        captured_distill["text"] = chunks[0].text if chunks else ""
        captured_distill["source"] = source
        return 1, []

    fake_hub = _FakeHub()
    _patch_common(monkeypatch, fake_hub)
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {"image_recognition": {"model_ref": "custom-vision-1"}}},
    )
    monkeypatch.setattr("engine.modes.author_loop_skill_prefs.bind_node_llm", fake_bind_node_llm)
    monkeypatch.setattr("engine.setup_chat.novel_import.run_distillation_from_chunks", fake_distill)
    aid = store_attachment("page.png", b"\x89PNG fake bytes")

    out = await read_attachment_image.ainvoke({"attachment_id": aid})

    assert bind_calls == ["image_recognition", "text_recognition"]
    assert vision_llm.messages is not None
    human = vision_llm.messages[1].content
    assert isinstance(human, list)
    image_url = human[0]["image_url"]["url"]
    assert image_url.startswith("data:image/jpeg;base64,")
    assert "赛博都市" in captured_distill["text"]
    assert captured_distill["source"] == "page.png"
    assert "识别完成" in out
    assert fake_hub.events == []  # no chunk-level novel_import_* noise for a single image
    assert fake_hub.begin_image_calls == [1]
    assert fake_hub.image_progress_calls == [{"ok": True, "error": None}]


@pytest.mark.asyncio
async def test_read_attachment_image_retries_then_succeeds_after_transient_rate_limit(monkeypatch):
    class _FakeVisionResp:
        content = "画面描述：一个赛博都市场景，角色阿明说了一句台词。"

    class _FlakyVisionLlm(Runnable):
        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, input, config=None, **kwargs):
            raise NotImplementedError

        async def ainvoke(self, messages, config=None, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise _rate_limit_error()
            return _FakeVisionResp()

    inner = _FlakyVisionLlm()
    vision_llm = RetryingChatModel(bound=inner)

    def fake_bind_node_llm(llm, agent, params):
        return vision_llm if agent == "image_recognition" else llm

    async def fake_distill(chunks, *, source, compaction_interval, llm, on_progress=None):
        return 1, []

    fake_hub = _FakeHub()
    _patch_common(monkeypatch, fake_hub)
    monkeypatch.setattr("asyncio.sleep", lambda _s: _noop_awaitable())
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {"image_recognition": {"model_ref": "custom-vision-1"}}},
    )
    monkeypatch.setattr("engine.modes.author_loop_skill_prefs.bind_node_llm", fake_bind_node_llm)
    monkeypatch.setattr("engine.setup_chat.novel_import.run_distillation_from_chunks", fake_distill)
    aid = store_attachment("page.png", b"\x89PNG fake bytes")

    out = await read_attachment_image.ainvoke({"attachment_id": aid})

    assert inner.calls == 2
    assert "识别完成" in out
    assert fake_hub.image_progress_calls == [{"ok": True, "error": None}]


async def _noop_awaitable() -> None:
    return None


@pytest.mark.asyncio
async def test_read_attachment_image_returns_friendly_message_after_exhausting_rate_limit_retries(monkeypatch):
    class _AlwaysLimitedVisionLlm(Runnable):
        def invoke(self, input, config=None, **kwargs):
            raise NotImplementedError

        async def ainvoke(self, messages, config=None, **kwargs):
            raise _rate_limit_error()

    def fake_bind_node_llm(llm, agent, params):
        return RetryingChatModel(bound=_AlwaysLimitedVisionLlm()) if agent == "image_recognition" else llm

    fake_hub = _FakeHub()
    _patch_common(monkeypatch, fake_hub)
    monkeypatch.setattr("asyncio.sleep", lambda _s: _noop_awaitable())
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {"image_recognition": {"model_ref": "custom-vision-1"}}},
    )
    monkeypatch.setattr("engine.modes.author_loop_skill_prefs.bind_node_llm", fake_bind_node_llm)
    aid = store_attachment("page.png", b"\x89PNG fake bytes")

    out = await read_attachment_image.ainvoke({"attachment_id": aid})

    assert "限流" in out
    assert "page.png" in out
    assert fake_hub.image_progress_calls == [{"ok": False, "error": "视觉模型服务商临时限流"}]


@pytest.mark.asyncio
async def test_read_attachment_image_empty_description_returns_message_without_distilling(monkeypatch):
    class _FakeVisionResp:
        content = "   "

    class _FakeVisionLlm:
        async def ainvoke(self, messages):
            return _FakeVisionResp()

    def fake_bind_node_llm(llm, agent, params):
        return _FakeVisionLlm() if agent == "image_recognition" else llm

    fake_hub = _FakeHub()
    _patch_common(monkeypatch, fake_hub)
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {"image_recognition": {"model_ref": "custom-vision-1"}}},
    )
    monkeypatch.setattr("engine.modes.author_loop_skill_prefs.bind_node_llm", fake_bind_node_llm)
    aid = store_attachment("page.png", b"\x89PNG fake bytes")

    out = await read_attachment_image.ainvoke({"attachment_id": aid})

    assert "未返回有效描述" in out
    assert fake_hub.image_progress_calls == [{"ok": False, "error": "视觉模型未返回有效描述"}]


@pytest.mark.asyncio
async def test_read_attachment_calls_text_recognition_bound_llm(monkeypatch):
    """The existing text-import path must now route its distillation call through the
    text_recognition node override instead of always using the raw global default."""
    bind_calls: list[str] = []

    def fake_bind_node_llm(llm, agent, params):
        bind_calls.append(agent)
        return llm

    async def fake_distill(chunks, *, source, compaction_interval, llm, on_progress=None):
        return 1, []

    _patch_common(monkeypatch, _FakeHub())
    monkeypatch.setattr("engine.modes.author_loop_skill_prefs.bind_node_llm", fake_bind_node_llm)
    monkeypatch.setattr("engine.setup_chat.novel_import.run_distillation_from_chunks", fake_distill)
    aid = store_attachment("novel.txt", "内容".encode("utf-8"))

    await read_attachment.ainvoke({"attachment_id": aid})

    assert bind_calls == ["text_recognition"]


@pytest.mark.asyncio
async def test_read_attachment_images_runs_consolidation_pipeline(monkeypatch):
    bind_calls: list[str] = []

    def fake_bind_node_llm(llm, agent, params):
        bind_calls.append(agent)
        return llm

    consolidated: dict = {}

    async def fake_pipeline(images, *, vision_llm, consolidator_llm, batch_size, overlap, on_image_done=None):
        consolidated["count"] = len(images)
        return "整合后的跨页描述", [], []

    async def fake_distill(chunks, *, source, compaction_interval, llm, on_progress=None):
        consolidated["distill_text"] = chunks[0].text if chunks else ""
        return 2, []

    fake_hub = _FakeHub()
    _patch_common(monkeypatch, fake_hub)
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {"image_recognition": {"model_ref": "custom-vision-1"}}},
    )
    monkeypatch.setattr("engine.modes.author_loop_skill_prefs.bind_node_llm", fake_bind_node_llm)
    monkeypatch.setattr(
        "engine.setup_chat.image_batch_consolidator.run_vision_and_consolidation_pipeline",
        fake_pipeline,
    )
    monkeypatch.setattr("engine.setup_chat.novel_import.run_distillation_from_chunks", fake_distill)
    monkeypatch.setattr(
        "utils.config.get_config",
        lambda: {"novel_import": {"chunk_size": 10000, "compaction_interval": 5, "image_batch_size": 10, "image_batch_overlap": 2}},
    )
    a1 = store_attachment("1.jpg", b"\x89PNG")
    a2 = store_attachment("2.jpg", b"\x89PNG")

    out = await read_attachment_images.ainvoke({"attachment_ids": [a2, a1]})

    assert consolidated["count"] == 2
    assert consolidated["distill_text"] == "整合后的跨页描述"
    assert "识别完成" in out
    assert bind_calls == ["image_recognition", "text_recognition"]


def test_agent_registers_read_attachment_and_style_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "engine.setup_chat.agent.setup_chat_checkpoint_path",
        lambda: str(tmp_path / "cp.sqlite"),
    )
    import engine.setup_chat.agent as a

    src = inspect.getsource(a.build_agent)
    assert "read_attachment" in src
    assert "read_attachment_image" in src
    assert "read_attachment_images" in src
    assert "list_persisted_attachments" in src
    assert "read_persisted_attachment" in src
    assert "get_image_description" in src
    assert "build_prose_style_from_import" in src


@pytest.mark.asyncio
async def test_list_persisted_attachments_formats_manifest(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path / "novels"))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "n1")
    from engine.setup_chat.attachment_persistence import persist_attachment

    persist_attachment("n1", "id1", "2.jpg", b"x")
    persist_attachment("n1", "id2", "1.jpg", b"x")
    out = await list_persisted_attachments.ainvoke({})
    assert "id1" in out and "id2" in out
    assert out.index("1.jpg") < out.index("2.jpg")


@pytest.mark.asyncio
async def test_read_persisted_attachment_returns_text(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path / "novels"))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "n1")
    from engine.setup_chat.attachment_persistence import persist_attachment

    persist_attachment("n1", "doc1", "notes.txt", "参考设定".encode("utf-8"))
    out = await read_persisted_attachment.ainvoke({"attachment_id": "doc1"})
    assert "参考设定" in out
    assert "落盘附件" in out


@pytest.mark.asyncio
async def test_read_attachment_image_persists_description(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path / "novels"))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "n1")

    class _FakeVisionResp:
        content = "画面描述：赛博都市场景。"

    class _FakeVisionLlm:
        async def ainvoke(self, messages):
            return _FakeVisionResp()

    async def fake_distill(chunks, *, source, compaction_interval, llm, on_progress=None):
        return 1, []

    _patch_common(monkeypatch, _FakeHub())
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {"image_recognition": {"model_ref": "custom-vision-1"}}},
    )
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.bind_node_llm",
        lambda llm, agent, params: _FakeVisionLlm() if agent == "image_recognition" else llm,
    )
    monkeypatch.setattr("engine.setup_chat.novel_import.run_distillation_from_chunks", fake_distill)
    aid = store_attachment("page.png", b"\x89PNG fake bytes")

    await read_attachment_image.ainvoke({"attachment_id": aid})

    from engine.setup_chat.attachment_persistence import load_image_description

    assert load_image_description("n1", aid) == "画面描述：赛博都市场景。"


@pytest.mark.asyncio
async def test_read_persisted_attachment_image_uses_cached_description(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path / "novels"))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "n1")
    from engine.setup_chat.attachment_persistence import persist_attachment, persist_image_description

    persist_attachment("n1", "img1", "page.jpg", b"jpeg")
    persist_image_description("n1", "img1", "已落盘的视觉描述")

    vision_called = {"n": 0}

    async def fake_recognize(*_args, **_kwargs):
        vision_called["n"] += 1
        return "should not run"

    monkeypatch.setattr("engine.setup_chat.image_batch_consolidator.recognize_image", fake_recognize)

    out = await read_persisted_attachment.ainvoke({"attachment_id": "img1"})

    assert vision_called["n"] == 0
    assert "已落盘的视觉描述" in out
    assert "视觉描述" in out


@pytest.mark.asyncio
async def test_get_image_description_returns_persisted_text(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path / "novels"))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "n1")
    from engine.setup_chat.attachment_persistence import persist_attachment, persist_image_description

    persist_attachment("n1", "img1", "page.jpg", b"jpeg")
    persist_image_description("n1", "img1", "魁梧剑士站在城门口")

    out = await get_image_description.ainvoke({"attachment_id": "img1"})

    assert "魁梧剑士站在城门口" in out
    assert "page.jpg" in out


@pytest.mark.asyncio
async def test_get_image_description_missing_returns_hint(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path / "novels"))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "n1")
    from engine.setup_chat.attachment_persistence import persist_attachment

    persist_attachment("n1", "img1", "page.jpg", b"jpeg")

    out = await get_image_description.ainvoke({"attachment_id": "img1"})

    assert "尚无" in out
