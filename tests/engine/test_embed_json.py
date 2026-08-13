"""embed_json: parse_embed_json (weak model fault tolerance)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "backend"))

from engine.execution.embed_json import parse_embed_json


def test_parse_embed_json_strips_code_fence():
    fenced = '```json\n[{"id":1,"anchor":"x"}]\n```'
    out = parse_embed_json(fenced)
    assert out == [{"id": 1, "anchor": "x"}]


def test_parse_embed_json_array_and_chatter():
    assert parse_embed_json('[{"id":1,"anchor":"x"}]') == [{"id": 1, "anchor": "x"}]
    assert parse_embed_json('好的：\n[{"id":1,"anchor":"y"}]\n以上') == [{"id": 1, "anchor": "y"}]


def test_parse_embed_json_single_object_wrapped():
    assert parse_embed_json('{"score": 7, "pass": true}') == [{"score": 7, "pass": True}]


def test_parse_embed_json_ndjson_loose():
    #NDJSON / missing comma scattered objects → cut out one by one
    out = parse_embed_json('{"id":1}\n{"id":2}')
    assert {"id": 1} in out and {"id": 2} in out


def test_parse_embed_json_garbage_and_empty():
    assert parse_embed_json("不是 JSON") == []
    assert parse_embed_json("") == []
