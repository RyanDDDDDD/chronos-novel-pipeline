"""Static social relationship rendering (师徒/姐妹/长辈 etc. from relationship_graph.json)."""
from __future__ import annotations

import hooks.archive.social_relations.social_relations as social_relations


def _patch_graph(monkeypatch, graph):
    monkeypatch.setattr(social_relations, "load_graph", lambda: graph)


def test_relations_includes_edges(monkeypatch):
    graph = {"groups": {}, "edges": {"甲→乙": {"from": "甲", "to": "乙", "nature": "师徒",
             "relationship_anchor": ""}}}
    _patch_graph(monkeypatch, graph)
    out = social_relations.relations_for_character("甲", ["甲", "乙"])
    assert "乙" in out and "师徒" in out


def test_relations_includes_groups(monkeypatch):
    graph = {"groups": {"g1": {"members": ["甲", "乙"], "type": "姐妹", "priority": 5}}, "edges": {}}
    _patch_graph(monkeypatch, graph)
    out = social_relations.relations_for_character("甲", ["甲", "乙"])
    assert "姐妹" in out and "乙" in out


def test_relations_empty_when_nothing(monkeypatch):
    _patch_graph(monkeypatch, {"groups": {}, "edges": {}})
    assert social_relations.relations_for_character("孤", ["孤", "甲"]) == ""


def test_relations_filters_offstage(monkeypatch):
    graph = {"groups": {}, "edges": {"甲→丙": {"from": "甲", "to": "丙", "nature": "师徒",
             "relationship_anchor": ""}}}
    _patch_graph(monkeypatch, graph)
    #丙 not in present roster -> filtered out
    out = social_relations.relations_for_character("甲", ["甲", "乙"])
    assert "丙" not in out


def test_relations_reverse_direction_edge(monkeypatch):
    graph = {"groups": {}, "edges": {"乙→甲": {"from": "乙", "to": "甲", "nature": "长幼",
             "relationship_anchor": ""}}}
    _patch_graph(monkeypatch, graph)
    out = social_relations.relations_for_character("甲", ["甲", "乙"])
    assert "乙" in out and "长幼" in out


def test_relations_empty_name(monkeypatch):
    _patch_graph(monkeypatch, {"groups": {}, "edges": {}})
    assert social_relations.relations_for_character("", ["甲"]) == ""
