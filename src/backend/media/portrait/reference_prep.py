"""Resize a character reference image to one of NovelAI's Precise Reference canvases.

NovelAI's V4.5 Director/Precise Reference feature always uses one of three image sizes
(1024x1536 / 1472x1472 / 1536x1024, per docs.novelai.net/en/image/precisereference); a
smaller/larger image is upscaled/downscaled AND padded to reach one of them. We replicate
the official client's preprocessing: pick the canvas whose aspect ratio is closest to the
source (minimal padding), scale-to-fit, black-pad the remainder. No crop -- cropping a
portrait can lose the face."""
from __future__ import annotations

import io

from PIL import Image

_CANVASES: tuple[tuple[int, int], ...] = ((1024, 1536), (1472, 1472), (1536, 1024))


def fit_to_director_canvas(png_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    src_ar = img.width / img.height
    cw, ch = min(_CANVASES, key=lambda c: abs((c[0] / c[1]) - src_ar))
    scale = min(cw / img.width, ch / img.height)
    new_w, new_h = max(1, round(img.width * scale)), max(1, round(img.height * scale))
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGB", (cw, ch), (0, 0, 0))
    canvas.paste(resized, ((cw - new_w) // 2, (ch - new_h) // 2))
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()
