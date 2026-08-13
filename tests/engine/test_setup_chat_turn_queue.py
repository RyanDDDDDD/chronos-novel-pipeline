from api.services.setup_chat_turn_queue import (
    SETUP_CHAT_TURN_QUEUE,
    SetupChatTurnItem,
    SetupChatTurnKind,
    SetupChatTurnQueue,
)


def test_enqueue_pop_fifo_per_novel():
    q = SetupChatTurnQueue()
    a = SetupChatTurnItem("n1", SetupChatTurnKind.SYSTEM_NOTICE, summary_text="first")
    b = SetupChatTurnItem("n1", SetupChatTurnKind.SYSTEM_NOTICE, summary_text="second")
    q.enqueue(a)
    q.enqueue(b)
    assert q.peek("n1") is a
    assert q.pop("n1") is a
    assert q.pop("n1") is b
    assert q.pop("n1") is None


def test_novels_are_isolated():
    q = SetupChatTurnQueue()
    q.enqueue(SetupChatTurnItem("a", SetupChatTurnKind.SYSTEM_NOTICE, summary_text="a"))
    q.enqueue(SetupChatTurnItem("b", SetupChatTurnKind.SYSTEM_NOTICE, summary_text="b"))
    assert q.len_for("a") == 1
    assert q.len_for("b") == 1
    assert q.pop("a").summary_text == "a"
    assert q.len_for("a") == 0


def test_clear_discards_pending():
    q = SetupChatTurnQueue()
    q.enqueue(SetupChatTurnItem("n", SetupChatTurnKind.SYSTEM_NOTICE, summary_text="x"))
    q.clear("n")
    assert q.len_for("n") == 0
    assert q.peek("n") is None


def test_module_singleton_exists():
    SETUP_CHAT_TURN_QUEUE.enqueue(
        SetupChatTurnItem("singleton-test", SetupChatTurnKind.SYSTEM_NOTICE, summary_text="t")
    )
    assert SETUP_CHAT_TURN_QUEUE.len_for("singleton-test") == 1
    SETUP_CHAT_TURN_QUEUE.clear("singleton-test")


def test_enqueue_or_merge_appends_when_queue_empty():
    q = SetupChatTurnQueue()
    q.enqueue_or_merge_system_notice("n", "first")
    assert q.len_for("n") == 1
    assert q.peek("n").summary_text == "first"


def test_enqueue_or_merge_merges_into_existing_pending_notice():
    q = SetupChatTurnQueue()
    q.enqueue_or_merge_system_notice("n", "character A fixed")
    q.enqueue_or_merge_system_notice("n", "chapter 5 skeleton fixed")
    q.enqueue_or_merge_system_notice("n", "timeline cascade done")

    assert q.len_for("n") == 1
    merged = q.peek("n").summary_text
    assert "character A fixed" in merged
    assert "chapter 5 skeleton fixed" in merged
    assert "timeline cascade done" in merged
    assert merged.index("character A fixed") < merged.index("chapter 5 skeleton fixed")
    assert merged.index("chapter 5 skeleton fixed") < merged.index("timeline cascade done")


def test_enqueue_or_merge_does_not_touch_already_popped_notice():
    """Merging must target only an item still sitting in the queue -- a notice already
    popped out for an in-flight turn is a separate run and must not be mutated."""
    q = SetupChatTurnQueue()
    q.enqueue_or_merge_system_notice("n", "first")
    popped = q.pop("n")
    q.enqueue_or_merge_system_notice("n", "second")

    assert popped.summary_text == "first"
    assert q.len_for("n") == 1
    assert q.peek("n").summary_text == "second"


def test_enqueue_or_merge_keeps_novels_isolated():
    q = SetupChatTurnQueue()
    q.enqueue_or_merge_system_notice("a", "notice for a")
    q.enqueue_or_merge_system_notice("b", "notice for b")
    assert q.len_for("a") == 1
    assert q.len_for("b") == 1
    assert q.peek("a").summary_text == "notice for a"
    assert q.peek("b").summary_text == "notice for b"
