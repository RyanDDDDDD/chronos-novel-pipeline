import json
import os

import pytest

from engine.memory_recall.event_log import (
    append_event_entry,
    build_event_extract_node,
    build_event_extract_rewrite_node,
    build_summary_fold_node,
    build_summary_fold_rewrite_node,
    copy_entries_for_branch,
    delete_entries_for_chapter,
    load_event_log,
    load_recall_cooldown,
    replace_event_entry,
    save_recall_cooldown,
)


async def _identity_guard_text(text: str) -> str:
    return text


@pytest.fixture(autouse=True)
def _event_log_novel_env(monkeypatch, tmp_path):
    from repositories.sqlite_store import close_connection, get_connection
    from utils.paths import novel_dir

    nid = "test-novel"
    root = tmp_path / nid
    (root / "lore").mkdir(parents=True)
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", nid)
    db_path = os.path.join(novel_dir(nid), "chronos.sqlite3")
    close_connection(db_path)
    conn = get_connection(db_path)
    conn.execute("DELETE FROM sandbox_events")
    conn.execute("DELETE FROM documents WHERE doc_key = 'recall_cooldown'")
    conn.commit()


def test_load_recall_cooldown_missing_file_returns_empty():
    assert load_recall_cooldown() == {}


def test_save_then_load_recall_cooldown_roundtrips():
    save_recall_cooldown({"event:abc": 3, "world:factions:天音门": 1})
    assert load_recall_cooldown() == {"event:abc": 3, "world:factions:天音门": 1}


def test_load_event_log_missing_file():
    assert load_event_log() == {"entries": []}


def test_load_event_log_corrupt_file():
    assert load_event_log() == {"entries": []}


@pytest.mark.asyncio
async def test_append_event_entry_persists():
    await append_event_entry({"id": "1", "summary": "甲做了事"})
    await append_event_entry({"id": "2", "summary": "乙做了事"})
    saved = load_event_log()
    assert [e["id"] for e in saved["entries"]] == ["1", "2"]


@pytest.mark.asyncio
async def test_replace_event_entry_replaces_by_id():
    await append_event_entry({"id": "1", "summary": "旧版本"})
    await replace_event_entry("1", {"id": "1", "summary": "新版本"})
    saved = load_event_log()
    assert [e["summary"] for e in saved["entries"]] == ["新版本"]


@pytest.mark.asyncio
async def test_replace_event_entry_pure_delete_when_new_entry_is_none():
    await append_event_entry({"id": "1", "summary": "会被删掉"})
    await replace_event_entry("1", None)
    saved = load_event_log()
    assert saved["entries"] == []


@pytest.mark.asyncio
async def test_replace_event_entry_pure_append_when_old_id_is_none():
    await replace_event_entry(None, {"id": "1", "summary": "新条目"})
    saved = load_event_log()
    assert [e["id"] for e in saved["entries"]] == ["1"]


@pytest.mark.asyncio
async def test_delete_entries_for_chapter_removes_only_that_chapter():
    await append_event_entry({"id": "1", "chapter": 1, "summary": "第一章的事"})
    await append_event_entry({"id": "2", "chapter": 2, "summary": "第二章的事"})
    await append_event_entry({"id": "3", "chapter": 1, "summary": "第一章的另一件事"})

    await delete_entries_for_chapter(1)

    saved = load_event_log()
    assert [e["id"] for e in saved["entries"]] == ["2"]


@pytest.mark.asyncio
async def test_delete_entries_for_chapter_no_matching_entries_is_a_no_op():
    await append_event_entry({"id": "1", "chapter": 2, "summary": "第二章的事"})

    await delete_entries_for_chapter(1)

    saved = load_event_log()
    assert [e["id"] for e in saved["entries"]] == ["1"]


@pytest.mark.asyncio
async def test_summary_fold_node_runs_on_the_opening_round():
    """No more window-aging gate -- even an empty turns list (opening round) triggers a fold."""

    async def call_llm(system, user):
        return "开场摘要"

    node = build_summary_fold_node("开场指令", call_llm, _identity_guard_text)
    out = await node({"turns": [], "rolling_summary": "", "final_text": "甲缓缓走入书房。"})

    assert out == {"rolling_summary": "开场摘要"}


