"""动作 delta hook：逐拍推角色当前姿势/动作，覆盖式（replace）。运行期专用。"""
from __future__ import annotations

from pathlib import Path

from engine.archive.archive_hook import ArchiveDeltaContext, ArchiveDeltaHook

_PROMPT = (Path(__file__).parent / "action_builder.md").read_text(encoding="utf-8")


class ActionHook(ArchiveDeltaHook):
    name = "action"
    fields = ["action"]
    merge = {"action": "replace"}

    def prompt_fragment(self, ctx: ArchiveDeltaContext) -> str:
        return _PROMPT

    def parse(self, field: str, raw_value, ctx: ArchiveDeltaContext):  # noqa: ANN001
        return str(raw_value).strip() if raw_value else ""
