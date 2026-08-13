from engine.author_loop.review.review_loader import get_review_hook_card


def test_get_review_hook_card_known_hook_with_markdown():
    content = get_review_hook_card("style")
    assert content is not None
    assert len(content) > 0


def test_get_review_hook_card_code_only_hook_returns_none():
    assert get_review_hook_card("expansion_ratio") is None


def test_get_review_hook_card_unknown_name_returns_none():
    assert get_review_hook_card("../../etc/passwd") is None
    assert get_review_hook_card("not-a-real-hook") is None