@pytest.mark.asyncio
async def test_summary_fold_node_uses_this_turns_own_text_not_a_past_round():
    seen = {}

    async def call_llm(system, user):
        seen["user"] = user
        return "新摘要"

    node = build_summary_fold_node("指令2", call_llm, _identity_guard_text)
    turns = [{"instruction": "指令0", "prose": "prose0"}, {"instruction": "指令1", "prose": "prose1"}]
    out = await node({"turns": turns, "rolling_summary": "旧摘要", "final_text": "prose2"})

    assert "指令2" in seen["user"] and "prose2" in seen["user"]
    assert "指令0" not in seen["user"] and "指令1" not in seen["user"]
    assert out["rolling_summary"] == "新摘要"


@pytest.mark.asyncio
async def test_summary_fold_node_guard_text_rewrites_summary_only():

    forbidden = "违规词"

    async def guard_text(text: str) -> str:
        return text.replace(forbidden, "安全词")

    async def call_llm(system, user):
        return f"滚动摘要含{forbidden}"

    node = build_summary_fold_node("指令0", call_llm, guard_text)
    out = await node({"turns": [], "rolling_summary": "", "final_text": "正文0"})

    assert forbidden not in out["rolling_summary"]
    assert "安全词" in out["rolling_summary"]


@pytest.mark.asyncio
async def test_summary_fold_rewrite_node_uses_previous_rounds_summary_snapshot_as_baseline(
    monkeypatch,
):
    seen = {}

    async def call_llm(system, user):
        seen["user"] = user
        return "新摘要"

    node = build_summary_fold_rewrite_node(call_llm, _identity_guard_text)
    state = {
        "turns": [
            {"instruction": "指令0", "rolling_summary_after": "第0轮之后的摘要"},
            {"instruction": "指令1"},
        ],
        "final_text": "重写后的正文",
    }
    await node(state)

    assert "第0轮之后的摘要" in seen["user"]


@pytest.mark.asyncio
async def test_summary_fold_rewrite_node_opening_round_uses_empty_baseline():
    seen = {}

    async def call_llm(system, user):
        seen["user"] = user
        return "新摘要"

    node = build_summary_fold_rewrite_node(call_llm, _identity_guard_text)
    state = {
        "turns": [{"instruction": "开场指令"}],
        "final_text": "重写后的开场正文",
    }
    await node(state)

    assert "（无）" in seen["user"]


@pytest.mark.asyncio
async def test_summary_fold_node_does_not_archive(monkeypatch):

    archived: list[list[dict]] = []

    async def _fake_archive(entries):
        archived.append(entries)
        return len(entries)

    monkeypatch.setattr(
        "engine.memory_recall.event_log.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"archive": staticmethod(_fake_archive)})(),
    )

    async def call_llm(system, user):
        return "摘要"

    prev_entry = {"id": "prev-1", "chapter": 1, "turn_index": 0, "summary": "上一轮的事件"}
    node = build_summary_fold_node("第2轮指令", call_llm, _identity_guard_text)
    await node({
        "turns": [{"instruction": "指令0", "prose": "正文0", "event_log_entry": prev_entry}],
        "rolling_summary": "旧摘要", "final_text": "正文1",
    })

    assert archived == []


@pytest.mark.asyncio
async def test_event_extract_node_runs_on_the_opening_round():

    async def call_llm(system, user):
        return '{"event": "甲登场", "entities": ["甲"]}'

    node = build_event_extract_node(3, "开场指令", call_llm, _identity_guard_text, branch_id="b1")
    out = await node({"turns": [], "rolling_summary": "", "final_text": "甲缓缓走入书房。"})

    entry = out["event_log_entries_this_turn"][0]
    assert entry["summary"] == "甲登场"
    assert entry["chapter"] == 3
    assert entry["turn_index"] == 0


@pytest.mark.asyncio
async def test_event_extract_node_uses_this_turns_own_text_not_a_past_round():
    seen = {}

    async def call_llm(system, user):
        seen["user"] = user
        return '{"event": "甲把玉佩交给了乙", "entities": ["甲"]}'

    node = build_event_extract_node(3, "指令2", call_llm, _identity_guard_text, branch_id="b1")
    turns = [{"instruction": "指令0", "prose": "prose0"}, {"instruction": "指令1", "prose": "prose1"}]
    out = await node({"turns": turns, "rolling_summary": "旧摘要", "final_text": "prose2"})

    assert "指令2" in seen["user"] and "prose2" in seen["user"]
    assert "指令0" not in seen["user"] and "指令1" not in seen["user"]
    assert out["event_log_entries_this_turn"][0]["turn_index"] == 2


