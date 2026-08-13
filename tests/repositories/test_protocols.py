# tests/repositories/test_protocols.py
from repositories.entities import Character
from repositories.protocols import LoreRepository


class _FakeLore:
    def get_character(self, name): return Character(name=name)
    def list_characters(self): return []

def test_fake_satisfies_lore_protocol():
    assert isinstance(_FakeLore(), LoreRepository)
