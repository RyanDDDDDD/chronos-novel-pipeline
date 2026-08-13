def test_defaults_to_manual():
    from engine.setup_chat.mode import is_auto_mode
    assert is_auto_mode() is False


def test_set_and_read_auto_mode():
    from engine.setup_chat.mode import is_auto_mode, set_auto_mode
    set_auto_mode(True)
    try:
        assert is_auto_mode() is True
    finally:
        set_auto_mode(False)  # don't leak state into other tests


def test_banner_mentions_auto_and_no_wait():
    from engine.setup_chat.mode import AUTO_MODE_BANNER
    assert "AUTO" in AUTO_MODE_BANNER
    assert isinstance(AUTO_MODE_BANNER, str) and AUTO_MODE_BANNER.strip()