@pytest.mark.asyncio
async def test_event_extract_node_persists_entry(monkeypatch):
    from engine.memory_recall import entity_index

    monkeypatch.setattr(
        "engine.memory_recall.entity_index.build_entity_vocab", lambda: {"玉佩"})
    entity_index.invalidate_entity_vocab_cache()

    async def call_llm(system, user):
        return '{"event": "甲把玉佩交给了乙", "time": "决战之后", "entities": ["甲"]}'

    node = build_event_extract_node(3, "指令0", call_llm, _identity_guard_text, branch_id="b1")
    out = await node({"turns": [], "rolling_summary": "", "final_text": "正文0"})

    entry = out["event_log_entries_this_turn"][0]
    assert entry["summary"] == "甲把玉佩交给了乙"
    assert entry["time"] == "决战之后"
    assert set(entry["entities"]) == {"甲", "玉佩"}

    saved_log = load_event_log()
    assert len(saved_log["entries"]) == 1


@pytest.mark.asyncio
async def test_event_extract_node_persists_location_and_characters():

    async def call_llm(system, user):
        return (
            '{"event": "甲把玉佩交给了乙", "time": "决战之后",'
            ' "location": "藏经阁", "characters": ["甲", "乙"], "entities": ["甲"]}'
        )

    node = build_event_extract_node(3, "指令0", call_llm, _identity_guard_text, branch_id="b1")
    out = await node({"turns": [], "rolling_summary": "", "final_text": "正文0"})

    entry = out["event_log_entries_this_turn"][0]
    assert entry["location"] == "藏经阁"
    assert entry["characters"] == ["甲", "乙"]


@pytest.mark.asyncio
async def test_event_extract_node_missing_location_and_characters_default_to_empty():

    async def call_llm(system, user):
        return '{"event": "甲登场", "entities": ["甲"]}'

    node = build_event_extract_node(1, "指令0", call_llm, _identity_guard_text, branch_id="b1")
    out = await node({"turns": [], "rolling_summary": "", "final_text": "正文0"})

    entry = out["event_log_entries_this_turn"][0]
    assert entry["location"] == ""
    assert entry["characters"] == []


@pytest.mark.asyncio
async def test_event_extract_node_persists_multiple_entries():

    async def call_llm(system, user):
        return (
            '{"events": ['
            '{"event": "甲回忆起童年", "entities": ["甲"]},'
            '{"event": "乙回忆起师父", "entities": ["乙"]}'
            ']}'
        )

    node = build_event_extract_node(1, "指令0", call_llm, _identity_guard_text, branch_id="b1")
    out = await node({"turns": [], "rolling_summary": "", "final_text": "正文0"})

    entries = out["event_log_entries_this_turn"]
    assert len(entries) == 2
    assert {e["summary"] for e in entries} == {"甲回忆起童年", "乙回忆起师父"}
    assert len(load_event_log()["entries"]) == 2


@pytest.mark.asyncio
async def test_event_extract_rewrite_node_replaces_all_prior_entries():

    old_entries = [
        {"id": "old-1", "chapter": 1, "turn_index": 0, "time": "", "summary": "旧的A", "entities": []},
        {"id": "old-2", "chapter": 1, "turn_index": 0, "time": "", "summary": "旧的B", "entities": []},
    ]
    for entry in old_entries:
        await append_event_entry(entry)

    async def call_llm(system, user):
        return '{"events": [{"event": "合并后的新事件", "entities": []}]}'

    node = build_event_extract_rewrite_node(1, call_llm, _identity_guard_text, branch_id="b1")
    state = {
        "turns": [{"instruction": "指令0", "event_log_entries": old_entries}],
        "final_text": "重写后的正文",
    }
    out = await node(state)

    assert len(out["event_log_entries_this_turn"]) == 1
    assert out["event_log_entries_this_turn"][0]["summary"] == "合并后的新事件"
    saved = load_event_log()
    assert len(saved["entries"]) == 1
    assert saved["entries"][0]["summary"] == "合并后的新事件"


@pytest.mark.asyncio
async def test_event_extract_node_degraded_extract_produces_no_entry():

    async def call_llm(system, user):
        return "纯文本，不是 JSON"

    node = build_event_extract_node(1, "指令0", call_llm, _identity_guard_text, branch_id="b1")
    out = await node({"turns": [], "rolling_summary": "", "final_text": "正文0"})

    assert out == {"event_log_entries_this_turn": []}


