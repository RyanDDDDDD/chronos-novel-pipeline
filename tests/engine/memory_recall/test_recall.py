from engine.memory_recall.recall import recall_relevant_context
from repositories.entities import MemoryOrigin


def test_recall_no_hits_from_either_source_returns_empty(monkeypatch):
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "玉佩"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )
    out, _, _settings = recall_relevant_context("今天天气不错", chapter=99, origin=MemoryOrigin.SANDBOX)
    assert out == ""


def test_recall_dynamic_entries_sorted_newest_first(monkeypatch):
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "玉佩"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log",
        lambda: {"entries": [
            {"id": "a", "chapter": 1, "turn_index": 0, "summary": "旧事件", "entities": ["玉佩"]},
            {"id": "b", "chapter": 3, "turn_index": 2, "summary": "新事件", "entities": ["玉佩"]},
            {"id": "c", "chapter": 2, "turn_index": 5, "summary": "不相关事件", "entities": ["无关词"]},
        ]})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context("提到了玉佩", chapter=99, origin=MemoryOrigin.SANDBOX)
    lines = out.splitlines()
    assert lines[0] == "## 相关历史/设定回收"
    assert "新事件" in lines[2]
    assert "旧事件" in lines[3]
    assert "不相关事件" not in out


def test_recall_caps_dynamic_entries(monkeypatch):
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "玉佩"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    entries = [
        {"id": str(i), "chapter": i, "turn_index": 0, "summary": f"事件{i}", "entities": ["玉佩"]}
        for i in range(8)
    ]
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log", lambda: {"entries": entries})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context("玉佩", chapter=99, origin=MemoryOrigin.SANDBOX, max_items=5)
    assert sum(1 for ln in out.splitlines() if ln.startswith("- [")) == 5


def test_recall_includes_static_world_entries(monkeypatch):
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "factions": [{"name": "云隐山庄", "desc": "西境古老门派"}],
        })})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log", lambda: {"entries": []})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context("去云隐山庄看看", chapter=99, origin=MemoryOrigin.SANDBOX)
    assert "云隐山庄" in out and "西境古老门派" in out


def test_recall_finds_semantic_hit_with_no_keyword_match(monkeypatch):
    """Core new behavior: zero keyword hits must not short-circuit before the semantic query."""
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "玉佩"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log", lambda: {"entries": []})
    from repositories.entities import SandboxMemoryHit

    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [
            SandboxMemoryHit(
                id="sem-1", chapter=4, turn_index=1, summary="语义联想到的旧事", entities=["丙"],
            ),
        ])})(),
    )

    out, _, _settings = recall_relevant_context("完全没提到已知实体名的一句话", chapter=99, origin=MemoryOrigin.SANDBOX)
    assert "语义联想到的旧事" in out
    assert "云隐山庄" not in out


def test_recall_semantic_hit_dropped_when_characters_absent_from_scene(monkeypatch):
    """Core bug-fix behavior: a semantic hit naming characters who are neither this turn's
    keyword hits nor the current active cast must be dropped -- otherwise embedding similarity
    built on shared vocabulary (not shared plot) drags unrelated named characters into the
    recall block, and from there into prose."""
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "玉佩"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log", lambda: {"entries": []})
    from repositories.entities import SandboxMemoryHit

    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [
            SandboxMemoryHit(
                id="sem-1", chapter=6, turn_index=1, summary="不在场角色的旧事",
                characters=["司马相如", "张三", "李四"],
            ),
        ])})(),
    )

    out, _, _settings = recall_relevant_context(
        "王五展示超凡武学", chapter=99, origin=MemoryOrigin.SANDBOX, active_cast={"王五": 8, "小明": 8},
    )
    assert out == ""


def test_recall_semantic_hit_kept_when_a_character_is_onstage(monkeypatch):
    """Same shape as the drop test, but one of the hit's characters overlaps active_cast --
    the hit is presumed relevant (same cast, possibly referred to indirectly) and kept."""
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "玉佩"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log", lambda: {"entries": []})
    from repositories.entities import SandboxMemoryHit

    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [
            SandboxMemoryHit(
                id="sem-1", chapter=6, turn_index=1, summary="在场角色的旧事",
                characters=["小明", "张三"],
            ),
        ])})(),
    )

    out, _, _settings = recall_relevant_context(
        "王五展示超凡武学", chapter=99, origin=MemoryOrigin.SANDBOX, active_cast={"王五": 8, "小明": 8},
    )
    assert "在场角色的旧事" in out


