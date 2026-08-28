from __future__ import annotations

from repositories.doc_repositories import WorldRepository


def test_world_repo_crud(novel_engine):
    repo = WorldRepository("n1")
    assert repo.get() is None

    repo.save({"lore": "world lore"})
    assert repo.get() == {"lore": "world lore"}

    res = repo.get_with_version()
    assert res == ({"lore": "world lore"}, 1)

    # Stale CAS rejected
    assert repo.save_if_version_matches({"lore": "stale"}, expected_version=99) is None

    # Matching CAS
    new_ver = repo.save_if_version_matches({"lore": "v2"}, expected_version=1)
    assert new_ver == 2
    assert repo.get() == {"lore": "v2"}
