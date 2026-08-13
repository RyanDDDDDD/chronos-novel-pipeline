"""Slash hard-gate + plan-state injection from plan_runner."""
from __future__ import annotations

import json
import re

from engine.setup_chat.skills import (
    expand_skill_placeholders,
    list_skill_index,
    load_skill_body,
)

_ACTIVATION_HEADER = "## 当前阶段引导（请据此进行；勿向用户复述本段）"
_SLASH_RE = re.compile(r"^/([A-Za-z0-9_-]+)(?:\s|$)")


def parse_slash_command(text: str) -> str | None:
    """Message starts with /name → return name; explicit slash is a hard gate."""
    m = _SLASH_RE.match((text or "").strip())
    return m.group(1) if m else None


def _last_human_text(messages: list) -> str:
    for m in reversed(messages or []):
        if getattr(m, "type", None) == "human" or (isinstance(m, dict) and m.get("type") == "human"):
            c = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
            return c if isinstance(c, str) else ""
    return ""


def build_skill_activations(messages: list, skills_dirs: list[str]) -> list[str]:
    """Skill bodies to inject this turn (slash hard-gate only; plan injection is separate)."""
    try:
        last_text = _last_human_text(messages)
        index = list_skill_index(skills_dirs)
        slash = parse_slash_command(last_text)
        if slash and any(it["name"] == slash for it in index):
            body = load_skill_body(slash, skills_dirs)
            if body:
                return [expand_skill_placeholders(body, skills_dirs)]
        return []
    except (OSError, json.JSONDecodeError):
        return []


def strip_activation_for_display(content: str) -> str:
    """Remove the activation injection block for occasional retelling of the model."""
    if _ACTIVATION_HEADER not in content:
        return content
    return content.split(_ACTIVATION_HEADER, 1)[0].rstrip()