def test_recall_semantic_hit_with_no_characters_recorded_still_passes(monkeypatch):
    """A hit with no characters metadata makes no character claim at all, so there's nothing to
    gate on -- must not be dropped just because active_cast was supplied."""
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "玉佩"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log", lambda: {"entries": []})
    from repositories.entities import SandboxMemoryHit

    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [
            SandboxMemoryHit(id="sem-1", chapter=6, turn_index=1, summary="无角色标注的旧事"),
        ])})(),
    )

    out, _, _settings = recall_relevant_context(
        "王五展示超凡武学", chapter=99, origin=MemoryOrigin.SANDBOX, active_cast={"王五": 8, "小明": 8},
    )
    assert "无角色标注的旧事" in out


def test_recall_line_shows_time_location_and_characters_when_present(monkeypatch):
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "玉佩"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log",
        lambda: {"entries": [
            {
                "id": "a", "chapter": 3, "turn_index": 0, "time": "决战之后",
                "location": "藏经阁", "characters": ["甲", "乙"],
                "summary": "甲把玉佩交给了乙", "entities": ["玉佩"],
            },
        ]})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context("提到了玉佩", chapter=99, origin=MemoryOrigin.SANDBOX)
    assert "决战之后" in out
    assert "藏经阁" in out
    assert "甲、乙" in out


def test_recall_line_omits_optional_bits_when_absent(monkeypatch):
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "玉佩"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log",
        lambda: {"entries": [
            {"id": "a", "chapter": 1, "turn_index": 0, "summary": "旧事件", "entities": ["玉佩"]},
        ]})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context("提到了玉佩", chapter=99, origin=MemoryOrigin.SANDBOX)
    lines = out.splitlines()
    assert lines[2] == "- [第1章] 旧事件"


def test_recall_dedupes_same_id_across_both_sources_keeping_keyword_version(monkeypatch):
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "玉佩"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log",
        lambda: {"entries": [
            {
                "id": "dup-1", "chapter": 2, "turn_index": 0,
                "summary": "关键词版本的完整内容", "entities": ["玉佩"],
            },
        ]})
    from repositories.entities import SandboxMemoryHit

    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [
            SandboxMemoryHit(
                id="dup-1", chapter=2, turn_index=0, summary="语义版本(应该被忽略)", entities=[],
            ),
        ])})(),
    )

    out, _, _settings = recall_relevant_context("提到了玉佩", chapter=99, origin=MemoryOrigin.SANDBOX)
    assert "关键词版本的完整内容" in out
    assert "语义版本" not in out
    assert sum(1 for ln in out.splitlines() if ln.startswith("- [")) == 1


def test_recall_prior_prose_hit_when_instruction_has_none(monkeypatch):
    """Core new behavior: instruction alone missing a hit must not block prior_prose's hits."""
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "玉佩"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log",
        lambda: {"entries": [
            {"id": "a", "chapter": 1, "turn_index": 0, "summary": "玉佩的事", "entities": ["玉佩"]},
        ]})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context("继续", chapter=99, origin=MemoryOrigin.SANDBOX, prior_prose="他拿出了玉佩")
    assert "玉佩的事" in out


def test_recall_cooldown_suppresses_recently_recalled_item(monkeypatch):
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "玉佩"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log",
        lambda: {"entries": [
            {"id": "a", "chapter": 1, "turn_index": 0, "summary": "旧事件", "entities": ["玉佩"]},
        ]})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context("提到了玉佩", chapter=99, origin=MemoryOrigin.SANDBOX, turn_index=5, cooldown={"event:a": 3})
    assert out == ""  # last recalled at turn 3, now turn 5, still within COOLDOWN_TURNS=10