@pytest.mark.asyncio
async def test_event_extract_rewrite_node_replaces_existing_entry():

    old_entry = {
        "id": "old-1", "chapter": 1, "turn_index": 0, "time": "", "summary": "旧的",
        "entities": [],
    }
    await append_event_entry(old_entry)

    async def call_llm(system, user):
        return '{"event": "甲改口了", "entities": ["甲"]}'

    node = build_event_extract_rewrite_node(1, call_llm, _identity_guard_text, branch_id="b1")
    state = {
        "turns": [{"instruction": "指令0", "event_log_entry": old_entry}],
        "final_text": "重写后的正文",
    }
    out = await node(state)

    assert out["event_log_entries_this_turn"][0]["summary"] == "甲改口了"

    saved = load_event_log()
    assert len(saved["entries"]) == 1
    assert saved["entries"][0]["summary"] == "甲改口了"


@pytest.mark.asyncio
async def test_event_extract_node_archives_the_previous_rounds_entry(monkeypatch):
    """Archiving is deferred to the NEXT round's own turn -- by the time this turn runs, the
    previous round can no longer be rewritten (rewrite only ever targets turns[-1]), so its entry
    is now permanently safe to embed. This turn's OWN entry is never archived here -- it might
    still get rewritten before the round after it begins."""

    archived: list[list[dict]] = []

    async def _fake_archive(entries):
        archived.append(entries)
        return len(entries)

    monkeypatch.setattr(
        "engine.memory_recall.event_log.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"archive": staticmethod(_fake_archive)})(),
    )

    async def call_llm(system, user):
        return '{"event": "新一轮的事件", "entities": []}'

    prev_entry = {"id": "prev-1", "chapter": 1, "turn_index": 0, "summary": "上一轮的事件"}
    node = build_event_extract_node(1, "第2轮指令", call_llm, _identity_guard_text, branch_id="b1")
    out = await node({
        "turns": [{"instruction": "指令0", "prose": "正文0", "event_log_entry": prev_entry}],
        "rolling_summary": "", "final_text": "正文1",
    })

    assert archived == [[prev_entry]]
    assert out["event_log_entries_this_turn"][0]["summary"] == "新一轮的事件"


@pytest.mark.asyncio
async def test_event_extract_node_does_not_archive_on_the_opening_round(monkeypatch):

    archived: list[list[dict]] = []

    async def _fake_archive(entries):
        archived.append(entries)
        return len(entries)

    monkeypatch.setattr(
        "engine.memory_recall.event_log.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"archive": staticmethod(_fake_archive)})(),
    )

    async def call_llm(system, user):
        return '{"event": "开场事件", "entities": []}'

    node = build_event_extract_node(1, "开场指令", call_llm, _identity_guard_text, branch_id="b1")
    await node({"turns": [], "rolling_summary": "", "final_text": "开场正文"})

    assert archived == []


@pytest.mark.asyncio
async def test_event_extract_node_does_not_archive_when_previous_round_produced_no_entry(
    monkeypatch,
):

    archived: list[list[dict]] = []

    async def _fake_archive(entries):
        archived.append(entries)
        return len(entries)

    monkeypatch.setattr(
        "engine.memory_recall.event_log.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"archive": staticmethod(_fake_archive)})(),
    )

    async def call_llm(system, user):
        return '{"event": "这一轮的事件", "entities": []}'

    node = build_event_extract_node(1, "指令1", call_llm, _identity_guard_text, branch_id="b1")
    await node({
        "turns": [{"instruction": "指令0", "prose": "正文0", "event_log_entry": None}],
        "rolling_summary": "", "final_text": "正文1",
    })

    assert archived == []


@pytest.mark.asyncio
async def test_event_extract_node_archive_failure_does_not_raise(monkeypatch):

    async def _boom(entries):
        raise RuntimeError("vector store boom")

    monkeypatch.setattr(
        "engine.memory_recall.event_log.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"archive": staticmethod(_boom)})(),
    )

    async def call_llm(system, user):
        return '{"event": "事件", "entities": []}'

    prev_entry = {"id": "prev-1", "chapter": 1, "turn_index": 0, "summary": "上一轮的事件"}
    node = build_event_extract_node(1, "指令1", call_llm, _identity_guard_text, branch_id="b1")
    out = await node({
        "turns": [{"instruction": "指令0", "prose": "正文0", "event_log_entry": prev_entry}],
        "rolling_summary": "", "final_text": "正文1",
    })

    assert len(out["event_log_entries_this_turn"]) > 0


