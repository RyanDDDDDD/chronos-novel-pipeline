from __future__ import annotations

import io

from PIL import Image

from media.portrait.reference_prep import fit_to_director_canvas


def _png(w: int, h: int, color: tuple[int, int, int] = (120, 40, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def _size(b: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(b)).size


def test_portrait_source_maps_to_portrait_canvas():
    assert _size(fit_to_director_canvas(_png(832, 1216))) == (1024, 1536)


def test_landscape_source_maps_to_landscape_canvas():
    assert _size(fit_to_director_canvas(_png(1600, 900))) == (1536, 1024)


def test_square_source_maps_to_square_canvas():
    assert _size(fit_to_director_canvas(_png(700, 700))) == (1472, 1472)


def test_scales_to_fit_and_black_pads_no_crop():
    out = fit_to_director_canvas(_png(400, 1600, (10, 200, 10)))
    img = Image.open(io.BytesIO(out)).convert("RGB")
    assert img.size == (1024, 1536)
    assert img.getpixel((512, 768)) == (10, 200, 10)   # center = source
    assert img.getpixel((5, 768)) == (0, 0, 0)          # left edge = pad


def test_accepts_rgba_source():
    buf = io.BytesIO()
    Image.new("RGBA", (832, 1216), (1, 2, 3, 255)).save(buf, format="PNG")
    assert _size(fit_to_director_canvas(buf.getvalue())) == (1024, 1536)