def test_recall_cooldown_allows_item_after_window_passes(monkeypatch):
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "玉佩"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log",
        lambda: {"entries": [
            {"id": "a", "chapter": 1, "turn_index": 0, "summary": "旧事件", "entities": ["玉佩"]},
        ]})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context("提到了玉佩", chapter=99, origin=MemoryOrigin.SANDBOX, turn_index=13, cooldown={"event:a": 3})
    assert "旧事件" in out  # 13 - 3 = 10 >= COOLDOWN_TURNS, window has passed


def test_recall_cooldown_turns_param_shortens_window(monkeypatch):
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "玉佩"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log",
        lambda: {"entries": [
            {"id": "a", "chapter": 1, "turn_index": 0, "summary": "旧事件", "entities": ["玉佩"]},
        ]})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    # 默认 COOLDOWN_TURNS=10 时，turn_index=5 - cooldown 3 = 2 < 10，仍在冷却期内会被抑制
    # （见 test_recall_cooldown_suppresses_recently_recalled_item）；这里传 cooldown_turns=2，
    # 同样的 2 却已经 >= cooldown_turns=2，窗口提前解冻，条目应该出现。
    out, _, _settings = recall_relevant_context(
        "提到了玉佩", chapter=99, origin=MemoryOrigin.SANDBOX,
        turn_index=5, cooldown={"event:a": 3}, cooldown_turns=2,
    )
    assert "旧事件" in out


def test_recall_cooldown_skipped_items_do_not_consume_max_items_slot(monkeypatch):
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "玉佩"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log",
        lambda: {"entries": [
            {"id": "newest", "chapter": 3, "turn_index": 0, "summary": "最新事件", "entities": ["玉佩"]},
            {"id": "older", "chapter": 1, "turn_index": 0, "summary": "较旧事件", "entities": ["玉佩"]},
        ]})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    # "newest" is on cooldown; "older" should backfill instead of the slot just vanishing.
    out, _, _settings = recall_relevant_context(
        "提到了玉佩", chapter=99, origin=MemoryOrigin.SANDBOX, max_items=1, turn_index=5, cooldown={"event:newest": 3},
    )
    assert "较旧事件" in out
    assert "最新事件" not in out


def test_recall_updated_cooldown_only_touches_items_actually_recalled(monkeypatch):
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "玉佩"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log",
        lambda: {"entries": [
            {"id": "a", "chapter": 1, "turn_index": 0, "summary": "事件A", "entities": ["玉佩"]},
        ]})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    _, updated, _settings = recall_relevant_context("提到了玉佩", chapter=99, origin=MemoryOrigin.SANDBOX, turn_index=7, cooldown={})
    assert updated["event:a"] == 7

    # An item skipped by cooldown keeps its prior timestamp, not refreshed.
    _, updated2, _settings2 = recall_relevant_context(
        "提到了玉佩", chapter=99, origin=MemoryOrigin.SANDBOX, turn_index=9, cooldown={"event:a": 7},
    )
    assert updated2["event:a"] == 7


def test_recall_includes_power_system_named_entries(monkeypatch):
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "power_system": [{"name": "元气", "desc": "气血流动力量，需定期喂食"}],
        })})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log", lambda: {"entries": []})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context("他体内的元气开始运转", chapter=99, origin=MemoryOrigin.SANDBOX)
    assert "元气" in out and "气血流动力量，需定期喂食" in out


def test_recall_core_themes_without_keywords_still_excluded(monkeypatch):
    """core_themes entries without keywords configured stay excluded (safe default) -- prevents
    every pre-existing novel's un-migrated core_themes entries from suddenly flooding recall the
    moment this feature ships, since none of them will have keywords populated yet."""
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "core_themes": [{"name": "复仇", "desc": "主角因灭门而踏上复仇路"}],
        })})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log", lambda: {"entries": []})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context("他决定复仇", chapter=99, origin=MemoryOrigin.SANDBOX)
    assert out == ""


def test_recall_world_entries_also_subject_to_cooldown(monkeypatch):
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "factions": [{"name": "云隐山庄", "desc": "西境古老门派"}],
        })})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log", lambda: {"entries": []})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context(
        "去云隐山庄看看", chapter=99, origin=MemoryOrigin.SANDBOX, turn_index=5, cooldown={"world:factions:云隐山庄": 2},
    )
    assert "云隐山庄" not in out


