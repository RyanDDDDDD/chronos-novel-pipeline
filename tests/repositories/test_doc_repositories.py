"""Document domain repo (world/relationship) test."""
from repositories.doc_repositories import WorldRepository


def test_world_repo_roundtrip(novel_engine):
    r = WorldRepository("n1")
    assert r.get() is None
    r.save({"tone": "dark"})
    assert r.get() == {"tone": "dark"}


def test_world_repo_get_with_version_delegates(novel_engine):
    r = WorldRepository("n1")
    assert r.get_with_version() is None


def test_world_repo_save_if_version_matches_create_then_update(novel_engine):
    r = WorldRepository("n1")

    new_version = r.save_if_version_matches({"tone": "dark"}, 0)
    assert new_version == 1
    assert r.get_with_version() == ({"tone": "dark"}, 1)

    new_version = r.save_if_version_matches({"tone": "darker"}, 1)
    assert new_version == 2

    stale = r.save_if_version_matches({"tone": "stale"}, 1)
    assert stale is None
