from __future__ import annotations

from repositories.document_store import (
    get_document,
    get_document_with_version,
    save_document,
    save_document_if_version_matches,
)


def test_document_store_get_save_roundtrip(novel_engine):
    assert get_document("n1", "doc1") is None
    save_document("n1", "doc1", {"theme": "fantasy"})
    assert get_document("n1", "doc1") == {"theme": "fantasy"}


def test_document_store_save_bumps_version(novel_engine):
    save_document("n1", "doc1", {"v": 1})
    res1 = get_document_with_version("n1", "doc1")
    assert res1 == ({"v": 1}, 1)

    save_document("n1", "doc1", {"v": 2})
    res2 = get_document_with_version("n1", "doc1")
    assert res2 == ({"v": 2}, 2)


def test_document_store_cas_version_operations(novel_engine):
    assert get_document_with_version("n1", "doc2") is None

    # CAS create when expected_version=0
    v1 = save_document_if_version_matches("n1", "doc2", {"init": True}, expected_version=0)
    assert v1 == 1

    # CAS create fails when already exists
    assert save_document_if_version_matches("n1", "doc2", {"init": False}, expected_version=0) is None

    # CAS stale update fails
    assert save_document_if_version_matches("n1", "doc2", {"update": 1}, expected_version=99) is None

    # CAS matching update succeeds
    v2 = save_document_if_version_matches("n1", "doc2", {"update": 1}, expected_version=1)
    assert v2 == 2
    assert get_document("n1", "doc2") == {"update": 1}
