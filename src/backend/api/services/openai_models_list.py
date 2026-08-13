"""Fetch and parse OpenAI-compatible GET {base_url}/models responses (local LM Studio, cloud proxies)."""
from __future__ import annotations

import httpx


def parse_openai_models_response(data: object) -> tuple[list[str], str | None]:
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return [], "返回的格式不符合 OpenAI /models 约定（缺少 data 数组）"
    models = [str(i["id"]) for i in items if isinstance(i, dict) and "id" in i]
    return models, None


async def fetch_openai_compatible_models(
    base_url: str,
    *,
    api_key: str = "",
    timeout: float = 5.0,
    connection_error_prefix: str = "无法连接推理服务",
) -> dict[str, object]:
    resolved = base_url.strip()
    if not resolved:
        return {"models": [], "error": "base_url 不能为空"}

    headers: dict[str, str] = {}
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{resolved.rstrip('/')}/models", headers=headers, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"models": [], "error": f"{connection_error_prefix}：{exc}"}

    models, fmt_err = parse_openai_models_response(data)
    if fmt_err:
        return {"models": [], "error": fmt_err}
    return {"models": models}
