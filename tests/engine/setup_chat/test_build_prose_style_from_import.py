import pytest

from api.services.novels import get_prose_style
from engine.setup_chat import style_source_cache
from engine.setup_chat.attachment_tool import build_prose_style_from_import
from engine.setup_chat.novel_import import TextChunk
from tests.conftest import seed_registry_novel


@pytest.fixture(autouse=True)
def _clear_cache():
    style_source_cache._STYLE_SOURCE_CHUNKS.clear()
    yield
    style_source_cache._STYLE_SOURCE_CHUNKS.clear()


@pytest.fixture
def _seeded_novel(tmp_path, monkeypatch):
    novels_root = tmp_path / "novels"
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(novels_root))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "default")
    seed_registry_novel(
        novels_root,
        "default",
        "赛博都市",
        active=True,
        prose_style={"preset": "plain-direct", "custom_addendum": "保留项"},
    )
    return novels_root / "default"


def _patch_llm(monkeypatch):
    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: object())


@pytest.mark.asyncio
async def test_no_cached_chunks_returns_prompt_to_import_first():
    out = await build_prose_style_from_import.ainvoke({})

    assert "没有可用的导入原文" in out


@pytest.mark.asyncio
async def test_success_sets_active_style_and_keeps_custom_addendum(monkeypatch, _seeded_novel):
    style_source_cache.store_chunks("default", [TextChunk(index=0, text="内容")])

    async def fake_pipeline(chunks, *, novel_id, novel_title, concurrency, llm=None):
        assert novel_id == "default"
        assert novel_title == "赛博都市"
        return {
            "id": f"auto-{novel_id}", "name": f"《{novel_title}》风格", "rules": "r",
            "samples": {}, "source_novel_id": novel_id, "created_at": "2026-07-23T00:00:00+00:00",
        }

    _patch_llm(monkeypatch)
    monkeypatch.setattr(
        "engine.setup_chat.prose_style_extraction.run_style_extraction_pipeline", fake_pipeline,
    )

    out = await build_prose_style_from_import.ainvoke({})

    assert "《赛博都市》风格" in out
    assert get_prose_style("default") == {"preset": "auto-default", "custom_addendum": "保留项"}


@pytest.mark.asyncio
async def test_pipeline_returns_none_reports_no_material(monkeypatch, _seeded_novel):
    style_source_cache.store_chunks("default", [TextChunk(index=0, text="内容")])

    async def fake_pipeline(chunks, **_kwargs):
        return None

    _patch_llm(monkeypatch)
    monkeypatch.setattr(
        "engine.setup_chat.prose_style_extraction.run_style_extraction_pipeline", fake_pipeline,
    )

    out = await build_prose_style_from_import.ainvoke({})

    assert "未能从原文抽出足够素材" in out
    assert get_prose_style("default")["preset"] == "plain-direct"


@pytest.mark.asyncio
async def test_pipeline_exception_returns_friendly_error(monkeypatch, _seeded_novel):
    style_source_cache.store_chunks("default", [TextChunk(index=0, text="内容")])

    async def fake_pipeline(chunks, **_kwargs):
        raise RuntimeError("LLM 挂了")

    _patch_llm(monkeypatch)
    monkeypatch.setattr(
        "engine.setup_chat.prose_style_extraction.run_style_extraction_pipeline", fake_pipeline,
    )

    out = await build_prose_style_from_import.ainvoke({})

    assert "文风抽取失败" in out
    assert get_prose_style("default")["preset"] == "plain-direct"


@pytest.mark.asyncio
async def test_rebuilds_chunks_from_persisted_text_after_cache_miss(monkeypatch, _seeded_novel):
    from engine.setup_chat.attachment_persistence import persist_attachment

    persist_attachment("default", "txt1", "novel.txt", "导入原文用于文风。".encode("utf-8"))

    captured: dict = {}

    async def fake_pipeline(chunks, *, novel_id, novel_title, concurrency, llm=None):
        captured["first_chunk"] = chunks[0].text if chunks else ""
        return {
            "id": f"auto-{novel_id}", "name": f"《{novel_title}》风格", "rules": "r",
            "samples": {}, "source_novel_id": novel_id, "created_at": "2026-07-23T00:00:00+00:00",
        }

    _patch_llm(monkeypatch)
    monkeypatch.setattr(
        "utils.config.get_config",
        lambda: {"novel_import": {"chunk_size": 10000, "concurrency": 2}},
    )
    monkeypatch.setattr(
        "engine.setup_chat.prose_style_extraction.run_style_extraction_pipeline", fake_pipeline,
    )

    out = await build_prose_style_from_import.ainvoke({})

    assert "《赛博都市》风格" in out
    assert "导入原文用于文风" in captured["first_chunk"]