@pytest.mark.asyncio
async def test_event_extract_node_guard_text_rewrites_event_only():

    forbidden = "违规词"

    async def guard_text(text: str) -> str:
        return text.replace(forbidden, "安全词")

    async def call_llm(system, user):
        return (
            '{"event": "事件含违规词", '
            '"time": "时刻含违规词", "location": "地点含违规词", '
            '"characters": ["角色含违规词"], "entities": ["实体含违规词"]}'
        )

    node = build_event_extract_node(1, "指令0", call_llm, guard_text, branch_id="b1")
    out = await node({"turns": [], "rolling_summary": "", "final_text": "正文0"})

    entry = out["event_log_entries_this_turn"][0]
    assert forbidden not in entry["summary"]
    assert "安全词" in entry["summary"]
    assert forbidden in entry["time"]
    assert forbidden in entry["location"]
    assert forbidden in entry["characters"][0]
    assert forbidden in entry["entities"][0]


@pytest.mark.asyncio
async def test_event_extract_node_falls_back_to_folds_own_characters_when_identify_layer_inactive():

    async def call_llm(system, user):
        return '{"event": "甲登场", "entities": [], "characters": ["甲"]}'

    node = build_event_extract_node(3, "指令0", call_llm, _identity_guard_text, branch_id="b1")
    out = await node({
        "turns": [], "rolling_summary": "", "final_text": "正文0",
    })

    assert out["event_log_entries_this_turn"][0]["characters"] == ["甲"]


def test_build_entry_accepts_event_result():
    from engine.memory_recall.event_log import build_entry
    from engine.story_sandbox.summary_fold import EventResult
    from repositories.entities import MemoryOrigin

    result = EventResult(event="甲登场", time="", location="", entities=[], characters=[])
    entry = build_entry(result, chapter=3, turn_index=0, present=None, origin=MemoryOrigin.SANDBOX)
    assert entry["summary"] == "甲登场"


def test_build_entry_tags_branch_id():
    from engine.memory_recall.event_log import build_entry
    from engine.story_sandbox.summary_fold import FoldResult
    from repositories.entities import MemoryOrigin

    result = FoldResult(summary="", event="甲登场", time="", location="", entities=[], characters=[])
    entry = build_entry(result, chapter=3, turn_index=0, present=None, branch_id="b1", origin=MemoryOrigin.SANDBOX)
    assert entry["branch_id"] == "b1"


def test_build_entry_defaults_branch_id_to_none():
    from engine.memory_recall.event_log import build_entry
    from engine.story_sandbox.summary_fold import FoldResult
    from repositories.entities import MemoryOrigin

    result = FoldResult(summary="", event="甲登场", time="", location="", entities=[], characters=[])
    entry = build_entry(result, chapter=3, turn_index=0, present=None, origin=MemoryOrigin.SANDBOX)
    assert entry["branch_id"] is None


def test_build_entry_tags_origin():
    from engine.memory_recall.event_log import build_entry
    from engine.story_sandbox.summary_fold import FoldResult
    from repositories.entities import MemoryOrigin

    result = FoldResult(summary="", event="甲登场", time="", location="", entities=[], characters=[])
    entry = build_entry(result, chapter=3, turn_index=0, present=None, origin=MemoryOrigin.AUTHOR_LOOP)
    assert entry["origin"] == "author_loop"


@pytest.mark.asyncio
async def test_delete_entries_for_chapter_with_branch_id_only_removes_that_branch():
    await append_event_entry({"id": "1", "chapter": 1, "branch_id": "b1", "summary": "b1的事"})
    await append_event_entry({"id": "2", "chapter": 1, "branch_id": "b2", "summary": "b2的事"})
    await append_event_entry({"id": "3", "chapter": 1, "branch_id": None, "summary": "canon的事"})

    await delete_entries_for_chapter(1, branch_id="b1")

    saved = load_event_log()
    assert sorted(e["id"] for e in saved["entries"]) == ["2", "3"]


