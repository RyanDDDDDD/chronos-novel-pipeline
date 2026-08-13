from engine.memory_recall.entity_index import build_entity_vocab, scan_entities


def test_scan_entities_matches_substring(monkeypatch):
    from engine.memory_recall import entity_index

    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [
            {"given_name": "玉佩"}, {"given_name": "甲"},
        ])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "factions": [], "geography": [{"name": "云隐山庄"}], "races": [],
        })})(),
    )
    assert entity_index.scan_entities("甲把玉佩交给了乙") == ["玉佩", "甲"]


def test_scan_entities_empty_text_returns_empty(monkeypatch):
    from engine.memory_recall import entity_index

    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "甲"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    assert entity_index.scan_entities("") == []


def test_build_entity_vocab_merges_two_sources(monkeypatch):
    class FakeLoreRepo:
        def list_raw(self):
            return [{"given_name": "甲"}, {"given_name": ""}, {"not_a_dict": 1}]

    class FakeWorldRepo:
        def get(self):
            return {
                "factions": [{"name": "云隐山庄", "desc": "西境古老门派"}],
                "geography": [{"name": "北境"}],
                "races": [],
            }

    monkeypatch.setattr("repositories.get_lore_repo", lambda: FakeLoreRepo())
    monkeypatch.setattr("repositories.get_world_repo", lambda: FakeWorldRepo())

    vocab = build_entity_vocab()
    assert vocab == {"甲", "云隐山庄", "北境"}


def test_build_entity_vocab_missing_sources_contribute_nothing(monkeypatch):
    class BrokenRepo:
        def list_raw(self):
            raise OSError("boom")

        def get(self):
            raise OSError("boom")

    monkeypatch.setattr("repositories.get_lore_repo", lambda: BrokenRepo())
    monkeypatch.setattr("repositories.get_world_repo", lambda: BrokenRepo())

    assert build_entity_vocab() == set()


def test_scan_entities_uses_cached_automaton_across_calls(monkeypatch):
    from engine.memory_recall import entity_index

    entity_index.invalidate_entity_vocab_cache()
    call_count = {"n": 0}

    class FakeLoreRepo:
        def list_raw(self):
            call_count["n"] += 1
            return [{"given_name": "甲"}]

    class FakeWorldRepo:
        def get(self):
            return {"factions": [], "geography": [], "races": []}

    monkeypatch.setattr("repositories.get_lore_repo", lambda: FakeLoreRepo())
    monkeypatch.setattr("repositories.get_world_repo", lambda: FakeWorldRepo())

    assert entity_index.scan_entities("甲说话了") == ["甲"]
    assert entity_index.scan_entities("甲又说话了") == ["甲"]
    assert call_count["n"] == 1  # vocab built once, automaton reused


def test_invalidate_entity_vocab_cache_forces_rebuild(monkeypatch):
    from engine.memory_recall import entity_index

    entity_index.invalidate_entity_vocab_cache()
    call_count = {"n": 0}

    class FakeLoreRepo:
        def list_raw(self):
            call_count["n"] += 1
            return [{"given_name": "甲"}]

    class FakeWorldRepo:
        def get(self):
            return {"factions": [], "geography": [], "races": []}

    monkeypatch.setattr("repositories.get_lore_repo", lambda: FakeLoreRepo())
    monkeypatch.setattr("repositories.get_world_repo", lambda: FakeWorldRepo())

    entity_index.scan_entities("甲")
    entity_index.invalidate_entity_vocab_cache()
    entity_index.scan_entities("甲")
    assert call_count["n"] == 2


def test_scan_entities_empty_vocab_returns_empty(monkeypatch):
    from engine.memory_recall import entity_index

    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {})})(),
    )
    assert entity_index.scan_entities("随便什么文本") == []


def test_build_entity_vocab_includes_power_system_and_core_themes(monkeypatch):
    class FakeLoreRepo:
        def list_raw(self):
            return []

    class FakeWorldRepo:
        def get(self):
            return {
                "factions": [], "geography": [], "races": [],
                "power_system": [{"name": "蛊虫", "desc": "寄生驱动力量"}],
                "core_themes": [{"name": "复仇", "desc": "d"}],
            }

    monkeypatch.setattr("repositories.get_lore_repo", lambda: FakeLoreRepo())
    monkeypatch.setattr("repositories.get_world_repo", lambda: FakeWorldRepo())

    vocab = build_entity_vocab()
    assert "蛊虫" in vocab
    assert "复仇" in vocab  # now included -- recall.py's Pass B gates *injection*, not vocab membership


