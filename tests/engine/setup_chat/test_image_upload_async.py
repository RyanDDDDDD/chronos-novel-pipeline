import asyncio
import io
import os

import pytest
from PIL import Image

from engine.setup_chat.image_upload_async import (
    ImageUploadStatus,
    begin_image_upload,
    cancel_image_upload,
    get_image_upload_status,
    schedule_image_compression,
    stream_upload_to_temp,
)
from utils.paths import novel_attachment_upload_temp_dir


def _make_png_file(path: str, width: int = 400, height: int = 300) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", (width, height), "green").save(path, "PNG")


class _FakeUpload:
    def __init__(self, data: bytes, chunk_size: int = 128) -> None:
        self._data = data
        self._chunk_size = chunk_size
        self._pos = 0

    async def read(self, size: int = -1) -> bytes:
        if self._pos >= len(self._data):
            return b""
        take = self._chunk_size if size < 0 else min(size, self._chunk_size)
        chunk = self._data[self._pos : self._pos + take]
        self._pos += len(chunk)
        return chunk


@pytest.mark.asyncio
async def test_stream_upload_to_temp_writes_in_chunks(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path / "novels"))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "n1")
    dest = os.path.join(novel_attachment_upload_temp_dir("n1"), "chunked.png")
    payload = b"x" * 500
    await stream_upload_to_temp(_FakeUpload(payload), dest)
    assert open(dest, "rb").read() == payload


@pytest.mark.asyncio
async def test_schedule_image_compression_finalizes_attachment(monkeypatch, tmp_path):
    from api.services.scheduler import EventScheduler
    from engine.setup_chat import attachments as attachments_mod
    from engine.setup_chat import image_upload_async as upload_mod

    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path / "novels"))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "n1")
    scheduler = EventScheduler()
    monkeypatch.setattr("api.services.scheduler.SCHEDULER", scheduler)

    attachment_id, input_path = begin_image_upload("n1", "page.png")
    _make_png_file(input_path)
    schedule_image_compression(attachment_id)
    scheduler.start()
    deadline = asyncio.get_running_loop().time() + 5.0
    while asyncio.get_running_loop().time() < deadline:
        if attachment_id in attachments_mod._ATTACHMENTS:
            break
        await asyncio.sleep(0.05)
    await scheduler.stop()
    await upload_mod.shutdown_image_process_pool()

    assert get_image_upload_status(attachment_id) is None
    assert attachment_id in attachments_mod._ATTACHMENTS
    assert attachments_mod._ATTACHMENTS[attachment_id].raw.startswith(b"\xff\xd8")


def test_cancel_image_upload_drops_processing_job(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path / "novels"))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "n1")
    attachment_id, input_path = begin_image_upload("n1", "page.png")
    _make_png_file(input_path)
    cancel_image_upload(attachment_id)
    assert get_image_upload_status(attachment_id) is None
    assert not os.path.isfile(input_path)
