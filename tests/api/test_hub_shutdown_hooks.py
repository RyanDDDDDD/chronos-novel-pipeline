import pytest
from api.hub import register_shutdown_hooks
from api.services.scheduler import EventScheduler


class _FakeHub:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def shutdown(self) -> None:
        self.calls.append("shutdown")

    async def reset_all_setup_chat(self) -> None:
        self.calls.append("reset_all_setup_chat")

    async def reset_all_story_sandbox(self) -> None:
        self.calls.append("reset_all_story_sandbox")


@pytest.mark.asyncio
async def test_register_shutdown_hooks_runs_both_on_stop():
    s = EventScheduler()
    hub = _FakeHub()
    register_shutdown_hooks(s, hub)
    s.start()
    await s.stop()
    assert set(hub.calls) == {"shutdown", "reset_all_setup_chat", "reset_all_story_sandbox"}
