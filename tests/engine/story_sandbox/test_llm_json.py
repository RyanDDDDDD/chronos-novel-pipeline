from engine.story_sandbox.llm_json import extract_json_dict, extract_json_list


def test_extract_json_list_parses_clean_json():
    assert extract_json_list('["a", "b"]') == ["a", "b"]


def test_extract_json_list_strips_markdown_code_fence():
    assert extract_json_list('```json\n["a", "b"]\n```') == ["a", "b"]


def test_extract_json_list_strips_bare_code_fence_without_json_tag():
    assert extract_json_list('```\n["a", "b"]\n```') == ["a", "b"]


def test_extract_json_list_tolerates_leading_noise_via_bracket_slice():
    assert extract_json_list('以下是建议：["a", "b"]') == ["a", "b"]


def test_extract_json_list_returns_none_for_malformed_json():
    assert extract_json_list("不是JSON") is None


def test_extract_json_list_repairs_smart_quote_closing_last_element():
    raw = '```json\n["a", "b”]'
    assert extract_json_list(raw) == ["a", "b"]


def test_extract_json_list_repairs_smart_quote_before_next_element():
    raw = '["a”, "b"]'
    assert extract_json_list(raw) == ["a", "b"]


def test_extract_json_list_leaves_mid_string_smart_quote_untouched():
    raw = '["a’、继续的文字", "b"]'
    assert extract_json_list(raw) == ["a’、继续的文字", "b"]


def test_extract_json_list_returns_none_for_a_json_object():
    assert extract_json_list('{"a": 1}') is None


def test_extract_json_dict_parses_clean_json():
    assert extract_json_dict('{"甲": {"a": 1}}') == {"甲": {"a": 1}}


def test_extract_json_dict_strips_markdown_code_fence():
    assert extract_json_dict('```json\n{"甲": {"a": 1}}\n```') == {"甲": {"a": 1}}


def test_extract_json_dict_tolerates_leading_noise_via_brace_slice():
    assert extract_json_dict('这是结果：{"甲": {"a": 1}}') == {"甲": {"a": 1}}


def test_extract_json_dict_returns_none_for_malformed_json():
    assert extract_json_dict("不是JSON") is None


def test_extract_json_dict_returns_none_for_a_json_list():
    assert extract_json_dict("[1, 2, 3]") is None