def test_build_character_vocab_excludes_world_nouns(monkeypatch):
    from engine.memory_recall.entity_index import build_character_vocab

    class FakeLoreRepo:
        def list_raw(self):
            return [{"given_name": "甲"}, {"given_name": ""}, {"not_a_dict": 1}]

    class FakeWorldRepo:
        def get(self):
            return {"factions": [{"name": "云隐山庄"}], "geography": [], "races": []}

    monkeypatch.setattr("repositories.get_lore_repo", lambda: FakeLoreRepo())
    monkeypatch.setattr("repositories.get_world_repo", lambda: FakeWorldRepo())

    assert build_character_vocab() == {"甲"}  # world noun must NOT leak in


def test_scan_characters_matches_only_character_names(monkeypatch):
    from engine.memory_recall import entity_index

    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [
            {"given_name": "甲"}, {"given_name": "乙"},
        ])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "factions": [{"name": "云隐山庄"}], "geography": [], "races": [],
        })})(),
    )
    # 云隐山庄 is a world noun (present in entity_vocab via scan_entities) but must not match here
    assert entity_index.scan_characters("甲在云隐山庄见到了乙") == ["乙", "甲"]


def test_scan_characters_empty_text_returns_empty(monkeypatch):
    from engine.memory_recall import entity_index

    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "甲"}])})(),
    )
    monkeypatch.setattr("repositories.get_world_repo", lambda: type("R", (), {"get": staticmethod(lambda: {})})())
    assert entity_index.scan_characters("") == []


def test_invalidate_entity_vocab_cache_also_drops_character_automaton(monkeypatch):
    from engine.memory_recall import entity_index

    entity_index.invalidate_entity_vocab_cache()
    call_count = {"n": 0}

    class FakeLoreRepo:
        def list_raw(self):
            call_count["n"] += 1
            return [{"given_name": "甲"}]

    monkeypatch.setattr("repositories.get_lore_repo", lambda: FakeLoreRepo())
    monkeypatch.setattr("repositories.get_world_repo", lambda: type("R", (), {"get": staticmethod(lambda: {})})())

    entity_index.scan_characters("甲")
    entity_index.invalidate_entity_vocab_cache()
    entity_index.scan_characters("甲")
    assert call_count["n"] == 2  # rebuilt after invalidation, not reused


def test_character_alias_map_resolves_ref_terms(monkeypatch):
    from engine.memory_recall import entity_index

    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [
            {"given_name": "角色乙"}, {"given_name": "角色甲"},
        ])})(),
    )
    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {"角色乙→角色甲": {
            "from": "角色乙", "to": "角色甲", "nature": "兄妹", "relationship_anchor": "",
            "from_ref_terms": ["妹妹"], "to_ref_terms": ["哥哥"],
        }}},
    )
    alias_map = entity_index._character_alias_map()
    assert alias_map == {"妹妹": "角色乙", "哥哥": "角色甲"}


def test_character_alias_map_drops_ambiguous_term(monkeypatch):
    from engine.memory_recall import entity_index

    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [
            {"given_name": "角色乙"}, {"given_name": "小雪"}, {"given_name": "角色甲"},
        ])})(),
    )
    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {
            "角色乙→角色甲": {"from": "角色乙", "to": "角色甲", "nature": "兄妹", "relationship_anchor": "",
                        "from_ref_terms": ["妹妹"], "to_ref_terms": []},
            "小雪→角色甲": {"from": "小雪", "to": "角色甲", "nature": "兄妹", "relationship_anchor": "",
                        "from_ref_terms": ["妹妹"], "to_ref_terms": []},
        }},
    )
    alias_map = entity_index._character_alias_map()
    assert "妹妹" not in alias_map  # 两个不同角色都叫"妹妹" -- 歧义，丢弃


def test_character_alias_map_drops_term_colliding_with_given_name(monkeypatch):
    from engine.memory_recall import entity_index

    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [
            {"given_name": "角色乙"}, {"given_name": "角色甲"}, {"given_name": "妹妹"},
        ])})(),
    )
    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {"角色乙→角色甲": {
            "from": "角色乙", "to": "角色甲", "nature": "兄妹", "relationship_anchor": "",
            "from_ref_terms": ["妹妹"], "to_ref_terms": [],
        }}},
    )
    alias_map = entity_index._character_alias_map()
    assert "妹妹" not in alias_map  # "妹妹" 本身就是另一个真实角色的 given_name -- 不能抢占


def test_character_alias_map_missing_graph_degrades_empty(monkeypatch):
    from engine.memory_recall import entity_index

    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "甲"}])})(),
    )

    def _boom():
        raise OSError("no graph")

    monkeypatch.setattr("engine.setup.cast.relationship_graph.load_graph", _boom)
    assert entity_index._character_alias_map() == {}


