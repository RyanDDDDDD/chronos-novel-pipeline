"""Relational graph data layer: append-only edge log + fold-on-read + mutual derivation."""
from __future__ import annotations

from engine.setup.cast.relationship_graph import (
    append_edge,
    directed_edge,
    edges_for_character,
    empty_graph,
    iter_edges,
    iter_edges_by_key,
    iter_groups,
    load_graph,
    merge_overlay,
    peer_label,
    related_to_present,
    remove_edge,
    render_overview,
    validate_edge,
)

_EDGE_AB = {
    "from": "男主", "to": "女甲", "nature": "征服-占有", "relationship_anchor": "病态占有",
    "from_ref_terms": [], "to_ref_terms": ["主人"],
}
_EDGE_AC = {
    "from": "男主", "to": "女乙", "nature": "征服-占有", "relationship_anchor": "",
    "from_ref_terms": [], "to_ref_terms": [],
}


def _seed_edges_from_jsonl_bytes(db_path: str, content: bytes) -> None:
    import json

    from repositories.sqlite_store import get_connection
    from scripts.migrate_json_to_sqlite import _clean_ref_terms, _parse_relationship_edge_line

    conn = get_connection(db_path)
    conn.execute("DELETE FROM relationship_edges")
    for raw_line in content.splitlines():
        edge = _parse_relationship_edge_line(raw_line)
        if edge is None:
            continue
        frm = str(edge.get("from", "")).strip()
        to = str(edge.get("to", "")).strip()
        conn.execute(
            "INSERT INTO relationship_edges (from_name, to_name, nature, relationship_anchor,"
            " from_ref_terms_json, to_ref_terms_json, deleted) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                frm,
                to,
                str(edge.get("nature", "")),
                str(edge.get("relationship_anchor", "")),
                json.dumps(_clean_ref_terms(edge.get("from_ref_terms"))),
                json.dumps(_clean_ref_terms(edge.get("to_ref_terms"))),
                1 if edge.get("deleted") else 0,
            ),
        )
    conn.commit()


def test_empty_graph_is_dict_keyed():
    assert empty_graph() == {"groups": {}, "edges": {}}


def test_load_missing_returns_empty(tmp_path):
    assert load_graph(str(tmp_path / "nope.sqlite3")) == empty_graph()


def test_append_then_load_roundtrip(tmp_path):
    p = str(tmp_path / "edges.sqlite3")
    append_edge(_EDGE_AB, path=p)
    append_edge(_EDGE_AC, path=p)
    g = load_graph(p)
    assert g["groups"] == {}
    assert g["edges"]["男主→女甲"]["nature"] == "征服-占有"
    assert g["edges"]["男主→女乙"]["to_ref_terms"] == []


def test_append_does_not_read_existing_content(tmp_path):
    """核心不变量：append_edge 是纯追加，不依赖读取现有内容——多次调用互不干扰，
    模拟并发场景下两个后台任务各自 append 自己的边。"""
    p = str(tmp_path / "edges.sqlite3")
    append_edge(_EDGE_AB, path=p)
    append_edge(_EDGE_AC, path=p)
    append_edge({**_EDGE_AB, "nature": "青梅竹马"}, path=p)  # 同一对 from→to 的第二条
    g = load_graph(p)
    assert len(g["edges"]) == 2  # 男主→女甲、男主→女乙
    assert g["edges"]["男主→女甲"]["nature"] == "青梅竹马"  # 后写覆盖前写


