import pytest
from engine.setup_chat import attachments as attachments_mod
from engine.setup_chat.attachments import (
    delete_attachment,
    describe_attachments,
    pop_attachment_text,
    store_attachment,
)


@pytest.fixture(autouse=True)
def _clear_store():
    attachments_mod._ATTACHMENTS.clear()
    yield
    attachments_mod._ATTACHMENTS.clear()


def test_store_and_pop_roundtrip():
    aid = store_attachment("novel.txt", "第一章内容".encode("utf-8"))
    assert pop_attachment_text(aid) == ("novel.txt", "第一章内容")


def test_pop_decodes_utf8_with_replace_on_bad_bytes():
    aid = store_attachment("bad.txt", b"\xff\xfe not valid utf-8 mixed with \xe4\xbd\xa0")
    filename, text = pop_attachment_text(aid)
    assert filename == "bad.txt"
    assert "你" in text  # valid trailing utf-8 sequence still decodes


def test_pop_is_one_time():
    aid = store_attachment("novel.txt", "内容".encode("utf-8"))
    pop_attachment_text(aid)
    assert pop_attachment_text(aid) is None


def test_pop_leaves_persisted_copy_on_disk(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path / "novels"))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "n1")
    from engine.setup_chat.attachment_persistence import load_persisted_attachment_bytes

    aid = store_attachment("novel.txt", "内容".encode("utf-8"))
    pop_attachment_text(aid)
    loaded = load_persisted_attachment_bytes("n1", aid)
    assert loaded == ("novel.txt", "内容".encode("utf-8"))


def test_delete_attachment_removes_persisted_copy(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path / "novels"))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "n1")
    from engine.setup_chat.attachment_persistence import load_persisted_attachment_bytes

    aid = store_attachment("novel.txt", "内容".encode("utf-8"))
    delete_attachment(aid)
    assert load_persisted_attachment_bytes("n1", aid) is None


def test_pop_unknown_id_returns_none():
    assert pop_attachment_text("nope") is None


def test_delete_removes_without_reading():
    aid = store_attachment("novel.txt", "内容".encode("utf-8"))
    delete_attachment(aid)
    assert pop_attachment_text(aid) is None


def test_delete_unknown_id_is_noop():
    delete_attachment("nope")  # must not raise


def test_store_image_attachment_keeps_filename_and_stores_jpeg():
    from io import BytesIO

    from PIL import Image

    from engine.setup_chat.attachments import pop_attachment_bytes, store_image_attachment

    buf = BytesIO()
    Image.new("RGB", (1200, 800), "green").save(buf, "PNG")
    aid = store_image_attachment("scan.png", buf.getvalue())
    popped = pop_attachment_bytes(aid)
    assert popped is not None
    filename, raw = popped
    assert filename == "scan.png"
    assert raw.startswith(b"\xff\xd8")


def test_describe_lists_present_attachments():
    a1 = store_attachment("1.txt", "x".encode("utf-8"))
    a2 = store_attachment("2.md", "y".encode("utf-8"))
    manifest = describe_attachments([a1, a2])
    assert a1 in manifest and "1.txt" in manifest
    assert a2 in manifest and "2.md" in manifest


def test_describe_skips_unknown_ids():
    a1 = store_attachment("1.txt", "x".encode("utf-8"))
    manifest = describe_attachments([a1, "ghost-id"])
    assert "ghost-id" not in manifest
    assert "1.txt" in manifest


def test_describe_empty_when_none_present():
    assert describe_attachments(["ghost"]) == ""


def test_describe_natural_sorts_by_filename():
    a10 = store_attachment("10.jpg", b"x")
    a2 = store_attachment("2.jpg", b"x")
    a1 = store_attachment("1.jpg", b"x")
    manifest = describe_attachments([a10, a2, a1])
    assert manifest.index("1.jpg") < manifest.index("2.jpg") < manifest.index("10.jpg")


def test_count_pending_images_counts_only_image_extensions():
    from engine.setup_chat.attachments import count_pending_images

    a = store_attachment("page.png", b"x")
    b = store_attachment("page.JPG", b"x")  # case-insensitive
    c = store_attachment("novel.txt", b"x")
    assert count_pending_images([a, b, c]) == 2


def test_count_pending_images_ignores_unknown_or_already_popped_ids():
    from engine.setup_chat.attachments import count_pending_images

    a = store_attachment("page.png", b"x")
    pop_attachment_text(a)  # consumes it (bytes reader would too; text reader is fine for this check)
    assert count_pending_images([a, "ghost"]) == 0


def test_count_pending_images_returns_zero_for_empty_list():
    from engine.setup_chat.attachments import count_pending_images

    assert count_pending_images([]) == 0


from engine.setup_chat.attachments import pop_attachment_bytes


def test_pop_bytes_roundtrip_without_utf8_decode():
    raw = b"\x89PNG\r\n\x1a\n not really a png but binary-ish \xff\xfe"
    aid = store_attachment("page.png", raw)
    assert pop_attachment_bytes(aid) == ("page.png", raw)


def test_pop_bytes_is_one_time():
    aid = store_attachment("page.png", b"\x89PNG")
    pop_attachment_bytes(aid)
    assert pop_attachment_bytes(aid) is None


def test_pop_bytes_unknown_id_returns_none():
    assert pop_attachment_bytes("nope") is None


def test_allowed_extensions_include_common_image_types():
    from engine.setup_chat.attachments import ALLOWED_EXTENSIONS
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        assert ext in ALLOWED_EXTENSIONS


def test_pop_attachment_images_batch_natural_order_and_atomic():
    from engine.setup_chat.attachments import pop_attachment_images_batch

    a10 = store_attachment("10.jpg", b"x")
    a2 = store_attachment("2.jpg", b"x")
    a1 = store_attachment("1.jpg", b"x")
    popped = pop_attachment_images_batch([a10, a2, a1])
    assert popped == [(a1, "1.jpg", b"x"), (a2, "2.jpg", b"x"), (a10, "10.jpg", b"x")]
    assert pop_attachment_images_batch([a1]) is None


def test_pop_attachment_images_batch_rejects_non_image_or_missing():
    from engine.setup_chat.attachments import pop_attachment_images_batch

    img = store_attachment("1.jpg", b"x")
    txt = store_attachment("1.txt", b"x")
    assert pop_attachment_images_batch([img, txt]) is None
    assert pop_attachment_images_batch([img, "ghost"]) is None
    assert pop_attachment_images_batch([img]) == [(img, "1.jpg", b"x")]
