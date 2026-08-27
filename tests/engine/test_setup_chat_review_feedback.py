"""Unit tests for the setup-chat background-review feedback buffer + renderer."""
from __future__ import annotations

import pytest
from api.services.setup_chat_review_feedback import (
    REVIEW_FEEDBACK,
    ReviewFeedbackBuffer,
    ReviewFeedbackEntry,
    ReviewStatus,
    handle_review_timeout,
    render_review_feedback,
)


@pytest.fixture
def buf() -> ReviewFeedbackBuffer:
    return ReviewFeedbackBuffer()


def _entry(label: str, status: ReviewStatus = ReviewStatus.RESOLVED, body: str = "x") -> ReviewFeedbackEntry:
    return ReviewFeedbackEntry(kind="character", label=label, status=status, body=body)


def test_pending_aggregates_and_auto_clears_per_novel(buf: ReviewFeedbackBuffer) -> None:
    assert buf.has_pending("n") is False
    buf.mark_pending("n", ("character", "甲"))
    buf.mark_pending("n", ("character", "乙"))
    assert buf.has_pending("n") is True
    buf.clear_pending("n", ("character", "甲"))
    assert buf.has_pending("n") is True  # 乙 still pending
    buf.clear_pending("n", ("character", "乙"))
    assert buf.has_pending("n") is False
    # unrelated novel untouched
    buf.mark_pending("m", ("world",))
    assert buf.has_pending("n") is False and buf.has_pending("m") is True


def test_clear_pending_missing_key_is_noop(buf: ReviewFeedbackBuffer) -> None:
    buf.clear_pending("n", ("world",))  # must not raise
    assert buf.has_pending("n") is False


def test_mark_pending_is_idempotent(buf: ReviewFeedbackBuffer) -> None:
    buf.mark_pending("n", ("world",))
    buf.mark_pending("n", ("world",))
    buf.clear_pending("n", ("world",))
    assert buf.has_pending("n") is False


def test_record_keeps_insertion_order(buf: ReviewFeedbackBuffer) -> None:
    buf.record("n", ("a",), _entry("A"))
    buf.record("n", ("b",), _entry("B"))
    buf.record("n", ("c",), _entry("C"))
    assert [e.label for e in buf.snapshot("n")] == ["A", "B", "C"]


def test_record_same_key_replaces_in_place(buf: ReviewFeedbackBuffer) -> None:
    buf.record("n", ("a",), _entry("A"))
    buf.record("n", ("b",), _entry("B1"))
    buf.record("n", ("c",), _entry("C"))
    buf.record("n", ("b",), _entry("B2"))  # replace middle
    assert [e.label for e in buf.snapshot("n")] == ["A", "B2", "C"]


def test_clear_buffer_only_touches_one_novel(buf: ReviewFeedbackBuffer) -> None:
    buf.record("n", ("a",), _entry("A"))
    buf.record("m", ("a",), _entry("A"))
    buf.clear_buffer("n")
    assert buf.snapshot("n") == []
    assert [e.label for e in buf.snapshot("m")] == ["A"]


def test_bump_and_reset_attempt(buf: ReviewFeedbackBuffer) -> None:
    assert buf.bump_attempt("n", ("world",)) == 1
    assert buf.bump_attempt("n", ("world",)) == 2
    buf.reset_attempt("n", ("world",))
    assert buf.bump_attempt("n", ("world",)) == 1
    # independent keys
    assert buf.bump_attempt("n", ("skeleton", 3)) == 1


def test_clear_all_wipes_pending_buffer_and_attempts(buf: ReviewFeedbackBuffer) -> None:
    buf.mark_pending("n", ("world",))
    buf.record("n", ("world",), _entry("世界观"))
    buf.bump_attempt("n", ("world",))
    buf.clear_all("n")
    assert buf.has_pending("n") is False
    assert buf.snapshot("n") == []
    assert buf.bump_attempt("n", ("world",)) == 1  # counter was reset


def test_singleton_exists() -> None:
    assert isinstance(REVIEW_FEEDBACK, ReviewFeedbackBuffer)


def _e(label: str, status: ReviewStatus, body: str = "") -> ReviewFeedbackEntry:
    return ReviewFeedbackEntry(kind="character", label=label, status=status, body=body)


def test_render_all_clean_is_one_pass_line_no_notice() -> None:
    out = render_review_feedback([
        _e("世界观", ReviewStatus.CLEAN),
        _e("第2章骨架", ReviewStatus.CLEAN),
    ])
    assert "【通过，无需调整】世界观、第2章骨架" in out
    assert "不要据此再手动调用工具修改" not in out
    assert "共 2 项" in out


def test_render_mixed_collapses_clean_lists_others_and_appends_notice_once() -> None:
    out = render_review_feedback([
        _e("世界观", ReviewStatus.CLEAN),
        _e("角色「甲」", ReviewStatus.RESOLVED, "锚点太泛，已改具体。"),
        _e("第3章骨架", ReviewStatus.TIMEOUT, "第3章骨架的后台审查两次超时未完成，已放弃。"),
    ])
    assert "【通过，无需调整】世界观" in out
    assert "━━ 角色「甲」 ━━" in out
    assert "锚点太泛，已改具体。" in out
    assert "━━ 第3章骨架（超时） ━━" in out
    assert out.count("不要据此再手动调用工具修改") == 1
    # clean line comes before the detailed blocks
    assert out.index("【通过，无需调整】") < out.index("━━ 角色「甲」")


def test_render_preserves_entry_order_for_non_clean() -> None:
    out = render_review_feedback([
        _e("角色「乙」", ReviewStatus.RESOLVED, "b"),
        _e("角色「甲」", ReviewStatus.RESOLVED, "a"),
    ])
    assert out.index("角色「乙」") < out.index("角色「甲」")


def test_render_single_resolved_uses_standard_format() -> None:
    out = render_review_feedback([_e("世界观", ReviewStatus.RESOLVED, "基调不统一，已修。")])
    assert "共 1 项" in out
    assert "━━ 世界观 ━━" in out
    assert "基调不统一，已修。" in out
    assert "不要据此再手动调用工具修改" in out


@pytest.mark.asyncio
async def test_handle_review_timeout_retries_once_then_gives_up(monkeypatch) -> None:
    REVIEW_FEEDBACK.clear_all("n")
    retries: list[int] = []
    gave_up: list[int] = []
    reported: list[tuple] = []

    class _FakeHub:
        async def report_review_done(self, novel_id, pending_key, entries):
            reported.append((novel_id, pending_key, entries))

    monkeypatch.setattr("api.routes._hub_instance", lambda: _FakeHub())

    async def give_up():
        gave_up.append(1)

    key = ("character", "甲")

    # 1st timeout -> retry, no give_up, no report
    await handle_review_timeout(
        "n", key, kind="character", label="角色「甲」",
        retry=lambda: retries.append(1), give_up=give_up,
    )
    assert retries == [1] and gave_up == [] and reported == []

    # 2nd timeout -> give_up + TIMEOUT entry reported
    await handle_review_timeout(
        "n", key, kind="character", label="角色「甲」",
        retry=lambda: retries.append(1), give_up=give_up,
    )
    assert retries == [1]  # not retried again
    assert gave_up == [1]
    assert len(reported) == 1
    _nid, pkey, entries = reported[0]
    assert pkey == key
    (bkey, entry), = entries
    assert bkey == key
    assert entry.status is ReviewStatus.TIMEOUT
    assert "超时" in entry.body

    # attempt counter was reset after give-up
    assert REVIEW_FEEDBACK.bump_attempt("n", key) == 1
    REVIEW_FEEDBACK.clear_all("n")


