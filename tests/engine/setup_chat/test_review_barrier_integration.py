
import pytest
from api.services.message_hub import MessageHub
from api.services.setup_chat_review_feedback import (
    REVIEW_FEEDBACK,
    ReviewFeedbackEntry,
    ReviewStatus,
)


@pytest.fixture(autouse=True)
def _clean_review_feedback():
    from engine.setup_chat import character_background_review as cbr
    from engine.setup_chat import timeline_auto as ta
    from engine.setup_chat import world_background_review as wbr

    wbr._PENDING.clear()
    cbr._ACTIVE_CHARACTER_REVIEWS.clear()
    ta._CASCADE_PENDING.clear()
    REVIEW_FEEDBACK.clear_all("n")
    yield
    wbr._PENDING.clear()
    cbr._ACTIVE_CHARACTER_REVIEWS.clear()
    ta._CASCADE_PENDING.clear()
    REVIEW_FEEDBACK.clear_all("n")


@pytest.mark.asyncio
async def test_all_four_review_jobs_barrier_and_batch_flush(monkeypatch):
    """Integration test: world, character, skeleton, and timeline review jobs run in parallel.
    No system notice is triggered until ALL four have finished. Once the final job finishes,
    MessageHub flushes a single batched notice containing all four results."""
    hub = MessageHub()
    notices: list[tuple[str, str]] = []

    async def fake_trigger_notice(novel_id: str, summary: str):
        notices.append((novel_id, summary))

    monkeypatch.setattr(hub, "trigger_system_notice_turn", fake_trigger_notice)
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    # 1. Mark all 4 pending
    REVIEW_FEEDBACK.mark_pending("n", ("world",))
    REVIEW_FEEDBACK.mark_pending("n", ("character", "甲"))
    REVIEW_FEEDBACK.mark_pending("n", ("skeleton", 1))
    REVIEW_FEEDBACK.mark_pending("n", ("timeline",))

    assert REVIEW_FEEDBACK.has_pending("n") is True
    assert len(notices) == 0

    # 2. Complete world review (CLEAN)
    world_entry = ReviewFeedbackEntry("world", "世界观", ReviewStatus.CLEAN, "")
    await hub.report_review_done("n", ("world",), [(("world",), world_entry)])
    assert REVIEW_FEEDBACK.has_pending("n") is True
    assert len(notices) == 0

    # 3. Complete character review (RESOLVED)
    char_entry = ReviewFeedbackEntry("character", "角色「甲」", ReviewStatus.RESOLVED, "角色设定微调。")
    await hub.report_review_done("n", ("character", "甲"), [(("character", "甲"), char_entry)])
    assert REVIEW_FEEDBACK.has_pending("n") is True
    assert len(notices) == 0

    # 4. Complete skeleton review (CLEAN)
    skel_entry = ReviewFeedbackEntry("skeleton", "第1章骨架", ReviewStatus.CLEAN, "")
    await hub.report_review_done("n", ("skeleton", 1), [(("skeleton", 1), skel_entry)])
    assert REVIEW_FEEDBACK.has_pending("n") is True
    assert len(notices) == 0

    # 5. Complete timeline cascade (RESOLVED) -> This releases the barrier!
    time_entry = ReviewFeedbackEntry("timeline", "角色「甲」时间线", ReviewStatus.RESOLVED, "已重新推演。")
    await hub.report_review_done("n", ("timeline",), [(("timeline", "甲"), time_entry)])

    # Barrier is now cleared and notice should have fired exactly once
    assert REVIEW_FEEDBACK.has_pending("n") is False
    assert len(notices) == 1

    novel_id, text = notices[0]
    assert novel_id == "n"
    assert "本轮后台审查共 4 项：" in text
    assert "【通过，无需调整】世界观、第1章骨架" in text
    assert "━━ 角色「甲」 ━━" in text
    assert "角色设定微调。" in text
    assert "━━ 角色「甲」时间线 ━━" in text
    assert "已重新推演。" in text
    assert "以上均为后台自动审查与修复的结果" in text


@pytest.mark.asyncio
async def test_review_barrier_waits_for_busy_agent_then_flushes_on_turn_finish(monkeypatch):
    """When the setup-chat agent is busy processing a user turn, the flushed notice
    is held back until _on_setup_chat_turn_finished is called."""
    hub = MessageHub()
    notices: list[tuple[str, str]] = []

    async def fake_trigger_notice(novel_id: str, summary: str):
        notices.append((novel_id, summary))

    monkeypatch.setattr(hub, "trigger_system_notice_turn", fake_trigger_notice)
    monkeypatch.setattr("api.routes._hub_instance", lambda: hub)

    # Agent is busy
    monkeypatch.setattr(hub, "is_setup_chat_busy", lambda novel_id=None: True)

    REVIEW_FEEDBACK.mark_pending("n", ("world",))
    world_entry = ReviewFeedbackEntry("world", "世界观", ReviewStatus.RESOLVED, "世界观自动修复。")
    await hub.report_review_done("n", ("world",), [(("world",), world_entry)])

    # Pending cleared, but agent was busy -> no notice yet
    assert REVIEW_FEEDBACK.has_pending("n") is False
    assert len(notices) == 0

    # Agent finishes turn
    monkeypatch.setattr(hub, "is_setup_chat_busy", lambda novel_id=None: False)
    await hub._on_setup_chat_turn_finished("n")

    # Now flushed
    assert len(notices) == 1
    assert "世界观自动修复。" in notices[0][1]
