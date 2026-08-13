from io import BytesIO

import pytest
from PIL import Image

from engine.setup_chat.image_preprocess import (
    MAX_LONG_EDGE,
    ImagePreprocessError,
    prepare_image_for_vision,
    prepare_image_file_for_vision,
)


def _make_png_bytes(width: int, height: int, *, mode: str = "RGB") -> bytes:
    buf = BytesIO()
    if mode == "RGBA":
        Image.new("RGBA", (width, height), (255, 0, 0, 128)).save(buf, "PNG")
    else:
        Image.new("RGB", (width, height), "red").save(buf, "PNG")
    return buf.getvalue()


def test_prepare_image_outputs_jpeg():
    out = prepare_image_for_vision(_make_png_bytes(800, 600))
    assert out.startswith(b"\xff\xd8")


def test_prepare_image_downscales_large_image():
    out = prepare_image_for_vision(_make_png_bytes(3000, 2000))
    with Image.open(BytesIO(out)) as img:
        assert max(img.size) <= MAX_LONG_EDGE


def test_prepare_image_keeps_small_dimensions():
    out = prepare_image_for_vision(_make_png_bytes(800, 600))
    with Image.open(BytesIO(out)) as img:
        assert img.size == (800, 600)


def test_prepare_image_handles_rgba():
    out = prepare_image_for_vision(_make_png_bytes(400, 300, mode="RGBA"))
    with Image.open(BytesIO(out)) as img:
        assert img.mode == "RGB"


def test_prepare_image_rejects_invalid_bytes():
    with pytest.raises(ImagePreprocessError):
        prepare_image_for_vision(b"not an image")


def test_prepare_image_file_for_vision_writes_jpeg(tmp_path):
    src = tmp_path / "in.png"
    dst = tmp_path / "out.jpg"
    src.write_bytes(_make_png_bytes(1200, 900))
    size = prepare_image_file_for_vision(str(src), str(dst))
    assert size > 0
    assert dst.read_bytes().startswith(b"\xff\xd8")
