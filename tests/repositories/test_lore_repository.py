from __future__ import annotations

from repositories.entities import Character
from repositories.models import (
    CharacterArchive,
    Document,
    LoreCharacter,
    RelationshipEdge,
    TimelineSnapshot,
)
from repositories.sqlite_repositories import SqliteLoreRepository
from sqlmodel import Session, select


def test_lore_repo_roundtrip(novel_engine):
    repo = SqliteLoreRepository("n1")
    repo.save_all([{"name": "张三", "gender": "男"}, {"name": "李四", "gender": "女"}])

    c = repo.get_character("张三")
    assert isinstance(c, Character)
    assert c.name == "张三"
    assert c.gender == "男"

    chars = repo.list_characters()
    assert len(chars) == 2
    assert [c.name for c in chars] == ["张三", "李四"]

    raw = repo.list_raw()
    assert len(raw) == 2
    assert raw[0]["name"] == "张三"


def test_save_all_diff_and_cascade(novel_engine):
    repo = SqliteLoreRepository("n1")
    repo.save_all([{"name": "A"}, {"name": "B"}])

    with Session(novel_engine) as s:
        a = s.exec(select(LoreCharacter).where(LoreCharacter.name == "A")).one()
        b = s.exec(select(LoreCharacter).where(LoreCharacter.name == "B")).one()
        # Add dependents for A
        s.add(CharacterArchive(character_id=a.id, chapter=1, data_json={"note": "a1"}))
        s.add(TimelineSnapshot(character_id=a.id, chapter=1, stage=1, delta_json={"d": 1}))
        s.add(RelationshipEdge(from_character_id=a.id, to_character_id=b.id, nature="friend"))
        s.commit()

    # Now save roster without A -> A and its dependents should be dropped cleanly
    repo.save_all([{"name": "B"}, {"name": "C"}])

    with Session(novel_engine) as s:
        assert s.exec(select(LoreCharacter).where(LoreCharacter.name == "A")).one_or_none() is None
        assert s.exec(select(CharacterArchive)).all() == []
        assert s.exec(select(TimelineSnapshot)).all() == []
        assert s.exec(select(RelationshipEdge)).all() == []
        assert len(s.exec(select(LoreCharacter)).all()) == 2


def test_upsert_character(novel_engine):
    repo = SqliteLoreRepository("n1")
    repo.save_all([{"name": "A", "tag": 1}, {"name": "B", "tag": 2}])
    repo.upsert_character({"name": "A", "tag": 10})
    repo.upsert_character({"name": "C", "tag": 3})

    chars = repo.list_characters()
    assert len(chars) == 3
    assert repo.get_character("A").tag == 10
    assert repo.get_character("C").tag == 3


def test_version_cas_operations(novel_engine):
    repo = SqliteLoreRepository("n1")
    repo.save_all([{"name": "A", "gender": "男"}])

    res = repo.get_character_with_version("A")
    assert res is not None
    data, ver = res
    assert ver == 1

    # Stale version rejected
    res_stale = repo.save_character_if_version_matches("A", {"name": "A", "gender": "未知"}, expected_version=99)
    assert res_stale is None

    # Matching version updates and bumps
    new_ver = repo.save_character_if_version_matches("A", {"name": "A_renamed", "gender": "女"}, expected_version=1)
    assert new_ver == 2

    assert repo.get_character("A") is None
    c = repo.get_character("A_renamed")
    assert c is not None and c.gender == "女"

    # Delete with stale version
    assert not repo.delete_character_if_version_matches("A_renamed", expected_version=1)
    assert repo.get_character("A_renamed") is not None

    # Delete with matching version
    assert repo.delete_character_if_version_matches("A_renamed", expected_version=2)
    assert repo.get_character("A_renamed") is None


def test_merge_story_extensions(novel_engine):
    repo = SqliteLoreRepository("n1")
    with Session(novel_engine) as s:
        s.add(Document(doc_key="story_character_config", data_json={"A": {"hobby": "reading"}}))
        s.commit()

    repo.save_all([{"name": "A", "extensions": {"role": "hero"}}])
    c = repo.get_character("A")
    assert c.extensions == {"role": "hero", "hobby": "reading"}
