import json

import pytest
from engine.setup.cast.incremental_relationship import generate_edges_for_new_character
from engine.setup.cast.relationship_graph import append_edge as real_append_edge


def _char(name: str, **fields) -> dict:
    return {"name": name, "given_name": name, **fields}


def _seed_edges_roster(db_path: str, *names: str) -> None:
    from repositories.sqlite_store import get_connection
    conn = get_connection(db_path)
    for i, name in enumerate(names):
        conn.execute(
            "INSERT OR IGNORE INTO lore_characters (name, data_json, seq) VALUES (?, ?, ?)",
            (name, json.dumps({"name": name}, ensure_ascii=False), i),
        )
    conn.commit()


@pytest.mark.asyncio
async def test_empty_roster_skips_llm_call():
    calls = []

    async def call_llm(system, user):
        calls.append(user)
        return "[]"

    out = await generate_edges_for_new_character(_char("甲"), [], call_llm=call_llm)
    assert out == []
    assert calls == []  # 没有已有角色可关联，压根不该调用 LLM


@pytest.mark.asyncio
async def test_appends_valid_edges_and_invalidates_cache(tmp_path, monkeypatch):
    p = str(tmp_path / "edges.jsonl")
    invalidated = {"n": 0}
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.invalidate_entity_vocab_cache",
        lambda: invalidated.__setitem__("n", invalidated["n"] + 1),
    )

    async def call_llm(system, user):
        assert "乙" in user and "甲" in user  # 新角色 + 已有花名册都喂进去了
        return json.dumps([
            {"from": "甲", "to": "乙", "nature": "师徒", "relationship_anchor": "",
             "from_ref_terms": ["师傅"], "to_ref_terms": []},
        ])

    existing = [_char("甲", role="师傅")]
    _seed_edges_roster(p, "甲", "乙")
    out = await generate_edges_for_new_character(
        _char("乙", role="徒弟"), existing, call_llm=call_llm, edges_path=p,
    )
    assert len(out) == 1 and out[0]["nature"] == "师徒"
    from engine.setup.cast.relationship_graph import load_graph
    g = load_graph(p)
    assert g["edges"]["甲→乙"]["from_ref_terms"] == ["师傅"]
    assert invalidated["n"] == 1


@pytest.mark.asyncio
async def test_invalid_edge_dropped_valid_edge_kept(tmp_path):
    p = str(tmp_path / "edges.jsonl")

    async def call_llm(system, user):
        return json.dumps([
            {"from": "路人", "to": "乙", "nature": "陌生", "from_ref_terms": [], "to_ref_terms": []},
            {"from": "甲", "to": "乙", "nature": "世仇", "from_ref_terms": [], "to_ref_terms": []},
        ])

    _seed_edges_roster(p, "甲", "乙")
    out = await generate_edges_for_new_character(
        _char("乙"), [_char("甲")], call_llm=call_llm, edges_path=p,
    )
    assert len(out) == 1 and out[0]["nature"] == "世仇"  # "路人"不在花名册内，被丢弃


@pytest.mark.asyncio
async def test_no_edges_does_not_invalidate_cache(tmp_path, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.invalidate_entity_vocab_cache",
        lambda: calls.__setitem__("n", calls["n"] + 1),
    )

    async def call_llm(system, user):
        return "[]"

    p = str(tmp_path / "edges.jsonl")
    out = await generate_edges_for_new_character(
        _char("乙"), [_char("甲")], call_llm=call_llm, edges_path=p,
    )
    assert out == []
    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_llm_call_failure_degrades_to_empty():
    async def boom(system, user):
        raise RuntimeError("llm down")

    out = await generate_edges_for_new_character(_char("乙"), [_char("甲")], call_llm=boom)
    assert out == []


@pytest.mark.asyncio
async def test_malformed_llm_output_degrades_to_empty(tmp_path):
    async def call_llm(system, user):
        return "not json at all"

    out = await generate_edges_for_new_character(
        _char("乙"), [_char("甲")], call_llm=call_llm, edges_path=str(tmp_path / "edges.jsonl"),
    )
    assert out == []


def test_default_call_llm_routes_through_incremental_relationship_node(monkeypatch):
    from engine.setup.cast import incremental_relationship as ir

    class _FakeLLM:
        async def ainvoke(self, _messages):
            return type("R", (), {"content": "[]"})()

    bind_calls: list[tuple[str, dict]] = []

    def fake_bind_node_llm(llm, agent, params):
        bind_calls.append((agent, params))
        return _FakeLLM()

    monkeypatch.setattr("llm.factory.get_cloud_llm", lambda: object())
    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"import_llm_params": {"incremental_relationship": {"temperature": 0.1}}},
    )
    monkeypatch.setattr("engine.modes.author_loop_skill_prefs.bind_node_llm", fake_bind_node_llm)

    caller = ir._default_call_llm()
    assert bind_calls == [(
        "incremental_relationship", {"incremental_relationship": {"temperature": 0.1}},
    )]
    assert callable(caller)


@pytest.mark.asyncio
async def test_append_edge_oserror_skips_edge_and_never_raises(tmp_path, monkeypatch):
    p = str(tmp_path / "edges.jsonl")
    calls: list[str] = []

    async def call_llm(system, user):
        return json.dumps([
            {"from": "甲", "to": "乙", "nature": "师徒", "from_ref_terms": [], "to_ref_terms": []},
            {"from": "甲", "to": "乙", "nature": "同门", "from_ref_terms": [], "to_ref_terms": []},
        ])

    real_append = real_append_edge

    def flaky_append(edge, path=None):
        calls.append(edge["nature"])
        if edge["nature"] == "同门":
            raise OSError("disk full")
        real_append(edge, path=path)

    monkeypatch.setattr(
        "engine.setup.cast.incremental_relationship.append_edge", flaky_append,
    )

    _seed_edges_roster(p, "甲", "乙")
    out = await generate_edges_for_new_character(
        _char("乙"), [_char("甲")], call_llm=call_llm, edges_path=p,
    )
    assert calls == ["师徒", "同门"]
    assert len(out) == 1 and out[0]["nature"] == "师徒"


@pytest.mark.asyncio
async def test_append_edge_oserror_on_first_edge_returns_empty(tmp_path, monkeypatch):
    async def call_llm(system, user):
        return json.dumps([
            {"from": "甲", "to": "乙", "nature": "师徒", "from_ref_terms": [], "to_ref_terms": []},
        ])

    def boom_append(edge, path=None):
        raise OSError("permission denied")

    monkeypatch.setattr(
        "engine.setup.cast.incremental_relationship.append_edge", boom_append,
    )

    out = await generate_edges_for_new_character(
        _char("乙"), [_char("甲")], call_llm=call_llm, edges_path=str(tmp_path / "edges.jsonl"),
    )
    assert out == []
