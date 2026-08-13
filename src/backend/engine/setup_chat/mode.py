"""Process-global auto/manual mode flag for setup-chat.

In-memory only (never persisted) -- same trade-off already accepted by
skeleton_pipeline's _DIRECTION_SET/_LENS_CHOSEN and plan_runner's
_PENDING_REPAIR: losing it on restart is harmless, it just means the next
turn starts in manual (the safe default) until toggled again.
"""
from __future__ import annotations

_AUTO: bool = False

AUTO_MODE_BANNER = (
    "当前 AUTO 模式已开启：不逐字段访谈、不为选择题等待用户——按你的最佳判断自主决定"
    "所有细节（贴合已有 world/cast/plot 设定与用户这轮给的 brief），直接连续调用工具把"
    "这次请求要求的内容一次做完，最后用一段文字总结做了什么，供用户事后复核/编辑。"
    "只有当某个信息只有用户知道、你无法从现有设定或常理推断时，才停下来问。"
)

MANUAL_MODE_BANNER = (
    "当前 MANUAL (手动) 模式已开启：你需要通过交互式对话引导用户，逐步完成各项设定。"
    "不要一次性自主决定所有细节或擅自执行完所有工具调用。在处理每个模块时，你应该小步推进，"
    "向用户提问、提供明确的选项供用户选择，在获得用户的反馈或确认后再继续进行下一步。"
)


def is_auto_mode() -> bool:
    return _AUTO


def set_auto_mode(auto: bool) -> None:
    global _AUTO
    _AUTO = auto
