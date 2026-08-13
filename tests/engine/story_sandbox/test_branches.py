import json

import pytest
from engine.story_sandbox.branches import (
    create_branch,
    delete_branch,
    get_branch,
    list_branches,
    register_legacy_branch,
    rename_branch,
    touch_branch,
)
from engine.story_sandbox.state import LEGACY_BRANCH_ID


@pytest.fixture(autouse=True)
def _isolated_branches_path(monkeypatch, tmp_path):
    nid = "test-novel"
    root = tmp_path / nid
    (root / "chapters").mkdir(parents=True)
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", nid)


def test_list_branches_empty_when_no_file():
    assert list_branches(8) == []


def test_create_branch_fills_smallest_gap_from_empty():
    b1 = create_branch(8)
    b2 = create_branch(8)
    assert b1["name"] == "故事线1"
    assert b2["name"] == "故事线2"
    assert b1["id"] != b2["id"]
    assert b1["chapter"] == 8 and b2["chapter"] == 8


def test_create_branch_refills_gap_after_delete():
    b1 = create_branch(8)
    create_branch(8)
    delete_branch(8, b1["id"])
    b3 = create_branch(8)
    assert b3["name"] == "故事线1"


def test_create_branch_skips_occupied_numbers_not_just_the_first_gap():
    create_branch(8)  # 故事线1
    create_branch(8)  # 故事线2
    b3 = create_branch(8)
    assert b3["name"] == "故事线3"


def test_create_branch_custom_names_do_not_occupy_or_consume_numbers():
    create_branch(8, "醒来向好支线")
    b2 = create_branch(8)
    assert b2["name"] == "故事线1"


def test_create_branch_numbering_is_per_chapter():
    create_branch(8)  # 故事线1 for chapter 8
    b = create_branch(3)
    assert b["name"] == "故事线1"


def test_create_branch_respects_explicit_name():
    b = create_branch(8, "醒来向好支线")
    assert b["name"] == "醒来向好支线"


def test_create_branch_scoped_per_chapter():
    create_branch(8)
    create_branch(3)
    assert len(list_branches(8)) == 1
    assert len(list_branches(3)) == 1


def test_list_branches_sorted_by_updated_at_descending(monkeypatch):
    times = iter(["2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00"])
    monkeypatch.setattr("engine.story_sandbox.branches._now", lambda: next(times))
    b1 = create_branch(8, "先建的")
    b2 = create_branch(8, "后建的")
    listed = list_branches(8)
    assert [b["id"] for b in listed] == [b2["id"], b1["id"]]


def test_register_legacy_branch_is_idempotent():
    first = register_legacy_branch(8)
    second = register_legacy_branch(8)
    assert first == second
    assert first["id"] == LEGACY_BRANCH_ID
    assert first["name"] == "故事线1"
    assert len(list_branches(8)) == 1


def test_rename_branch_updates_name_and_persists():
    b = create_branch(8)
    renamed = rename_branch(8, b["id"], "新名字")
    assert renamed["name"] == "新名字"
    got = get_branch(8, b["id"])
    assert got["name"] == "新名字"


def test_rename_branch_raises_when_not_found():
    with pytest.raises(ValueError):
        rename_branch(8, "nonexistent", "x")


def test_rename_branch_does_not_cross_chapter_boundary():
    """The 'legacy' id is reused verbatim across every chapter -- renaming chapter 8's legacy
    branch must never touch chapter 3's."""
    register_legacy_branch(8)
    register_legacy_branch(3)
    rename_branch(8, LEGACY_BRANCH_ID, "第八章的线")
    ch3 = list_branches(3)[0]
    assert ch3["name"] == "故事线1"


def test_touch_branch_bumps_updated_at_and_reorders(monkeypatch):
    times = iter([
        "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00", "2026-01-03T00:00:00+00:00",
    ])
    monkeypatch.setattr("engine.story_sandbox.branches._now", lambda: next(times))
    b1 = create_branch(8, "先建的")
    b2 = create_branch(8, "后建的")
    touch_branch(8, b1["id"])
    listed = list_branches(8)
    assert listed[0]["id"] == b1["id"]


def test_touch_branch_is_a_no_op_when_missing():
    touch_branch(8, "nonexistent")  # must not raise


def test_delete_branch_removes_it_and_returns_remaining_survivor():
    b1 = create_branch(8)
    b2 = create_branch(8)
    result = delete_branch(8, b2["id"])
    assert result["id"] == b1["id"]
    assert [b["id"] for b in list_branches(8)] == [b1["id"]]


def test_delete_branch_raises_when_not_found():
    with pytest.raises(ValueError):
        delete_branch(8, "nonexistent")


def test_delete_last_branch_auto_creates_replacement():
    b1 = create_branch(8)
    replacement = delete_branch(8, b1["id"])
    assert replacement["id"] != b1["id"]
    listed = list_branches(8)
    assert len(listed) == 1
    assert listed[0]["id"] == replacement["id"]


def test_delete_last_branch_auto_replacement_also_fills_smallest_gap():
    b1 = create_branch(8)
    replacement = delete_branch(8, b1["id"])
    assert replacement["name"] == "故事线1"


def test_get_branch_returns_matching_record():
    b1 = create_branch(8, "先建的")
    create_branch(8, "后建的")
    found = get_branch(8, b1["id"])
    assert found["id"] == b1["id"]
    assert found["name"] == "先建的"


def test_get_branch_raises_when_not_found():
    with pytest.raises(ValueError):
        get_branch(8, "nonexistent")


def test_get_branch_does_not_cross_chapter_boundary():
    register_legacy_branch(8)
    register_legacy_branch(3)
    found = get_branch(3, LEGACY_BRANCH_ID)
    assert found["chapter"] == 3
