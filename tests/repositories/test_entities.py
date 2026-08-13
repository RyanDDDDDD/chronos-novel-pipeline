# tests/repositories/test_entities.py
from repositories.entities import ChapterOutline, Character, CharacterArchive, SandboxMemoryHit


def test_character_roundtrip_preserves_open_fields():
    raw = {"name": "甲", "gender": "female", "archetype": "X", "physique": {"a": 1}}
    c = Character(**raw)
    assert c.name == "甲"
    assert c.gender == "female"
    #Open fields are not lost
    assert c.model_dump()["archetype"] == "X"
    assert c.model_dump()["physique"] == {"a": 1}

def test_chapter_outline_parses_stages():
    raw = {"chapter": 1, "title": "第一章", "stages": [{"index": 0, "stage_num": 1, "title": "s"}]}
    co = ChapterOutline(**raw)
    assert co.stages[0].stage_num == 1

def test_archive_keeps_base_and_stages():
    a = CharacterArchive(name="甲", chapter=1, gender="xeno", stages={"1": {"x": 2}})
    d = a.model_dump()
    assert d["gender"] == "xeno"          #Top-level base open field
    assert d["stages"]["1"] == {"x": 2}


def test_sandbox_memory_hit_defaults():
    hit = SandboxMemoryHit()
    assert hit.id == ""
    assert hit.chapter == 0
    assert hit.turn_index == 0
    assert hit.entities == []
    assert hit.characters == []
    assert hit.origin == ""


def test_research_chunk_category_defaults_to_empty_string():
    from repositories.entities import ResearchChunk

    chunk = ResearchChunk(text="x", topic="t", source="s")
    assert chunk.category == ""


def test_research_chunk_accepts_category_enum_values():
    from repositories.entities import ResearchCategory, ResearchChunk

    chunk = ResearchChunk(text="x", category=ResearchCategory.CHARACTER)
    assert chunk.category == "character"


def test_sandbox_memory_hit_full_construction():
    hit = SandboxMemoryHit(
        id="e1", chapter=3, turn_index=5, time="决战之后", location="藏经阁",
        summary="甲把玉佩交给了乙", entities=["甲", "乙"], characters=["甲", "乙"],
    )
    assert hit.chapter == 3
    assert hit.characters == ["甲", "乙"]


def test_memory_origin_enum_values():
    from repositories.entities import MemoryOrigin

    assert MemoryOrigin.SANDBOX == "sandbox"
    assert MemoryOrigin.AUTHOR_LOOP == "author_loop"


def test_research_chunk_mention_count_defaults_to_one():
    from repositories.entities import ResearchChunk

    chunk = ResearchChunk(text="x", topic="t", source="s")
    assert chunk.mention_count == 1