def test_load_skips_corrupt_lines(tmp_path):
    import json

    db_path = str(tmp_path / "edges.sqlite3")
    content = (
        json.dumps(_EDGE_AB, ensure_ascii=False) + "\n"
        + "not valid json\n"
        + json.dumps(_EDGE_AC, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    _seed_edges_from_jsonl_bytes(db_path, content)
    g = load_graph(db_path)
    assert set(g["edges"]) == {"男主→女甲", "男主→女乙"}


def test_load_skips_line_with_invalid_utf8_bytes(tmp_path):
    """一行是坏字节（非法 UTF-8 起始字节，如磁盘/编辑损坏留下的残片）不该整图读取失败——
    跟 JSON 非法行一样只跳过这一行，其它行照常折叠进来。"""
    import json

    db_path = str(tmp_path / "edges.sqlite3")
    good_a = json.dumps(_EDGE_AB, ensure_ascii=False).encode("utf-8")
    good_c = json.dumps(_EDGE_AC, ensure_ascii=False).encode("utf-8")
    bad_line = b"\x97" + "残缺行".encode("utf-8")
    _seed_edges_from_jsonl_bytes(db_path, good_a + b"\n" + bad_line + b"\n" + good_c + b"\n")
    g = load_graph(db_path)
    assert set(g["edges"]) == {"男主→女甲", "男主→女乙"}


def test_iter_edges_reads_appended_form():
    g = {"groups": {}, "edges": {"男主→女甲": _EDGE_AB}}
    e = iter_edges(g)[0]
    assert e["from"] == "男主" and e["to"] == "女甲"
    assert e["to_ref_terms"] == ["主人"]


def test_directed_edge_lookup():
    g = {"groups": {}, "edges": {"男主→女甲": _EDGE_AB}}
    e = directed_edge(g, "男主", "女甲")
    assert e is not None and e["nature"] == "征服-占有"
    assert directed_edge(g, "女甲", "男主") is None


def test_render_overview_full():
    g = {"groups": {}, "edges": {"男主→女甲": _EDGE_AB}}
    out = render_overview(g)
    assert "主从" in out and "男主" in out and "女甲" in out and "征服-占有" in out


def test_render_overview_empty_graph():
    assert render_overview(empty_graph()) == ""


def test_iter_groups_empty_by_default():
    assert iter_groups(empty_graph()) == []


def test_peer_label_no_groups_is_empty():
    assert peer_label(empty_graph(), "女甲", "女乙") == ""


def test_validate_edge_good():
    names = {"男主", "女甲"}
    assert validate_edge(_EDGE_AB, names) == []


def test_validate_edge_unknown_from():
    errs = validate_edge({"from": "路人", "to": "女甲", "nature": "x"}, {"男主", "女甲"})
    assert any("路人" in e for e in errs)


def test_validate_edge_unknown_to():
    errs = validate_edge({"from": "男主", "to": "路人", "nature": "x"}, {"男主", "女甲"})
    assert any("路人" in e for e in errs)


def test_validate_edge_same_from_to():
    errs = validate_edge({"from": "男主", "to": "男主", "nature": "x"}, {"男主"})
    assert any("相同" in e for e in errs)


def test_validate_edge_empty_nature():
    errs = validate_edge({"from": "男主", "to": "女甲", "nature": ""}, {"男主", "女甲"})
    assert any("nature" in e for e in errs)


def test_edges_for_character_both_directions():
    g = {"groups": {}, "edges": {"男主→女甲": _EDGE_AB, "男主→女乙": _EDGE_AC}}
    assert {e["to"] for e in edges_for_character(g, "男主")} == {"女甲", "女乙"}
    assert [e["from"] for e in edges_for_character(g, "女甲")] == ["男主"]
    assert edges_for_character(g, "路人") == []


def test_related_to_present_pulls_in_the_other_side_of_an_edge():
    g = {"groups": {}, "edges": {"男主→女甲": _EDGE_AB}}
    assert related_to_present(g, {"男主"}) == {"女甲"}
    assert related_to_present(g, {"女甲"}) == {"男主"}


def test_related_to_present_excludes_names_already_present():
    g = {"groups": {}, "edges": {"男主→女甲": _EDGE_AB}}
    assert related_to_present(g, {"男主", "女甲"}) == set()


def test_related_to_present_ignores_edges_disjoint_from_present():
    g = {"groups": {}, "edges": {"男主→女乙": _EDGE_AC}}
    assert related_to_present(g, {"路人"}) == set()


def test_related_to_present_unions_across_multiple_present_characters():
    g = {"groups": {}, "edges": {"男主→女甲": _EDGE_AB, "男主→女乙": _EDGE_AC}}
    assert related_to_present(g, {"女甲", "女乙"}) == {"男主"}


def test_remove_edge_tombstone_drops_key_on_load(tmp_path):
    p = str(tmp_path / "edges.sqlite3")
    append_edge(_EDGE_AB, path=p)
    append_edge(_EDGE_AC, path=p)
    remove_edge("男主", "女甲", path=p)
    g = load_graph(p)
    assert set(g["edges"]) == {"男主→女乙"}


def test_remove_edge_does_not_affect_reverse_direction(tmp_path):
    p = str(tmp_path / "edges.sqlite3")
    append_edge(_EDGE_AB, path=p)
    append_edge({**_EDGE_AB, "from": "女甲", "to": "男主", "nature": "反向"}, path=p)
    remove_edge("男主", "女甲", path=p)
    g = load_graph(p)
    assert set(g["edges"]) == {"女甲→男主"}


def test_remove_edge_then_re_add_wins(tmp_path):
    p = str(tmp_path / "edges.sqlite3")
    append_edge(_EDGE_AB, path=p)
    remove_edge("男主", "女甲", path=p)
    append_edge({**_EDGE_AB, "nature": "重新建立"}, path=p)
    g = load_graph(p)
    assert g["edges"]["男主→女甲"]["nature"] == "重新建立"


def test_iter_edges_by_key_keys_by_from_to():
    g = {"groups": {}, "edges": {"男主→女甲": _EDGE_AB, "男主→女乙": _EDGE_AC}}
    assert iter_edges_by_key(g) == {"男主→女甲": _EDGE_AB, "男主→女乙": _EDGE_AC}


def test_merge_overlay_empty_overlay_returns_graph_unchanged():
    g = {"groups": {}, "edges": {"男主→女甲": _EDGE_AB}}
    assert merge_overlay(g, {}) == g


def test_merge_overlay_adds_a_new_edge_alongside_base_edges():
    g = {"groups": {}, "edges": {"男主→女甲": _EDGE_AB}}
    overlay = {"女甲→女乙": {"from": "女甲", "to": "女乙", "nature": "姐妹", "relationship_anchor": "", "from_ref_terms": [], "to_ref_terms": []}}
    merged = merge_overlay(g, overlay)
    assert set(merged["edges"]) == {"男主→女甲", "女甲→女乙"}
    assert merged["edges"]["男主→女甲"] == _EDGE_AB


def test_merge_overlay_overrides_a_same_key_base_edge():
    g = {"groups": {}, "edges": {"男主→女甲": _EDGE_AB}}
    overridden = {"from": "男主", "to": "女甲", "nature": "反目", "relationship_anchor": "", "from_ref_terms": [], "to_ref_terms": []}
    merged = merge_overlay(g, {"男主→女甲": overridden})
    assert merged["edges"]["男主→女甲"]["nature"] == "反目"


def test_merge_overlay_does_not_mutate_input_graph():
    g = {"groups": {}, "edges": {"男主→女甲": _EDGE_AB}}
    merge_overlay(g, {"男主→女乙": _EDGE_AC})
    assert set(g["edges"]) == {"男主→女甲"}


def test_merge_overlay_preserves_groups():
    g = {"groups": {"g0": {"members": ["男主", "女甲"], "type": "同门", "priority": 0}}, "edges": {}}
    merged = merge_overlay(g, {"男主→女乙": _EDGE_AC})
    assert merged["groups"] == g["groups"]
