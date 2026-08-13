"""Document domain repo (world/relationship) test."""
from repositories.doc_repositories import WorldRepository


class _Store:
    def __init__(self):
        self.docs = {}

    def get_doc(self, key, path):
        return self.docs.get(key)

    def save_doc(self, key, path, data):
        self.docs[key] = data


def test_world_repo_roundtrip(monkeypatch):
    monkeypatch.setattr("repositories.doc_repositories.world_bible_path", lambda: "/w.json")
    s = _Store()
    r = WorldRepository(s)
    assert r.get() is None
    r.save({"tone": "dark"})
    assert r.get() == {"tone": "dark"}