def test_recall_recalled_settings_includes_category_name_desc(monkeypatch):
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "power_system": [{"name": "元气", "desc": "气血流动力量"}],
        })})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log", lambda: {"entries": []})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    _out, _cooldown, recalled_settings = recall_relevant_context("他体内的元气开始运转", chapter=99, origin=MemoryOrigin.SANDBOX)
    assert recalled_settings == [
        {"category": "power_system", "name": "元气", "desc": "气血流动力量"},
    ]


def test_recall_recalled_settings_empty_when_nothing_recalled(monkeypatch):
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "玉佩"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )
    _out, _cooldown, recalled_settings = recall_relevant_context("今天天气不错", chapter=99, origin=MemoryOrigin.SANDBOX)
    assert recalled_settings == []


def test_recall_recalled_settings_excludes_dynamic_event_entries(monkeypatch):
    """recalled_settings must only ever contain world-bible named entries, never event-log
    entries -- even when both fire in the same call."""
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "玉佩"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "factions": [{"name": "云隐山庄", "desc": "西境古老门派"}],
        })})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log",
        lambda: {"entries": [
            {"id": "a", "chapter": 1, "turn_index": 0, "summary": "玉佩的事", "entities": ["玉佩"]},
        ]})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _cooldown, recalled_settings = recall_relevant_context("玉佩和云隐山庄都提到了", chapter=99, origin=MemoryOrigin.SANDBOX)
    assert "玉佩的事" in out  # event history still in the flat text
    assert recalled_settings == [
        {"category": "factions", "name": "云隐山庄", "desc": "西境古老门派"},
    ]


def test_recall_recalled_settings_suppressed_by_cooldown(monkeypatch):
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "factions": [{"name": "云隐山庄", "desc": "西境古老门派"}],
        })})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log", lambda: {"entries": []})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    _out, _cooldown, recalled_settings = recall_relevant_context(
        "去云隐山庄看看", chapter=99, origin=MemoryOrigin.SANDBOX, turn_index=5, cooldown={"world:factions:云隐山庄": 2},
    )
    assert recalled_settings == []


def test_recall_excludes_future_chapter_event_entry(monkeypatch):
    """Core bug fix: chapter 9's entry must never surface while writing chapter 8 -- 逻辑断崖."""
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "司马相如"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log",
        lambda: {"entries": [
            {
                "id": "future", "chapter": 9, "turn_index": 0,
                "summary": "司马相如在第9章展示才华", "entities": ["司马相如"],
            },
        ]})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context("司马相如的事", chapter=8, origin=MemoryOrigin.SANDBOX)
    assert out == ""


def test_recall_includes_past_chapter_event_entry(monkeypatch):
    """Past-chapter cross-recall is the function's intentional purpose -- must still work."""
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "玉佩"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log",
        lambda: {"entries": [
            {"id": "past", "chapter": 3, "turn_index": 0, "summary": "第3章的玉佩往事", "entities": ["玉佩"]},
        ]})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context("提到了玉佩", chapter=8, origin=MemoryOrigin.SANDBOX)
    assert "第3章的玉佩往事" in out


def test_recall_boundary_same_chapter_entry_included(monkeypatch):
    """entry.chapter == current chapter is NOT "future" -- must still be recallable."""
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "玉佩"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log",
        lambda: {"entries": [
            {"id": "same", "chapter": 8, "turn_index": 0, "summary": "本章早些时候的玉佩片段", "entities": ["玉佩"]},
        ]})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context("提到了玉佩", chapter=8, origin=MemoryOrigin.SANDBOX)
    assert "本章早些时候的玉佩片段" in out


def test_recall_excludes_future_chapter_semantic_hit(monkeypatch):
    """Same future-chapter exclusion, but via the semantic/vector path instead of keyword path."""
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "玉佩"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log", lambda: {"entries": []})
    from repositories.entities import SandboxMemoryHit

    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [
            SandboxMemoryHit(id="future-sem", chapter=9, turn_index=0, summary="未来章节的语义命中"),
        ])})(),
    )

    out, _, _settings = recall_relevant_context("完全没提到已知实体名的一句话", chapter=8, origin=MemoryOrigin.SANDBOX)
    assert out == ""


