import pytest
from repositories.vector_repositories import ResearchRepository, SandboxVectorMemoryRepository
from repositories.entities import ResearchChunk, SandboxMemoryHit


def test_research_repo_upsert_then_query(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    r = ResearchRepository()
    total = r.upsert([ResearchChunk(text="赛博都市由七大企业统治", topic="世界观", source="http://x")])
    assert total == 1
    hits = r.query("谁统治这座城市", top_k=3)
    assert hits and isinstance(hits[0], ResearchChunk)
    assert "企业" in hits[0].text
    assert hits[0].source == "http://x"


def test_research_repo_upsert_idempotent_same_text(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    r = ResearchRepository()
    r.upsert([ResearchChunk(text="同一句", topic="t", source="s")])
    total = r.upsert([ResearchChunk(text="同一句", topic="t", source="s")])
    assert total == 1


def test_research_repo_upsert_skips_chunks_without_text(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    r = ResearchRepository()
    assert r.upsert([ResearchChunk(text="", topic="t", source="s")]) == 0


def test_research_repo_query_empty_novel_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "brand-new-novel")
    r = ResearchRepository()
    assert r.query("任意", top_k=3) == []


def test_replace_for_source_supersedes_stale_chunk_for_same_source(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    r = ResearchRepository()
    r.upsert([ResearchChunk(text="旧版性格描述", topic="甲", source="novel.txt")])
    r.replace_for_source("novel.txt", [ResearchChunk(text="新版性格描述", topic="甲", source="novel.txt")])
    hits = r.query("性格描述", top_k=10)
    texts = [h.text for h in hits]
    assert "新版性格描述" in texts
    assert "旧版性格描述" not in texts


def test_replace_for_source_does_not_touch_other_sources(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    r = ResearchRepository()
    r.upsert([ResearchChunk(text="别的小说的设定", topic="世界观", source="other.txt")])
    r.replace_for_source("novel.txt", [ResearchChunk(text="这本小说的设定", topic="世界观", source="novel.txt")])
    hits = r.query("设定", top_k=10)
    texts = [h.text for h in hits]
    assert "别的小说的设定" in texts
    assert "这本小说的设定" in texts


def test_replace_for_source_keeps_unchanged_text_stable_across_calls(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    r = ResearchRepository()
    chunk = ResearchChunk(text="没变过的设定", topic="世界观", source="novel.txt")
    r.replace_for_source("novel.txt", [chunk])
    r.replace_for_source("novel.txt", [chunk])
    hits = r.query("没变过的设定", top_k=10)
    assert len([h for h in hits if h.text == "没变过的设定"]) == 1


def test_replace_for_source_empty_chunks_clears_prior_state(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    r = ResearchRepository()
    r.upsert([ResearchChunk(text="将被清空", topic="甲", source="novel.txt")])
    r.replace_for_source("novel.txt", [])
    hits = r.query("将被清空", top_k=10)
    assert "将被清空" not in [h.text for h in hits]


def test_upsert_persists_category_and_query_returns_it(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    r = ResearchRepository()
    r.upsert([ResearchChunk(text="冷静的性格", topic="甲", source="novel.txt", category="character")])
    hits = r.query("性格", top_k=3)
    assert hits[0].category == "character"


def test_get_chunks_by_category_returns_all_matching(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    r = ResearchRepository()
    r.upsert([
        ResearchChunk(text="设定A", topic="世界观", source="novel.txt", category="world"),
        ResearchChunk(text="设定B", topic="世界观", source="novel.txt", category="world"),
        ResearchChunk(text="冷静的甲", topic="甲", source="novel.txt", category="character"),
    ])
    world_chunks = r.get_chunks("world")
    assert {c.text for c in world_chunks} == {"设定A", "设定B"}


def test_get_chunks_with_topic_exact_matches_single_entity(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    r = ResearchRepository()
    r.upsert([
        ResearchChunk(text="冷静的甲", topic="甲", source="novel.txt", category="character"),
        ResearchChunk(text="活泼的乙", topic="乙", source="novel.txt", category="character"),
    ])
    chunks = r.get_chunks("character", topic="甲")
    assert [c.text for c in chunks] == ["冷静的甲"]


def test_get_chunks_missing_topic_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    r = ResearchRepository()
    r.upsert([ResearchChunk(text="冷静的甲", topic="甲", source="novel.txt", category="character")])
    assert r.get_chunks("character", topic="不存在的名字") == []


def test_list_topics_dedupes_and_scopes_to_category(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    r = ResearchRepository()
    r.upsert([
        ResearchChunk(text="冷静的甲", topic="甲", source="novel.txt", category="character"),
        ResearchChunk(text="活泼的乙", topic="乙", source="novel.txt", category="character"),
        ResearchChunk(text="设定A", topic="世界观", source="novel.txt", category="world"),
    ])
    assert set(r.list_topics("character")) == {"甲", "乙"}


def test_list_topics_empty_category_returns_empty_list(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    r = ResearchRepository()
    assert r.list_topics("character") == []


@pytest.mark.asyncio
async def test_replace_for_source_async_upserts_and_returns_count(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    r = ResearchRepository()
    written = await r.replace_for_source_async(
        "novel.txt", [ResearchChunk(text="异步写入的内容", topic="世界观", source="novel.txt")],
    )
    assert written == 1
    hits = r.query("异步写入的内容", top_k=3)
    assert hits and hits[0].text == "异步写入的内容"


@pytest.mark.asyncio
async def test_replace_for_source_async_supersedes_stale_chunk_for_same_source(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    r = ResearchRepository()
    r.upsert([ResearchChunk(text="旧版性格描述", topic="甲", source="novel.txt")])
    await r.replace_for_source_async(
        "novel.txt", [ResearchChunk(text="新版性格描述", topic="甲", source="novel.txt")],
    )
    hits = r.query("性格描述", top_k=10)
    texts = [h.text for h in hits]
    assert "新版性格描述" in texts
    assert "旧版性格描述" not in texts


@pytest.mark.asyncio
async def test_sandbox_memory_repo_archive_empty_list_returns_zero(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    repo = SandboxVectorMemoryRepository()
    assert await repo.archive([]) == 0


@pytest.mark.asyncio
async def test_sandbox_memory_repo_archive_upserts_and_counts(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    repo = SandboxVectorMemoryRepository()
    entries = [
        {"id": "e1", "chapter": 1, "turn_index": 0, "time": "决战之后",
         "summary": "甲把玉佩交给了乙", "entities": ["甲", "乙"]},
        {"id": "e2", "chapter": 1, "turn_index": 1, "time": "",
         "summary": "乙离开了书房", "entities": ["乙"]},
    ]
    assert await repo.archive(entries) == 2


@pytest.mark.asyncio
async def test_sandbox_memory_repo_archive_idempotent_same_id(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    repo = SandboxVectorMemoryRepository()
    entry = {"id": "e1", "chapter": 1, "turn_index": 0, "time": "", "summary": "同一条", "entities": []}
    await repo.archive([entry])
    assert await repo.archive([entry]) == 1


@pytest.mark.asyncio
async def test_sandbox_memory_repo_archive_skips_entries_missing_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    repo = SandboxVectorMemoryRepository()
    entries = [{"id": "e1", "chapter": 1, "turn_index": 0, "time": "", "summary": "", "entities": []}]
    assert await repo.archive(entries) == 0


def test_sandbox_memory_repo_query_empty_novel_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "brand-new-novel")
    repo = SandboxVectorMemoryRepository()
    assert repo.query("随便什么", top_k=3) == []


@pytest.mark.asyncio
async def test_sandbox_memory_repo_query_returns_archived_entry_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    repo = SandboxVectorMemoryRepository()
    entry = {
        "id": "e1", "chapter": 3, "turn_index": 5, "time": "决战之后", "location": "藏经阁",
        "characters": ["甲", "乙"], "summary": "甲把玉佩交给了乙", "entities": ["甲", "乙"],
    }
    await repo.archive([entry])
    out = repo.query("甲把玉佩交给了谁", top_k=3)
    assert out
    hit = out[0]
    assert isinstance(hit, SandboxMemoryHit)
    assert hit.id == "e1"
    assert hit.chapter == 3
    assert hit.turn_index == 5
    assert hit.time == "决战之后"
    assert hit.location == "藏经阁"
    assert hit.summary == "甲把玉佩交给了乙"
    assert set(hit.entities) == {"甲", "乙"}
    assert hit.characters == ["甲", "乙"]


@pytest.mark.asyncio
async def test_sandbox_memory_repo_query_missing_optional_fields_default_to_empty(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    repo = SandboxVectorMemoryRepository()
    entry = {"id": "e2", "chapter": 1, "turn_index": 0, "summary": "没有额外字段的事件", "entities": []}
    await repo.archive([entry])
    hit = repo.query("没有额外字段的事件", top_k=3)[0]
    assert hit.time == ""
    assert hit.location == ""
    assert hit.characters == []


def test_embedding_text_includes_time_location_and_characters():
    entry = {
        "time": "决战之后", "location": "藏经阁",
        "characters": ["甲", "乙"], "summary": "甲把玉佩交给了乙",
    }
    text = SandboxVectorMemoryRepository._embedding_text(entry)
    assert "决战之后" in text
    assert "藏经阁" in text
    assert "甲" in text and "乙" in text
    assert "甲把玉佩交给了乙" in text


def test_embedding_text_degrades_gracefully_with_only_summary():
    assert SandboxVectorMemoryRepository._embedding_text({"summary": "普通事件"}) == "普通事件"


@pytest.mark.asyncio
async def test_sandbox_memory_repo_delete_chapter_removes_only_that_chapter(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    repo = SandboxVectorMemoryRepository()
    entries = [
        {"id": "e1", "chapter": 1, "turn_index": 0, "summary": "第一章的事", "entities": []},
        {"id": "e2", "chapter": 2, "turn_index": 0, "summary": "第二章的事", "entities": []},
    ]
    await repo.archive(entries)
    await repo.delete_chapter(1)
    remaining = repo.query("事", top_k=10)
    assert [h.id for h in remaining] == ["e2"]


@pytest.mark.asyncio
async def test_sandbox_memory_repo_delete_chapter_empty_novel_is_a_no_op(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "brand-new-novel")
    repo = SandboxVectorMemoryRepository()
    await repo.delete_chapter(1)  # must not raise


def test_get_sandbox_vector_memory_repo_returns_singleton():
    import repositories

    a = repositories.get_sandbox_vector_memory_repo()
    b = repositories.get_sandbox_vector_memory_repo()
    assert a is b


@pytest.fixture(autouse=True)
def _isolated_vector_memory_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")


@pytest.mark.asyncio
async def test_archive_and_query_roundtrips_branch_id():
    repo = SandboxVectorMemoryRepository()
    await repo.archive([{
        "id": "1", "summary": "甲把玉佩交给了乙", "chapter": 3, "turn_index": 0,
        "branch_id": "b1",
    }])
    hits = repo.query("玉佩", top_k=5)
    assert any(h.id == "1" and h.branch_id == "b1" for h in hits)


@pytest.mark.asyncio
async def test_archive_without_branch_id_roundtrips_as_empty_string():
    """author_loop's archive call site never sets branch_id -- must not crash, and must read
    back as '' (recall.py's canon sentinel), not None (vector metadata can't store None)."""
    repo = SandboxVectorMemoryRepository()
    await repo.archive([{"id": "1", "summary": "canon的事", "chapter": 3, "turn_index": 0}])
    hits = repo.query("canon", top_k=5)
    assert any(h.id == "1" and h.branch_id == "" for h in hits)


@pytest.mark.asyncio
async def test_archive_and_query_roundtrips_origin():
    repo = SandboxVectorMemoryRepository()
    await repo.archive([{
        "id": "1", "summary": "主笔归档的事", "chapter": 3, "turn_index": 0,
        "origin": "author_loop",
    }])
    hits = repo.query("归档", top_k=5)
    assert any(h.id == "1" and h.origin == "author_loop" for h in hits)


@pytest.mark.asyncio
async def test_archive_without_origin_roundtrips_as_empty_string():
    """Legacy archive calls predating this field must not crash, and must read back as ''
    (entries_in_scope/recall.py's "treat as sandbox" sentinel), not None."""
    repo = SandboxVectorMemoryRepository()
    await repo.archive([{"id": "1", "summary": "旧条目", "chapter": 3, "turn_index": 0}])
    hits = repo.query("旧条目", top_k=5)
    assert any(h.id == "1" and h.origin == "" for h in hits)


@pytest.mark.asyncio
async def test_delete_chapter_with_branch_id_only_removes_that_branch():
    repo = SandboxVectorMemoryRepository()
    await repo.archive([
        {"id": "1", "summary": "b1的事", "chapter": 3, "turn_index": 0, "branch_id": "b1"},
        {"id": "2", "summary": "b2的事", "chapter": 3, "turn_index": 0, "branch_id": "b2"},
    ])
    await repo.delete_chapter(3, branch_id="b1")
    hits = repo.query("的事", top_k=5)
    assert sorted(h.id for h in hits) == ["2"]


@pytest.mark.asyncio
async def test_copy_branch_duplicates_matching_entries_with_new_ids_and_branch():
    repo = SandboxVectorMemoryRepository()
    await repo.archive([
        {"id": "old-1", "summary": "甲登场", "chapter": 8, "turn_index": 0, "branch_id": "src"},
        {"id": "old-2", "summary": "乙登场", "chapter": 8, "turn_index": 1, "branch_id": "src"},
    ])

    await repo.copy_branch(8, "src", "dest", {"old-1": "new-1", "old-2": "new-2"})

    hits = repo.query("登场", top_k=10)
    by_id = {h.id: h for h in hits}
    assert {"old-1", "old-2", "new-1", "new-2"} <= set(by_id)
    assert by_id["new-1"].branch_id == "dest"
    assert by_id["new-1"].summary == "甲登场"
    assert by_id["old-1"].branch_id == "src"


@pytest.mark.asyncio
async def test_copy_branch_preserves_origin():
    repo = SandboxVectorMemoryRepository()
    await repo.archive([
        {"id": "old-1", "summary": "甲登场", "chapter": 8, "turn_index": 0, "branch_id": "src", "origin": "sandbox"},
    ])

    await repo.copy_branch(8, "src", "dest", {"old-1": "new-1"})

    hits = repo.query("登场", top_k=10)
    by_id = {h.id: h for h in hits}
    assert by_id["new-1"].origin == "sandbox"


@pytest.mark.asyncio
async def test_copy_branch_ignores_entries_not_in_the_remap():
    repo = SandboxVectorMemoryRepository()
    await repo.archive([
        {"id": "not-in-remap", "summary": "无关条目", "chapter": 8, "turn_index": 0, "branch_id": "src"},
    ])

    await repo.copy_branch(8, "src", "dest", {"some-other-id": "new-id"})

    hits = repo.query("无关条目", top_k=10)
    assert {h.id for h in hits} == {"not-in-remap"}


@pytest.mark.asyncio
async def test_copy_branch_skips_ids_not_yet_archived():
    """A round's event may be in id_remap (fork_branch built it from every round) but not yet
    archived to vector memory (the most recent round never is, per _archive_previous_round's
    deferred-until-superseded design) -- copy_branch must silently skip those, not error."""
    repo = SandboxVectorMemoryRepository()
    await repo.copy_branch(8, "src", "dest", {"never-archived-id": "new-id"})
    hits = repo.query("anything", top_k=10)
    assert hits == []


@pytest.mark.asyncio
async def test_copy_branch_empty_remap_is_a_no_op():
    repo = SandboxVectorMemoryRepository()
    await repo.archive([{"id": "1", "summary": "x", "chapter": 8, "turn_index": 0, "branch_id": "src"}])
    await repo.copy_branch(8, "src", "dest", {})
    hits = repo.query("x", top_k=10)
    assert {h.id for h in hits} == {"1"}


def test_upsert_persists_mention_count_and_query_returns_it(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    r = ResearchRepository()
    r.upsert([ResearchChunk(text="提及多次的角色", topic="甲", source="novel.txt",
                             category="character", mention_count=7)])
    hits = r.query("提及多次的角色", top_k=3)
    assert hits[0].mention_count == 7


def test_get_chunks_returns_mention_count(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    r = ResearchRepository()
    r.upsert([ResearchChunk(text="冷静的甲", topic="甲", source="novel.txt",
                             category="character", mention_count=3)])
    chunks = r.get_chunks("character", topic="甲")
    assert chunks[0].mention_count == 3


def test_query_missing_mention_count_defaults_to_one(monkeypatch, tmp_path):
    """Rows written before this field existed have no mention_count key in metadata --
    must degrade to 1, not crash or return None."""
    from rag.vector_store import SqliteVectorStore
    from utils.paths import novel_db_path

    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "test-novel")
    store = SqliteVectorStore("setup_research", novel_db_path("test-novel"))
    store.upsert(
        ids=["legacy-id"], documents=["老数据没有频次字段"],
        metadatas=[{"topic": "甲", "source": "novel.txt", "category": "character"}],
    )
    r = ResearchRepository()
    hits = r.query("老数据没有频次字段", top_k=3)
    assert hits[0].mention_count == 1


@pytest.mark.asyncio
async def test_shift_chapter_moves_fragment_same_id(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    from utils.paths import use_novel
    with use_novel("shift-vec-novel"):
        from repositories import get_sandbox_vector_memory_repo
        repo = get_sandbox_vector_memory_repo()
        await repo.archive([{
            "id": "e1", "chapter": 2, "turn_index": 0, "summary": "甲登场",
            "characters": ["甲"], "entities": [],
        }])
        await repo.shift_chapter(2, 1)

        hits = repo.query("甲登场", top_k=5)
        assert len(hits) == 1
        assert hits[0].id == "e1"
        assert hits[0].chapter == 3


@pytest.mark.asyncio
async def test_shift_chapter_no_op_when_nothing_archived(tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    from utils.paths import use_novel
    with use_novel("shift-vec-novel-2"):
        from repositories import get_sandbox_vector_memory_repo
        repo = get_sandbox_vector_memory_repo()
        await repo.shift_chapter(9, 1)  # must not raise