def test_scan_entities_resolves_alias_to_canonical_name(monkeypatch):
    from engine.memory_recall import entity_index

    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [
            {"given_name": "角色乙"}, {"given_name": "角色甲"},
        ])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {"factions": [], "geography": [], "races": []})})(),
    )
    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {"角色乙→角色甲": {
            "from": "角色乙", "to": "角色甲", "nature": "兄妹", "relationship_anchor": "",
            "from_ref_terms": ["妹妹"], "to_ref_terms": [],
        }}},
    )
    assert entity_index.scan_entities("妹妹今天很开心") == ["角色乙"]


def test_scan_characters_does_not_resolve_relational_aliases(monkeypatch):
    """scan_characters deliberately excludes the relationship-graph alias layer (unlike
    scan_entities) -- a relational term/epithet can be non-ambiguous in the graph today yet get
    reused narratively for a different character (this novel's genre-typical "废物"/"主人" style
    epithets are exactly this case) or appear in prose the graph never modeled at all. Trusting
    it here would let an unrelated character earn a full persona card on a false-positive match.
    See docs/superpowers/specs/2026-07-26-sandbox-present-vs-related-cast-design.md."""
    from engine.memory_recall import entity_index

    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [
            {"given_name": "角色乙"}, {"given_name": "角色甲"},
        ])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {"factions": [], "geography": [], "races": []})})(),
    )
    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {"角色乙→角色甲": {
            "from": "角色乙", "to": "角色甲", "nature": "兄妹", "relationship_anchor": "",
            "from_ref_terms": ["妹妹"], "to_ref_terms": [],
        }}},
    )
    assert entity_index.scan_characters("角色甲看着妹妹笑了") == ["角色甲"]


def test_invalidate_entity_vocab_cache_rebuilds_alias_layer(monkeypatch):
    from engine.memory_recall import entity_index

    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "角色甲"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {"factions": [], "geography": [], "races": []})})(),
    )
    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {}},
    )
    assert entity_index.scan_entities("妹妹") == []  # 还没有别名

    monkeypatch.setattr(
        "engine.setup.cast.relationship_graph.load_graph",
        lambda: {"groups": {}, "edges": {"角色乙→角色甲": {
            "from": "角色乙", "to": "角色甲", "nature": "兄妹", "relationship_anchor": "",
            "from_ref_terms": ["妹妹"], "to_ref_terms": [],
        }}},
    )
    entity_index.invalidate_entity_vocab_cache()
    assert entity_index.scan_entities("妹妹") == ["角色乙"]


def test_name_fragment_alias_map_strips_surname(monkeypatch):
    from engine.memory_recall import entity_index

    alias_map = entity_index._name_fragment_alias_map({"天童爱丽丝"})
    assert alias_map == {"爱丽丝": "天童爱丽丝", "童爱丽丝": "天童爱丽丝"}


def test_name_fragment_alias_map_drops_ambiguous_fragment(monkeypatch):
    from engine.memory_recall import entity_index

    #Both names strip(1) to the same "美丽" -- ambiguous, dropped (strip(2) is 1 char, too short)
    alias_map = entity_index._name_fragment_alias_map({"陈美丽", "王美丽"})
    assert alias_map == {}


def test_name_fragment_alias_map_drops_fragment_colliding_with_real_name(monkeypatch):
    from engine.memory_recall import entity_index

    #"司马相如" strip(2) -> "相如", which collides with another character's real given_name
    alias_map = entity_index._name_fragment_alias_map({"司马相如", "相如"})
    assert alias_map == {"马相如": "司马相如"}  # "相如" itself dropped, not "马相如"


def test_name_fragment_alias_map_skips_short_names(monkeypatch):
    from engine.memory_recall import entity_index

    #2-character given names produce only sub-2-character fragments -- nothing to register
    assert entity_index._name_fragment_alias_map({"甲", "小美", "张三"}) == {}


def test_world_keyword_alias_map_resolves_keyword_to_canonical_name(monkeypatch):
    from engine.memory_recall import entity_index

    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "power_system": [
                {"name": "信仰丧失", "desc": "d", "keywords": ["神像崩塌", "祷告"]},
            ],
        })})(),
    )
    alias_map = entity_index._world_keyword_alias_map(vocab=set())
    assert alias_map == {"神像崩塌": "信仰丧失", "祷告": "信仰丧失"}


def test_world_keyword_alias_map_drops_keyword_colliding_with_vocab_name(monkeypatch):
    from engine.memory_recall import entity_index

    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "power_system": [{"name": "信仰丧失", "desc": "d", "keywords": ["玉佩"]}],
        })})(),
    )
    # "玉佩" 已经是 vocab 里的一个真实名字（比如某件法器），不能被 alias 遮蔽
    alias_map = entity_index._world_keyword_alias_map(vocab={"玉佩"})
    assert alias_map == {}