def test_recall_relevant_context_filters_out_other_branches_keyword_entries(monkeypatch):
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log",
        lambda: {"entries": [
            {"id": "1", "chapter": 1, "branch_id": "other-branch", "entities": ["玉佩"], "summary": "另一条线的事", "characters": []},
        ]},
    )
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_entities", lambda text: {"玉佩"} if text else set(),
    )
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )
    text, _cooldown, _settings = recall_relevant_context("玉佩呢", chapter=2, origin=MemoryOrigin.SANDBOX, branch_id="my-branch")
    assert "另一条线的事" not in text


def test_recall_relevant_context_includes_canon_entries_with_no_branch_id(monkeypatch):
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log",
        lambda: {"entries": [
            {"id": "1", "chapter": 1, "branch_id": None, "entities": ["玉佩"], "summary": "canon的事", "characters": []},
        ]},
    )
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_entities", lambda text: {"玉佩"} if text else set(),
    )
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )
    text, _cooldown, _settings = recall_relevant_context("玉佩呢", chapter=2, origin=MemoryOrigin.SANDBOX, branch_id="my-branch")
    assert "canon的事" in text


def test_recall_relevant_context_filters_by_origin_symmetrically(monkeypatch):
    """author_loop and sandbox recall are symmetrically isolated: each only sees entries tagged
    with its own origin, regardless of branch_id. Entries missing the origin field (legacy,
    predating this feature) are treated as sandbox."""
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log",
        lambda: {"entries": [
            {"id": "1", "chapter": 1, "branch_id": "some-branch", "entities": ["玉佩"], "summary": "沙盒的事", "characters": [], "origin": "sandbox"},
            {"id": "2", "chapter": 1, "branch_id": None, "entities": ["玉佩"], "summary": "主笔的事", "characters": [], "origin": "author_loop"},
            {"id": "3", "chapter": 1, "branch_id": None, "entities": ["玉佩"], "summary": "旧条目没有origin字段", "characters": []},
        ]},
    )
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_entities", lambda text: {"玉佩"} if text else set(),
    )
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    sandbox_text, _cooldown, _settings = recall_relevant_context(
        "玉佩呢", chapter=2, origin=MemoryOrigin.SANDBOX,
    )
    assert "沙盒的事" in sandbox_text
    assert "旧条目没有origin字段" in sandbox_text
    assert "主笔的事" not in sandbox_text

    author_loop_text, _cooldown, _settings = recall_relevant_context(
        "玉佩呢", chapter=2, origin=MemoryOrigin.AUTHOR_LOOP,
    )
    assert "主笔的事" in author_loop_text
    assert "沙盒的事" not in author_loop_text
    assert "旧条目没有origin字段" not in author_loop_text


def test_recall_power_system_with_keywords_ignores_bare_name_alone(monkeypatch):
    """Once an entry has keywords configured, bare name match alone no longer confirms --
    only keyword co-occurrence does. Prevents regressions where a keyword-bearing entry's own
    name (which may itself be a common phrase) silently keeps the old unconditional-match path."""
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "power_system": [{"name": "信仰丧失", "desc": "d", "keywords": ["神像崩塌", "停止祷告"]}],
        })})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log", lambda: {"entries": []})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context("他的信仰丧失已久", chapter=99, origin=MemoryOrigin.SANDBOX)
    assert out == ""  # bare name present, but no keyword -- must not confirm


def test_recall_power_system_with_keywords_confirms_via_keyword_without_bare_name(monkeypatch):
    """Core recall-boost behavior: an abstract entry whose literal name never appears in prose
    must still surface via one of its keywords."""
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "power_system": [{"name": "信仰丧失", "desc": "不再信任神明", "keywords": ["神像崩塌", "停止祷告"]}],
        })})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log", lambda: {"entries": []})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context("神像崩塌的那一夜", chapter=99, origin=MemoryOrigin.SANDBOX)
    assert "信仰丧失" in out and "不再信任神明" in out


