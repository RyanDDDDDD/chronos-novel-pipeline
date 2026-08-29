"""NovelAI Diffusion image client -- portrait (txt2img) + sandbox scene (multi-character +
Precise/Director Reference). Synchronous single-shot (unlike Novita's submit-then-poll):
POST /ai/generate-image blocks ~5-15s and returns a ZIP archive (Content-Type:
binary/octet-stream, no Content-Length) whose sole entry is image_0.png. Persistent API
token auth (NovelAI account settings -> Account -> Get Persistent API Token; requires an
active paid subscription -- HTTP 402 otherwise).

Verified against a live Tablet-tier account 2026-08-28: nai-diffusion-5-full / -curated
work on Tablet; the v4_prompt / v4_negative_prompt objects are REQUIRED (a flat input +
negative_prompt alone returns HTTP 500); 832x1216 @ 28 steps costs no Anlas on any paid
tier.

Precise Reference (2026-08-29, reverse-engineered from the official web client's F12/HAR
via github.com/2786886095/novelai-image-desktop, then smoke-tested with a live token): a
request carrying reference images is multipart/form-data, NOT JSON -- a plain JSON body
with director_reference_images:[base64] is silently ignored. The images ride as binary
parts director_ref_N; the JSON `request` part references them via
director_reference_images_cached. V4.5 only. See
docs/superpowers/specs/2026-08-29-sandbox-scene-image-gen-design.md.

If the contract changes, adjust _base_parameters / _add_precise_reference / generate only."""
from __future__ import annotations

import hashlib
import io
import json
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

_DIRECTOR_STRENGTH_DEFAULT = 0.7
_MAX_REFERENCES = 6


def _center() -> dict:
    return {"centers": [{"x": 0.5, "y": 0.5}]}


def _base_parameters(
    prompt: str, negative_prompt: str, char_captions: list[dict] | None,
) -> dict:
    caps = char_captions or []
    neg_caps = [{"char_caption": "", **_center()} for _ in caps]
    return {
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
            "caption": {"base_caption": prompt, "char_captions": caps},
            "use_coords": False,
            "use_order": True,
        },
        "v4_negative_prompt": {
            "caption": {"base_caption": negative_prompt, "char_captions": neg_caps},
        },
    }


def _add_precise_reference(
    parameters: dict, prepped: list[bytes], strength: float, fidelity: float,
) -> None:
    parameters["director_reference_images_cached"] = [
        {"cache_secret_key": hashlib.sha256(b).hexdigest(), "data": f"director_ref_{i}"}
        for i, b in enumerate(prepped)
    ]
    parameters["normalize_reference_strength_multiple"] = True
    parameters["director_reference_descriptions"] = [
        {"caption": {"base_caption": "character", "char_captions": []}, "legacy_uc": False}
        for _ in prepped
    ]
    parameters["director_reference_strength_values"] = [round(strength, 2)] * len(prepped)
    parameters["director_reference_secondary_strength_values"] = [round(1 - fidelity, 2)] * len(prepped)
    # NovelAI's Precise Reference UI exposes only Strength and Fidelity; this transport
    # field is always 1 in the official client.
    parameters["director_reference_information_extracted"] = [1] * len(prepped)


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

    async def generate(
        self,
        prompt: str,
        *,
        negative_prompt: str = "",
        char_captions: list[dict] | None = None,
        character_references: list[bytes] | None = None,
        reference_strength: float = _DIRECTOR_STRENGTH_DEFAULT,
        reference_fidelity: float = 1.0,
    ) -> bytes:
        """`char_captions` items are already-shaped dicts
        `{"char_caption": str, "centers": [{"x": .5, "y": .5}]}`. `character_references` are
        raw PNG bytes (resized here) -- one per character to anchor via Precise Reference;
        V4.5 only."""
        from media.portrait.reference_prep import fit_to_director_canvas

        refs = character_references or []
        if refs and "4-5" not in self._model:
            raise RuntimeError(
                "Precise Reference 仅 V4.5 模型支持，请到「服务」页把场景生图模型设为 "
                "nai-diffusion-4-5-full / nai-diffusion-4-5-curated"
            )

        parameters = _base_parameters(prompt, negative_prompt, char_captions)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Origin": "https://novelai.net",
            "Referer": "https://novelai.net/",
        }

        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            if not refs:
                headers["Content-Type"] = "application/json"
                payload = {
                    "input": prompt, "model": self._model, "action": "generate",
                    "parameters": parameters,
                }
                resp = await client.post(_GENERATE_URL, json=payload, headers=headers)
            else:
                prepped = [fit_to_director_canvas(b) for b in refs[:_MAX_REFERENCES]]
                _add_precise_reference(
                    parameters, prepped, reference_strength, reference_fidelity,
                )
                # NB: no director_reference_images key in the JSON -- the images are the
                # director_ref_N binary parts, referenced via *_cached.
                request_json = {
                    "input": prompt, "model": self._model, "action": "generate",
                    "parameters": parameters,
                }
                files: dict = {
                    "request": (None, json.dumps(request_json), "application/json"),
                }
                for i, b in enumerate(prepped):
                    files[f"director_ref_{i}"] = (f"director_ref_{i}", b, "image/png")
                # httpx builds multipart/form-data with the right boundary from `files`.
                resp = await client.post(_GENERATE_URL, files=files, headers=headers)

            if resp.status_code == 402:
                raise RuntimeError("NovelAI 拒绝生成：订阅未激活或 Anlas 点数不足（HTTP 402）")
            resp.raise_for_status()
            return _extract_image(resp.content)
