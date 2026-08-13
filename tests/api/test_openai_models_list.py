"""Unit tests for OpenAI /models response parsing."""

from api.services.openai_models_list import parse_openai_models_response


def test_parse_openai_models_response_success():
    models, err = parse_openai_models_response({"data": [{"id": "a"}, {"id": "b"}]})
    assert models == ["a", "b"]
    assert err is None


def test_parse_openai_models_response_skips_bad_entries():
    models, err = parse_openai_models_response({"data": [{"id": "ok"}, "nope", {}]})
    assert models == ["ok"]
    assert err is None


def test_parse_openai_models_response_bad_shape():
    models, err = parse_openai_models_response({"items": []})
    assert models == []
    assert err is not None