def test_world_keyword_alias_map_drops_ambiguous_keyword_shared_by_two_entries(monkeypatch):
    from engine.memory_recall import entity_index

    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "power_system": [{"name": "信仰丧失", "desc": "d", "keywords": ["崩塌"]}],
            "core_themes": [{"name": "末世绝望", "desc": "d", "keywords": ["崩塌"]}],
        })})(),
    )
    alias_map = entity_index._world_keyword_alias_map(vocab=set())
    assert alias_map == {}  # 两个条目共用同一个线索词 -- 歧义，都不注册


def test_world_keyword_alias_map_missing_source_degrades_empty(monkeypatch):
    from engine.memory_recall import entity_index

    def _raise():
        raise OSError("boom")

    monkeypatch.setattr("repositories.get_world_repo", _raise)
    assert entity_index._world_keyword_alias_map(vocab=set()) == {}


def test_scan_entities_resolves_world_keyword_alias_to_canonical_name(monkeypatch):
    from engine.memory_recall import entity_index

    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "power_system": [
                {"name": "信仰丧失", "desc": "d", "keywords": ["神像崩塌"]},
            ],
        })})(),
    )
    assert entity_index.scan_entities("那一夜神像崩塌") == ["信仰丧失"]


def test_scan_characters_resolves_given_name_fragment(monkeypatch):
    """Regression test: real-data migration found compound given names (surname + given
    name, e.g. 上官铁柱) are commonly referred to by given-name-only in prose (铁柱),
    which the old given_name-exact-match-only vocab silently missed entirely."""
    from engine.memory_recall import entity_index

    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [
            {"given_name": "上官铁柱"}, {"given_name": "欧阳二狗"},
        ])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {"factions": [], "geography": [], "races": []})})(),
    )
    assert entity_index.scan_characters("铁柱和二狗打招呼") == ["上官铁柱", "欧阳二狗"]


def test_scan_entities_also_resolves_given_name_fragment(monkeypatch):
    from engine.memory_recall import entity_index

    entity_index.invalidate_entity_vocab_cache()
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "司马相如"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {"factions": [], "geography": [], "races": []})})(),
    )
    assert entity_index.scan_entities("相如走了进来") == ["司马相如"]


def test_automaton_cache_is_sharded_per_novel(monkeypatch):
    from engine.memory_recall import entity_index

    entity_index.invalidate_entity_vocab_cache("novel-A")
    entity_index.invalidate_entity_vocab_cache("novel-B")

    def lore_for(names):
        return lambda: type("R", (), {"list_raw": staticmethod(lambda: [
            {"given_name": n} for n in names
        ])})()

    def world_empty():
        return type("R", (), {"get": staticmethod(lambda: {
            "factions": [], "geography": [], "races": [],
        })})()

    monkeypatch.setattr("repositories.get_world_repo", world_empty)

    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "novel-A")
    monkeypatch.setattr("repositories.get_lore_repo", lore_for(["甲角色"]))
    assert entity_index.scan_entities("甲角色出场了") == ["甲角色"]

    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "novel-B")
    monkeypatch.setattr("repositories.get_lore_repo", lore_for(["乙角色"]))
    assert entity_index.scan_entities("乙角色出场了") == ["乙角色"]

    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "novel-A")
    assert entity_index.scan_entities("甲角色出场了") == ["甲角色"]


def test_persist_and_restore_automaton_cache(tmp_path, monkeypatch):
    from engine.memory_recall import entity_index
    from repositories.registry_store import get_registry_connection

    monkeypatch.setattr("utils.paths.novels_dir", lambda: str(tmp_path))
    (tmp_path / "novel-P" / "lore").mkdir(parents=True)
    conn = get_registry_connection()
    conn.execute(
        "INSERT INTO novels (id, name, created_at, is_active) VALUES (?, ?, ?, ?)",
        ("novel-P", "P", "2020-01-01T00:00:00+00:00", 0),
    )
    conn.commit()
    entity_index.invalidate_entity_vocab_cache("novel-P")

    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "novel-P")
    monkeypatch.setattr(
        "repositories.get_lore_repo",
        lambda: type("R", (), {"list_raw": staticmethod(lambda: [{"given_name": "甲角色"}])})(),
    )
    monkeypatch.setattr(
        "repositories.get_world_repo",
        lambda: type("R", (), {"get": staticmethod(lambda: {
            "factions": [], "geography": [], "races": [],
        })})(),
    )
    assert entity_index.scan_entities("甲角色出场了") == ["甲角色"]

    entity_index._automaton_cache.clear()
    entity_index._character_automaton_cache.clear()
    entity_index._persisted_entries.clear()

    def _boom():
        raise AssertionError("should not re-scan the repo during restore")

    monkeypatch.setattr("repositories.get_lore_repo", _boom)

    import asyncio
    asyncio.run(entity_index.restore_persisted_automata())
    assert entity_index.scan_entities("甲角色出场了") == ["甲角色"]
