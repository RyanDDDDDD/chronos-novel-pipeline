import pytest

from engine.setup_chat.attachment_persistence import (
    persist_attachment,
    persist_image_description,
)
from engine.setup_chat.style_source_rebuild import (
    load_style_source_text_from_persisted,
    rebuild_style_source_chunks_from_persisted,
)


@pytest.fixture
def novel_id(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path / "novels"))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "n1")
    return "n1"


def test_load_style_source_prefers_text_attachments(novel_id):
    persist_attachment(novel_id, "img1", "1.jpg", b"x")
    persist_image_description(novel_id, "img1", "视觉描述")
    persist_attachment(novel_id, "txt1", "novel.txt", "真实原文第一段。".encode("utf-8"))

    text = load_style_source_text_from_persisted(novel_id)

    assert text == "真实原文第一段。"


def test_load_style_source_from_image_descriptions(novel_id):
    persist_attachment(novel_id, "a2", "2.jpg", b"x")
    persist_attachment(novel_id, "a1", "1.jpg", b"x")
    persist_image_description(novel_id, "a1", "第一页描述")
    persist_image_description(novel_id, "a2", "第二页描述")

    text = load_style_source_text_from_persisted(novel_id)

    assert "=== 第1页 (1.jpg) ===" in text
    assert "第一页描述" in text
    assert "=== 第2页 (2.jpg) ===" in text
    assert "第二页描述" in text


def test_rebuild_style_source_chunks(novel_id):
    persist_attachment(novel_id, "txt1", "novel.txt", ("段落" * 500).encode("utf-8"))

    chunks = rebuild_style_source_chunks_from_persisted(novel_id, chunk_size=500)

    assert chunks is not None
    assert len(chunks) >= 2
    assert chunks[0].index == 0


def test_rebuild_returns_none_when_no_persisted_source(novel_id):
    assert load_style_source_text_from_persisted(novel_id) is None
    assert rebuild_style_source_chunks_from_persisted(novel_id, chunk_size=1000) is None