@pytest.mark.asyncio
async def test_delete_entries_for_chapter_any_branch_removes_branch_id_key_absent_entries():
    """Entries entirely missing the "branch_id" key predate the field (added 2026-07-28) and
    never legitimately belong to any one branch -- a chapter's pre-existing checkpoint isn't
    always lazily claimed as the "legacy" branch id before the user creates a fresh, differently
    -id'd branch by hand, so this must not be gated to LEGACY_BRANCH_ID specifically. Resetting
    ANY of that chapter's branches must be able to clear them, or the reset UI's "清空所有内容"
    promise is broken for any chapter written before branching shipped."""
    await append_event_entry({"id": "1", "chapter": 1, "summary": "预分支旧条目"})
    await append_event_entry({"id": "2", "chapter": 1, "branch_id": "b1", "summary": "其它故事线的事"})

    await delete_entries_for_chapter(1, branch_id="some-freshly-created-branch-uuid")

    saved = load_event_log()
    assert [e["id"] for e in saved["entries"]] == ["2"]


@pytest.mark.asyncio
async def test_delete_entries_for_chapter_spares_author_loop_canon():
    """author_loop's own archiving (dialogue_mode/react_graph.py::_archive_stage_event) always
    calls build_entry without a branch_id, producing an explicit "branch_id": None -- a real
    canonical chapter fact, distinct from a branch_id-key-absent legacy artifact. No sandbox
    branch reset for that chapter, whichever branch_id it names, may ever sweep this up."""
    await append_event_entry({"id": "1", "chapter": 1, "branch_id": None, "summary": "author_loop真实剧情"})
    await append_event_entry({"id": "2", "chapter": 1, "branch_id": "b1", "summary": "沙盒b1分支的事"})

    await delete_entries_for_chapter(1, branch_id="b1")

    saved = load_event_log()
    assert [e["id"] for e in saved["entries"]] == ["1"]


@pytest.mark.asyncio
async def test_delete_entries_for_chapter_without_branch_id_wipes_whole_chapter():
    """Passing no branch_id keeps the old whole-chapter-wipe behavior (used nowhere in
    production after this change, but kept working since the sync helper is also exercised
    directly by other tests in this file with no branch_id)."""
    await append_event_entry({"id": "1", "chapter": 1, "branch_id": "b1", "summary": "x"})
    await append_event_entry({"id": "2", "chapter": 2, "branch_id": "b1", "summary": "y"})

    await delete_entries_for_chapter(1)

    saved = load_event_log()
    assert [e["id"] for e in saved["entries"]] == ["2"]


@pytest.mark.asyncio
async def test_copy_entries_for_branch_duplicates_matching_entries_with_new_ids_and_branch():
    await append_event_entry({
        "id": "old-1", "chapter": 8, "branch_id": "src", "summary": "甲登场",
        "turn_index": 0, "time": "", "location": "", "characters": [], "entities": [],
    })
    await append_event_entry({
        "id": "old-2", "chapter": 8, "branch_id": "src", "summary": "乙登场",
        "turn_index": 1, "time": "", "location": "", "characters": [], "entities": [],
    })

    await copy_entries_for_branch(8, "dest", {"old-1": "new-1", "old-2": "new-2"})

    saved = load_event_log()
    ids = {e["id"] for e in saved["entries"]}
    assert ids == {"old-1", "old-2", "new-1", "new-2"}
    copies = {e["id"]: e for e in saved["entries"] if e["id"] in ("new-1", "new-2")}
    assert copies["new-1"]["branch_id"] == "dest"
    assert copies["new-1"]["summary"] == "甲登场"
    assert copies["new-2"]["branch_id"] == "dest"
    sources = {e["id"]: e for e in saved["entries"] if e["id"] in ("old-1", "old-2")}
    assert sources["old-1"]["branch_id"] == "src"


@pytest.mark.asyncio
async def test_copy_entries_for_branch_ignores_entries_not_in_the_remap():
    await append_event_entry({
        "id": "not-in-remap", "chapter": 8, "branch_id": "src", "summary": "无关条目",
        "turn_index": 0, "time": "", "location": "", "characters": [], "entities": [],
    })

    await copy_entries_for_branch(8, "dest", {"some-other-id": "new-id"})

    saved = load_event_log()
    assert [e["id"] for e in saved["entries"]] == ["not-in-remap"]


@pytest.mark.asyncio
async def test_copy_entries_for_branch_empty_remap_is_a_no_op():
    await append_event_entry({
        "id": "1", "chapter": 8, "branch_id": "src", "summary": "x",
        "turn_index": 0, "time": "", "location": "", "characters": [], "entities": [],
    })

    await copy_entries_for_branch(8, "dest", {})

    saved = load_event_log()
    assert [e["id"] for e in saved["entries"]] == ["1"]


