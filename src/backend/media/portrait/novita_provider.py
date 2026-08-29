"""Novita AI txt2img client. Novita retired the old sync `/v3/txt2img` endpoint (it now
404s); generation is submit-then-poll: POST /v3/async/txt2img returns a task_id, then
GET /v3/async/task-result?task_id=... is polled until the task reaches a terminal status.
Verified against a live account 2026-08-10 -- re-verify against https://novita.ai/docs if
Novita changes the contract again."""
from __future__ import annotations

import asyncio
import random

import httpx

from media.portrait.provider import ImagePortraitProvider

_ASYNC_TXT2IMG_URL = "https://api.novita.ai/v3/async/txt2img"
_TASK_RESULT_URL = "https://api.novita.ai/v3/async/task-result"
_TIMEOUT_S = 60.0
_POLL_INTERVAL_S = 2.0
_POLL_MAX_ATTEMPTS = 30
# Portrait bucket -- 2:3, matches the cast grid card's aspect-[2/3] and NovelAI's native
# 832x1216. SDXL handles this ratio fine.
_WIDTH = 832
_HEIGHT = 1216
# Novita hard-rejects Txt2ImgRequest.Prompt/NegativePrompt above 1024 runes with a 400
# VALIDATOR error (confirmed live 2026-08-11) -- upstream tag composition (LLM-extracted
# visual tags + style preset + freeform text) has no length budget of its own, so this is
# the last line of defense before the request leaves the process.
_MAX_PROMPT_RUNES = 1024


def _clamp_to_novita_limit(text: str) -> str:
    if len(text) <= _MAX_PROMPT_RUNES:
        return text
    truncated = text[:_MAX_PROMPT_RUNES]
    # Cut back to the last complete comma-separated tag rather than chopping mid-tag.
    last_comma = truncated.rfind(",")
    return truncated[:last_comma] if last_comma > 0 else truncated


class NovitaImageProvider(ImagePortraitProvider):
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
        reference_strength: float = 0.7,
        reference_fidelity: float = 1.0,
    ) -> bytes:
        del char_captions, reference_strength, reference_fidelity  # not supported by Novita
        if character_references:
            raise RuntimeError(
                "场景生图的角色参考（Precise Reference）只支持 NovelAI V4.5，当前绑定的是 Novita"
            )
        headers = {"Authorization": f"Bearer {self._api_key}"}
        async with httpx.AsyncClient() as client:
            submit_resp = await client.post(
                _ASYNC_TXT2IMG_URL,
                json={
                    "extra": {"response_image_type": "jpeg"},
                    "request": {
                        "model_name": self._model,
                        "prompt": _clamp_to_novita_limit(prompt),
                        "negative_prompt": _clamp_to_novita_limit(negative_prompt),
                        "width": _WIDTH,
                        "height": _HEIGHT,
                        "image_num": 1,
                        "steps": 20,
                        "guidance_scale": 7,
                        "sampler_name": "Euler a",
                        # Explicit per-call random seed -- an omitted seed relies on
                        # whatever Novita defaults to, which regenerating the same
                        # character (unchanged prompt) would otherwise silently inherit.
                        "seed": random.randint(0, 2**32 - 1),
                    },
                },
                headers=headers,
                timeout=_TIMEOUT_S,
            )
            submit_resp.raise_for_status()
            task_id = submit_resp.json()["task_id"]

            image_url = await self._poll_for_image_url(client, task_id, headers)

            image_resp = await client.get(image_url, timeout=_TIMEOUT_S)
            image_resp.raise_for_status()
            return image_resp.content

    async def _poll_for_image_url(
        self, client: httpx.AsyncClient, task_id: str, headers: dict[str, str]
    ) -> str:
        for _ in range(_POLL_MAX_ATTEMPTS):
            result_resp = await client.get(
                _TASK_RESULT_URL,
                params={"task_id": task_id},
                headers=headers,
                timeout=_TIMEOUT_S,
            )
            result_resp.raise_for_status()
            body = result_resp.json()
            status = body["task"]["status"]
            if status == "TASK_STATUS_SUCCEED":
                return str(body["images"][0]["image_url"])
            if status == "TASK_STATUS_FAILED":
                reason = body["task"].get("reason", "")
                raise RuntimeError(f"Novita task {task_id} failed: {reason}")
            await asyncio.sleep(_POLL_INTERVAL_S)
        raise TimeoutError(f"Novita task {task_id} did not complete within polling budget")
