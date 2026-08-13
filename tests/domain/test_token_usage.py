from domain.token_usage import extract_usage


class _Resp:
    def __init__(self, usage):
        self.usage_metadata = usage


def test_extract_usage_full():
    r = _Resp({"input_tokens": 100, "output_tokens": 40,
               "input_token_details": {"cache_read": 30}})
    assert extract_usage(r) == (100, 40, 30)


def test_extract_usage_no_cache_detail():
    r = _Resp({"input_tokens": 10, "output_tokens": 5})
    assert extract_usage(r) == (10, 5, 0)


def test_extract_usage_missing_metadata():
    assert extract_usage(object()) == (0, 0, 0)