def test_entries_in_scope_excludes_future_chapters():
    from engine.memory_recall.event_log import entries_in_scope
    from repositories.entities import MemoryOrigin

    entries = [
        {"id": "past", "chapter": 3, "branch_id": None},
        {"id": "future", "chapter": 9, "branch_id": None},
    ]
    result = entries_in_scope(entries, chapter=5, branch_id=None, origin=MemoryOrigin.SANDBOX)
    assert [e["id"] for e in result] == ["past"]


def test_entries_in_scope_includes_canon_and_current_branch_excludes_others():
    from engine.memory_recall.event_log import entries_in_scope
    from repositories.entities import MemoryOrigin

    entries = [
        {"id": "canon", "chapter": 1, "branch_id": None},
        {"id": "mine", "chapter": 1, "branch_id": "b1"},
        {"id": "other", "chapter": 1, "branch_id": "b2"},
    ]
    result = entries_in_scope(entries, chapter=5, branch_id="b1", origin=MemoryOrigin.SANDBOX)
    assert sorted(e["id"] for e in result) == ["canon", "mine"]


def test_entries_in_scope_no_branch_id_is_unfiltered_by_branch():
    from engine.memory_recall.event_log import entries_in_scope
    from repositories.entities import MemoryOrigin

    entries = [
        {"id": "a", "chapter": 1, "branch_id": "b1"},
        {"id": "b", "chapter": 1, "branch_id": "b2"},
    ]
    result = entries_in_scope(entries, chapter=5, branch_id=None, origin=MemoryOrigin.SANDBOX)
    assert sorted(e["id"] for e in result) == ["a", "b"]


def test_entries_in_scope_filters_by_origin_symmetrically():
    from engine.memory_recall.event_log import entries_in_scope
    from repositories.entities import MemoryOrigin

    entries = [
        {"id": "sandbox-1", "chapter": 1, "branch_id": None, "origin": "sandbox"},
        {"id": "author-1", "chapter": 1, "branch_id": None, "origin": "author_loop"},
        {"id": "legacy-1", "chapter": 1, "branch_id": None},
    ]
    sandbox_view = entries_in_scope(entries, chapter=5, branch_id=None, origin=MemoryOrigin.SANDBOX)
    author_view = entries_in_scope(entries, chapter=5, branch_id=None, origin=MemoryOrigin.AUTHOR_LOOP)

    assert sorted(e["id"] for e in sandbox_view) == ["legacy-1", "sandbox-1"]
    assert [e["id"] for e in author_view] == ["author-1"]


def test_list_memory_archive_sorted_newest_first():
    from engine.memory_recall.event_log import append_event_entry, list_memory_archive
    from repositories.entities import MemoryOrigin
    import asyncio

    asyncio.run(append_event_entry({"id": "a", "chapter": 1, "turn_index": 0, "branch_id": None}))
    asyncio.run(append_event_entry({"id": "b", "chapter": 3, "turn_index": 2, "branch_id": None}))
    asyncio.run(append_event_entry({"id": "c", "chapter": 2, "turn_index": 5, "branch_id": None}))

    result = list_memory_archive(chapter=99, branch_id=None, origin=MemoryOrigin.SANDBOX)
    assert [e["id"] for e in result] == ["b", "c", "a"]


def test_list_memory_archive_empty_log_returns_empty_list():
    from engine.memory_recall.event_log import list_memory_archive
    from repositories.entities import MemoryOrigin

    assert list_memory_archive(chapter=1, branch_id=None, origin=MemoryOrigin.SANDBOX) == []


def test_list_memory_archive_filters_by_origin():
    from engine.memory_recall.event_log import append_event_entry, list_memory_archive
    from repositories.entities import MemoryOrigin
    import asyncio

    asyncio.run(append_event_entry({"id": "s", "chapter": 1, "turn_index": 0, "branch_id": None, "origin": "sandbox"}))
    asyncio.run(append_event_entry({"id": "a", "chapter": 1, "turn_index": 0, "branch_id": None, "origin": "author_loop"}))

    result = list_memory_archive(chapter=99, branch_id=None, origin=MemoryOrigin.AUTHOR_LOOP)
    assert [e["id"] for e in result] == ["a"]
