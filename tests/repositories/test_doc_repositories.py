"""Document domain repo (world/relationship) test."""
from repositories.doc_repositories import WorldRepository


class _Store:
    def __init__(self):
        self.docs = {}
        self.versions = {}

    def get_doc(self, key, path):
        return self.docs.get(key)

    def save_doc(self, key, path, data):
        self.docs[key] = data

    def get_doc_with_version(self, key):
        if key not in self.docs:
            return None
        return self.docs[key], self.versions.get(key, 1)

    def save_doc_if_version_matches(self, key, data, expected_version):
        current = self.versions.get(key, 0)
        if expected_version != current:
            return None
        self.docs[key] = data
        self.versions[key] = current + 1
        return self.versions[key]


def test_world_repo_roundtrip(monkeypatch):
    monkeypatch.setattr("repositories.doc_repositories.world_bible_path", lambda: "/w.json")
    s = _Store()
    r = WorldRepository(s)
    assert r.get() is None
    r.save({"tone": "dark"})
    assert r.get() == {"tone": "dark"}


def test_world_repo_get_with_version_delegates(monkeypatch):
    monkeypatch.setattr("repositories.doc_repositories.world_bible_path", lambda: "/w.json")
    s = _Store()
    r = WorldRepository(s)
    assert r.get_with_version() is None


def test_world_repo_save_if_version_matches_create_then_update(monkeypatch):
    monkeypatch.setattr("repositories.doc_repositories.world_bible_path", lambda: "/w.json")
    s = _Store()
    r = WorldRepository(s)

    new_version = r.save_if_version_matches({"tone": "dark"}, 0)
    assert new_version == 1
    assert r.get_with_version() == ({"tone": "dark"}, 1)

    new_version = r.save_if_version_matches({"tone": "darker"}, 1)
    assert new_version == 2

    stale = r.save_if_version_matches({"tone": "stale"}, 1)
    assert stale is None
