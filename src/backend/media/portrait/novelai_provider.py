"""NovelAI Diffusion txt2img client. Synchronous single-shot (unlike Novita's
submit-then-poll): POST /ai/generate-image blocks ~5-15s and returns a ZIP archive
(Content-Type: binary/octet-stream, no Content-Length) whose sole entry is image_0.png.
Persistent API token auth (NovelAI account settings -> Account -> Get Persistent API
Token; requires an active paid subscription -- HTTP 402 otherwise).

Verified against a live Tablet-tier account 2026-08-28: nai-diffusion-5-full / -curated
work on Tablet; the v4_prompt / v4_negative_prompt objects are REQUIRED (a flat input +
negative_prompt alone returns HTTP 500); 832x1216 @ 28 steps costs no Anlas on any paid
tier. If the contract changes, adjust _build_payload / _extract_image only -- the
generate() skeleton stays."""
from __future__ import annotations

import io
import random
import zipfile

import httpx

from media.portrait.provider import ImagePortraitProvider

_GENERATE_URL = "https://image.novelai.net/ai/generate-image"
_TIMEOUT_S = 120.0

# NAI native portrait bucket (~2:3, matches the cast grid card's aspect-[2/3]).
_WIDTH = 832
_HEIGHT = 1216
_STEPS = 28
_SCALE = 5.0
_SAMPLER = "k_euler_ancestral"


def _build_payload(prompt: str, negative_prompt: str, model: str) -> dict:
    return {
        "input": prompt,
        "model": model,
        "action": "generate",
        "parameters": {
            "params_version": 3,
            "width": _WIDTH,
            "height": _HEIGHT,
            "scale": _SCALE,
            "sampler": _SAMPLER,
            "steps": _STEPS,
            "n_samples": 1,
            "seed": random.randint(0, 2**32 - 1),
            "ucPreset": 0,          # server-injects a baseline undesired-content set
            "qualityToggle": True,  # server-appends NAI quality tags
            "negative_prompt": negative_prompt,
            "noise_schedule": "karras",
            # REQUIRED by V4.5/V5 -- a flat input + negative_prompt alone returns HTTP 500.
            "v4_prompt": {
                "caption": {"base_caption": prompt, "char_captions": []},
                "use_coords": False,
                "use_order": True,
            },
            "v4_negative_prompt": {
                "caption": {"base_caption": negative_prompt, "char_captions": []},
            },
        },
    }


def _extract_image(zip_bytes: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        if not names:
            raise RuntimeError("NovelAI 返回的 ZIP 为空")
        return zf.read(names[0])


class NovelAIImageProvider(ImagePortraitProvider):
    def __init__(self, *, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    async def generate(self, prompt: str, *, negative_prompt: str = "") -> bytes:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Origin": "https://novelai.net",
            "Referer": "https://novelai.net/",
        }
        payload = _build_payload(prompt, negative_prompt, self._model)
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.post(_GENERATE_URL, json=payload, headers=headers)
            if resp.status_code == 402:
                raise RuntimeError("NovelAI 拒绝生成：订阅未激活或 Anlas 点数不足（HTTP 402）")
            resp.raise_for_status()
            return _extract_image(resp.content)