def test_recall_core_themes_with_keywords_confirms_via_keyword(monkeypatch):
    """core_themes entries were entirely excluded before -- with keywords configured, they now
    participate in recall via the same keyword-co-occurrence path as power_system."""
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "core_themes": [{"name": "复仇", "desc": "主角因灭门而踏上复仇路", "keywords": ["血恨", "手刃"]}],
        })})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log", lambda: {"entries": []})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context("他心怀血恨，终于手刃仇人", chapter=99, origin=MemoryOrigin.SANDBOX)
    assert "复仇" in out and "主角因灭门而踏上复仇路" in out


def test_recall_core_themes_with_keywords_ignores_bare_name_alone(monkeypatch):
    """The anti-flood case this whole feature exists for: a common-word core_themes entry with
    keywords configured must not fire on the bare name alone."""
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "core_themes": [{"name": "复仇", "desc": "d", "keywords": ["血恨", "手刃"]}],
        })})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log", lambda: {"entries": []})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context("他决定复仇", chapter=99, origin=MemoryOrigin.SANDBOX)
    assert out == ""


def test_recall_recalled_settings_includes_core_themes_category(monkeypatch):
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "core_themes": [{"name": "复仇", "desc": "d", "keywords": ["血海深仇"]}],
        })})(),
    )
    monkeypatch.setattr(
        "engine.memory_recall.event_log.load_event_log", lambda: {"entries": []})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    _out, _cooldown, recalled_settings = recall_relevant_context("血海深仇", chapter=99, origin=MemoryOrigin.SANDBOX)
    assert recalled_settings == [{"category": "core_themes", "name": "复仇", "desc": "d"}]


def test_recall_power_system_strong_keyword_confirms_alone(monkeypatch):
    """A single >=3-char keyword is a strong signal -- confirms on its own, no co-occurrence
    needed."""
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "power_system": [{"name": "信仰丧失", "desc": "d", "keywords": ["神像崩塌"]}],
        })})(),
    )
    monkeypatch.setattr("engine.memory_recall.event_log.load_event_log", lambda: {"entries": []})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context("神像崩塌了", chapter=99, origin=MemoryOrigin.SANDBOX)
    assert "信仰丧失" in out


def test_recall_core_themes_single_weak_keyword_alone_does_not_confirm(monkeypatch):
    """A lone 2-char weak keyword must NOT confirm by itself -- this is the anti-flood behavior
    this whole strong/weak split exists for."""
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "core_themes": [{"name": "复仇", "desc": "d", "keywords": ["血恨", "手刃"]}],
        })})(),
    )
    monkeypatch.setattr("engine.memory_recall.event_log.load_event_log", lambda: {"entries": []})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context("他终于手刃仇人", chapter=99, origin=MemoryOrigin.SANDBOX)
    assert out == ""


def test_recall_core_themes_two_weak_keywords_cooccurrence_confirms(monkeypatch):
    """Two distinct 2-char weak keywords co-occurring in full_scan_text confirms, even with no
    bare name mention."""
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "core_themes": [{"name": "复仇", "desc": "主角因灭门而踏上复仇路", "keywords": ["血恨", "手刃"]}],
        })})(),
    )
    monkeypatch.setattr("engine.memory_recall.event_log.load_event_log", lambda: {"entries": []})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context(
        "他心怀血恨，终于手刃仇人", chapter=99, origin=MemoryOrigin.SANDBOX
    )
    assert "复仇" in out and "主角因灭门而踏上复仇路" in out


def test_recall_core_themes_bare_name_plus_one_weak_keyword_confirms(monkeypatch):
    """Bare entry name + 1 weak keyword co-occurring confirms."""
    from engine.memory_recall import entity_index
    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "core_themes": [{"name": "复仇", "desc": "d", "keywords": ["血恨", "手刃"]}],
        })})(),
    )
    monkeypatch.setattr("engine.memory_recall.event_log.load_event_log", lambda: {"entries": []})
    monkeypatch.setattr(
        "repositories.get_sandbox_vector_memory_repo",
        lambda: type("R", (), {"query": staticmethod(lambda text, top_k: [])})(),
    )

    out, _, _settings = recall_relevant_context(
        "他决定复仇，心怀血恨", chapter=99, origin=MemoryOrigin.SANDBOX
    )
    assert "复仇" in out
