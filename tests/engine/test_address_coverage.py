"""address_ref same chapter coverage detection: pure data function (the relationship opponent set is injected by the bonds layer in the builder, this module does not touch the relationship source)."""
from __future__ import annotations

from engine.archive.address_coverage import (
    address_ref_targets_in_archive,
    apply_remediation,
    build_remediation_prompt,
    find_missing_address_targets,
    parse_remediation,
)


def test_actual_targets_from_flat_archive():
    archive = {"address_ref": {"甲": ["废物"], "乙": ["杂役"]}}
    assert address_ref_targets_in_archive(archive) == {"甲", "乙"}


def test_actual_targets_empty_when_no_address_ref():
    assert address_ref_targets_in_archive({}) == set()


def test_find_missing_is_expected_minus_actual():
    #expected={A, B, C}, actual={A, B} → missing C (pure set operation, expected is injected by the caller)
    archive = {"address_ref": {"甲": ["x"], "乙": ["y"]}}
    assert find_missing_address_targets(archive, {"甲", "乙", "丙"}) == ["丙"]


def test_find_missing_empty_when_fully_covered():
    archive = {"address_ref": {"甲": ["x"], "乙": ["y"], "丙": ["z"]}}
    assert find_missing_address_targets(archive, {"甲", "乙", "丙"}) == []


def test_find_missing_empty_when_no_expected():
    archive = {"address_ref": {}}
    assert find_missing_address_targets(archive, set()) == []


#── Remedial pure functions ───────────────────────────────────────────────────────────


def test_build_remediation_prompt_lists_missing_with_desc():
    #relation_desc is calculated by bonds and injected: opponent → relation description
    sys_p, user_p = build_remediation_prompt(
        "男主", ["丙"], {"丙": "支配（你已收服 ta）"}, "已沦陷", "基调X")
    assert "丙" in user_p and "支配" in user_p
    assert "已沦陷" in user_p and "基调X" in user_p
    assert "JSON" in sys_p


def test_build_remediation_prompt_peer_desc():
    #Serving peers together (no dominant words)
    sys_p, user_p = build_remediation_prompt("甲", ["乙"], {"乙": "共侍一主（同辈）"}, "", "")
    assert "乙" in user_p and "共侍" in user_p
    assert "每个对象都必须给出" in sys_p  #Force each object to have a name


def test_parse_remediation_filters_to_missing_and_drops_empty():
    raw = {"丙": ["废物", "杂役"], "甲": ["不该收"], "丁": [], "戊": "外人"}
    out = parse_remediation(raw, ["丙", "丁"])
    assert out == {"丙": ["废物", "杂役"]}  #Discard if A is not missing; if D is empty, discard; if E is not missing, discard


def test_parse_remediation_scalar_to_list():
    assert parse_remediation({"丙": "废物"}, ["丙"]) == {"丙": ["废物"]}


def test_parse_remediation_non_dict():
    assert parse_remediation("乱码", ["丙"]) == {}


def test_apply_remediation_injects_into_flat_archive():
    archive = {"address_ref": {"甲": ["x"]}}
    apply_remediation(archive, {"丙": ["废物"]})
    assert archive["address_ref"]["丙"] == ["废物"]
    assert archive["address_ref"]["甲"] == ["x"]  #Original reservation


def test_apply_remediation_creates_address_ref_when_missing():
    archive: dict = {}
    apply_remediation(archive, {"丙": ["废物"]})
    assert archive["address_ref"]["丙"] == ["废物"]


def test_apply_remediation_does_not_overwrite_existing():
    archive = {"address_ref": {"丙": ["原称呼"]}}
    apply_remediation(archive, {"丙": ["新称呼"]})
    assert archive["address_ref"]["丙"] == ["原称呼"]  #Already not covered
