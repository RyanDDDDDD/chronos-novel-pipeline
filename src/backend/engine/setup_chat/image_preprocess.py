"""Local Pillow preprocessing for setup-chat image attachments before in-memory storage."""

from __future__ import annotations

import os
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_LONG_EDGE = 2048
JPEG_QUALITY = 85


class ImagePreprocessError(Exception):
    """Raised when raw bytes cannot be decoded as a supported image."""


def _encode_rgb_as_jpeg(rgb: Image.Image) -> bytes:
    buf = BytesIO()
    rgb.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def _prepare_opened_image(opened: Image.Image) -> bytes:
    oriented = ImageOps.exif_transpose(opened)
    rgb = _to_rgb(oriented)
    if max(rgb.size) > MAX_LONG_EDGE:
        rgb.thumbnail((MAX_LONG_EDGE, MAX_LONG_EDGE), Image.Resampling.LANCZOS)
    return _encode_rgb_as_jpeg(rgb)


def prepare_image_for_vision(raw: bytes) -> bytes:
    """Decode, normalize orientation/colorspace, downscale if needed, return JPEG bytes."""
    try:
        with Image.open(BytesIO(raw)) as opened:
            return _prepare_opened_image(opened)
    except UnidentifiedImageError as exc:
        raise ImagePreprocessError("无法识别为有效图片") from exc
    except OSError as exc:
        raise ImagePreprocessError("图片解码失败") from exc


def prepare_image_file_for_vision(src_path: str, dst_path: str) -> int:
    """Read image from disk, write JPEG to dst_path. Returns output size in bytes."""
    try:
        with Image.open(src_path) as opened:
            jpeg = _prepare_opened_image(opened)
    except UnidentifiedImageError as exc:
        raise ImagePreprocessError("无法识别为有效图片") from exc
    except OSError as exc:
        raise ImagePreprocessError("图片解码失败") from exc
    os.makedirs(os.path.dirname(dst_path) or ".", exist_ok=True)
    with open(dst_path, "wb") as f:
        f.write(jpeg)
    return len(jpeg)


def compress_image_file_worker(input_path: str, output_path: str) -> int:
    """ProcessPool entrypoint: path-only IPC, returns compressed JPEG size in bytes."""
    return prepare_image_file_for_vision(input_path, output_path)


def _to_rgb(img: Image.Image) -> Image.Image:
    """RGBA/P → white-backed RGB; other modes → RGB."""
    if img.mode in ("RGBA", "P"):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[3])
        return background
    if img.mode != "RGB":
        return img.convert("RGB")
    return img
