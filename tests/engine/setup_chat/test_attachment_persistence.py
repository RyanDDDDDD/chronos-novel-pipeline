import json
import os

import pytest

from engine.setup_chat.attachment_persistence import (
    delete_persisted_attachment,
    list_persisted_attachments,
    load_image_description,
    load_persisted_attachment_bytes,
    persist_attachment,
    persist_image_description,
)
from utils.paths import novel_attachments_dir


@pytest.fixture
def novel_id(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path / "novels"))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "n1")
    return "n1"


def test_persist_and_load_roundtrip(novel_id):
    persist_attachment(novel_id, "abc123", "page.png", b"jpeg bytes")
    loaded = load_persisted_attachment_bytes(novel_id, "abc123")
    assert loaded == ("page.png", b"jpeg bytes")
    file_path = os.path.join(novel_attachments_dir(novel_id), "abc123_page.png")
    assert os.path.isfile(file_path)


def test_list_natural_sorts_by_filename(novel_id):
    persist_attachment(novel_id, "a3", "10.jpg", b"x")
    persist_attachment(novel_id, "a1", "1.jpg", b"x")
    persist_attachment(novel_id, "a2", "2.jpg", b"x")
    names = [m.filename for m in list_persisted_attachments(novel_id)]
    assert names == ["1.jpg", "2.jpg", "10.jpg"]


def test_delete_removes_file_and_index_entry(novel_id):
    persist_attachment(novel_id, "abc123", "doc.txt", b"hello")
    delete_persisted_attachment(novel_id, "abc123")
    assert load_persisted_attachment_bytes(novel_id, "abc123") is None
    assert list_persisted_attachments(novel_id) == []


def test_persist_and_load_image_description(novel_id):
    persist_attachment(novel_id, "img1", "page.jpg", b"jpeg")
    persist_image_description(novel_id, "img1", "一名魁梧剑士站在城门口")
    assert load_image_description(novel_id, "img1") == "一名魁梧剑士站在城门口"


def test_list_marks_has_description_for_images(novel_id):
    persist_attachment(novel_id, "img1", "1.jpg", b"x")
    persist_attachment(novel_id, "txt1", "notes.txt", b"hello")
    persist_image_description(novel_id, "img1", "描述文本")
    metas = {m.attachment_id: m for m in list_persisted_attachments(novel_id)}
    assert metas["img1"].has_description is True
    assert metas["txt1"].has_description is False


def test_delete_removes_description_sidecar(novel_id):
    persist_attachment(novel_id, "img1", "page.jpg", b"x")
    persist_image_description(novel_id, "img1", "描述")
    delete_persisted_attachment(novel_id, "img1")
    assert load_image_description(novel_id, "img1") is None
    desc_path = os.path.join(novel_attachments_dir(novel_id), "img1_description.txt")
    assert not os.path.isfile(desc_path)


def test_load_attachment_parsed_content(novel_id):
    from engine.setup_chat.attachment_persistence import load_attachment_parsed_content

    persist_attachment(novel_id, "img1", "page.jpg", b"x")
    persist_image_description(novel_id, "img1", "描述")
    assert load_attachment_parsed_content(novel_id, "img1") == "描述"

    persist_attachment(novel_id, "txt1", "notes.txt", b"plain")
    assert load_attachment_parsed_content(novel_id, "txt1") == "plain"


def test_persist_replaces_duplicate_filename(novel_id):
    from engine.setup_chat.attachment_persistence import (
        find_persisted_attachment_id_by_filename,
        list_persisted_attachments,
    )
    from engine.setup_chat.attachments import store_attachment

    first_id = store_attachment("1.jpg", b"first")
    persist_image_description(novel_id, first_id, "旧描述")
    second_id = store_attachment("1.jpg", b"second")

    assert first_id == second_id
    assert find_persisted_attachment_id_by_filename(novel_id, "1.jpg") == first_id
    metas = list_persisted_attachments(novel_id)
    assert [m.filename for m in metas] == ["1.jpg"]
    loaded = load_persisted_attachment_bytes(novel_id, first_id)
    assert loaded == ("1.jpg", b"second")
    assert load_image_description(novel_id, first_id) is None
