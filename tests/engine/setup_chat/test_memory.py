import asyncio
import inspect

import pytest
from engine.setup_chat.memory import (
    INTERRUPTED_MARKER,
    INTERRUPTED_TOOL_RESULT,
    DecisionDomain,
    RepairMode,
    _bg_tasks,
    _consolidate_domain,
    _distill_cut,
    _domains_over_quota,
    _feed_start,
    _inflight,
    _in_scope_domains,
    _render_memory,
    _run_distill,
    _safe_tail_messages,
    _spawn_distill,
    _tool_call_ids,
    _watermark,
    apply_distill_ops,
    distill_decisions,
    ensure_checkpoint_messages_valid,
    load_memory,
    make_pre_model_hook,
    repair_tool_call_sequence,
    save_memory,
)
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


@pytest.fixture(autouse=True)
def _reset_world_pipeline_globals(monkeypatch):
    """Process-global pipeline markers must not leak between tests."""
    import engine.setup_chat.skeleton_pipeline as sp
    import engine.setup_chat.world_pipeline as wp

    wp._ACTIVE_TIMELINE_TARGET = None
    wp._ACTIVE_TARGET = None
    monkeypatch.setattr(wp, "_stage_done", lambda stage, chapter: True)
    monkeypatch.setattr("engine.setup_chat.plan_runner._chapter_timeline_done", lambda ch: True)
    monkeypatch.setattr(sp, "_ACTIVE_CHAPTER", None)
    yield
    wp._ACTIVE_TIMELINE_TARGET = None
    wp._ACTIVE_TARGET = None


def test_load_missing_returns_empty(tmp_path):
    assert load_memory(str(tmp_path)) == {"decisions": []}


def test_save_then_load_roundtrip(tmp_path):
    decision = {
        "id": "d1", "domain": "world", "text": "主角是X",
        "status": "active", "alert": None, "ts": 1000.0,
    }
    save_memory(str(tmp_path), {"decisions": [decision]})
    assert load_memory(str(tmp_path))["decisions"] == [decision]


def test_load_upgrades_v1_flat_strings(tmp_path):
    save_memory(str(tmp_path), {"decisions": ["主角是X"]})
    out = load_memory(str(tmp_path))["decisions"]
    assert len(out) == 1
    d = out[0]
    assert d["text"] == "主角是X"
    assert d["domain"] == "misc"
    assert d["status"] == "active"
    assert d["alert"] is None
    assert isinstance(d["id"], str) and d["id"]
    assert isinstance(d["ts"], float)


def test_load_upgrade_is_idempotent_for_v2_shape(tmp_path):
    decision = {
        "id": "d1", "domain": "cast", "text": "角色A怕水",
        "status": "active", "alert": "veto", "ts": 500.0,
    }
    save_memory(str(tmp_path), {"decisions": [decision]})
    assert load_memory(str(tmp_path))["decisions"] == [decision]


def test_load_bad_json_degrades(tmp_path):
    (tmp_path / "memory.json").write_text("{bad", encoding="utf-8")
    assert load_memory(str(tmp_path)) == {"decisions": []}


def _msg(role, content):
    return type("M", (), {"type": role, "content": content})()


@pytest.mark.asyncio
async def test_distill_returns_structured_ops():
    async def call_llm(system, user):
        return (
            '{"add": [{"text": "否决校园背景", "domain": "world", "alert": "veto"}], '
            '"supersede": []}'
        )

    out = await distill_decisions(
        [_msg("human", "不要校园背景"), _msg("ai", "明白")], [], call_llm,
    )
    assert out["add"] == [{"text": "否决校园背景", "domain": "world", "alert": "veto"}]
    assert out["supersede"] == []


@pytest.mark.asyncio
async def test_distill_empty_on_error():
    async def call_llm(system, user):
        raise RuntimeError("boom")

    out = await distill_decisions([_msg("human", "x")], [], call_llm)
    assert out == {"add": [], "supersede": []}


@pytest.mark.asyncio
async def test_distill_empty_on_unparseable_output():
    async def call_llm(system, user):
        return "不是 JSON 的纯文本"

    out = await distill_decisions([_msg("human", "x")], [], call_llm)
    assert out == {"add": [], "supersede": []}


@pytest.mark.asyncio
async def test_distill_feeds_active_ledger_to_prompt():
    captured = {}

    async def call_llm(system, user):
        captured["user"] = user
        return '{"add": [], "supersede": []}'

    active = [{
        "id": "d1", "domain": "world", "text": "已确立X",
        "status": "active", "alert": None, "ts": 1.0,
    }]
    await distill_decisions([_msg("human", "继续")], active, call_llm)
    assert "d1" in captured["user"] and "已确立X" in captured["user"]


def test_apply_distill_ops_add_appends_new_active_entry():
    prev = {"decisions": []}
    ops = {"add": [{"text": "主角是剑客", "domain": "cast", "alert": None}], "supersede": []}
    out = apply_distill_ops(prev, ops)
    assert len(out["decisions"]) == 1
    d = out["decisions"][0]
    assert d["text"] == "主角是剑客" and d["domain"] == "cast"
    assert d["status"] == "active" and d["alert"] is None


def test_apply_distill_ops_supersede_flips_old_and_appends_replacement():
    prev = {"decisions": [{
        "id": "d1", "domain": "world", "text": "不能有魔法",
        "status": "active", "alert": "veto", "ts": 1.0,
    }]}
    ops = {
        "add": [],
        "supersede": [{"id": "d1", "replacement": "必须有魔法", "domain": "world", "alert": "mandate"}],
    }
    out = apply_distill_ops(prev, ops)
    old = next(d for d in out["decisions"] if d["id"] == "d1")
    assert old["status"] == "superseded"
    new = next(d for d in out["decisions"] if d["id"] != "d1")
    assert new["text"] == "必须有魔法" and new["alert"] == "mandate" and new["status"] == "active"


def test_apply_distill_ops_supersede_unknown_id_is_ignored():
    prev = {"decisions": []}
    ops = {"add": [], "supersede": [{"id": "ghost", "replacement": "x"}]}
    out = apply_distill_ops(prev, ops)
    assert out["decisions"] == []


def _decision(domain, text, alert=None, id_=None):
    return {
        "id": id_ or text, "domain": domain, "text": text,
        "status": "active", "alert": alert, "ts": 1.0,
    }


def test_domains_over_quota_counts_only_active():
    decisions = [
        {"id": f"a{i}", "domain": "world", "text": f"t{i}",
         "status": "active", "alert": None, "ts": 1.0}
        for i in range(21)
    ] + [
        {"id": "s1", "domain": "world", "text": "old",
         "status": "superseded", "alert": None, "ts": 1.0},
    ]
    mem = {"decisions": decisions}
    over = _domains_over_quota(mem)
    assert over == [DecisionDomain.WORLD]


def test_domains_over_quota_empty_when_within_limit():
    decisions = [
        {"id": f"a{i}", "domain": "cast", "text": f"t{i}",
         "status": "active", "alert": None, "ts": 1.0}
        for i in range(20)
    ]
    assert _domains_over_quota({"decisions": decisions}) == []


@pytest.mark.asyncio
async def test_consolidate_domain_compresses_and_preserves_alert(tmp_path):
    persist = str(tmp_path)
    mergeable = [
        {"id": f"a{i}", "domain": "world", "text": f"细碎决策{i}",
         "status": "active", "alert": None, "ts": float(i)}
        for i in range(21)
    ]
    locked = {
        "id": "veto1", "domain": "world", "text": "绝不能有魔法",
        "status": "active", "alert": "veto", "ts": 99.0,
    }
    save_memory(persist, {"decisions": [*mergeable, locked]})

    async def call_llm(system, user):
        assert "绝不能有魔法" not in user  # alert entries excluded from prompt
        return '{"merged": ["合并后的世界观决策A", "合并后的世界观决策B"]}'

    await _consolidate_domain(persist, DecisionDomain.WORLD, call_llm)
    mem = load_memory(persist)
    active_world = [d for d in mem["decisions"] if d["domain"] == "world" and d["status"] == "active"]
    assert len(active_world) == 3  # 2 merged + 1 alert preserved
    assert any(d["text"] == "绝不能有魔法" and d["alert"] == "veto" for d in active_world)
    assert any(d["text"] == "合并后的世界观决策A" for d in active_world)


@pytest.mark.asyncio
async def test_consolidate_domain_noop_when_within_quota(tmp_path):
    persist = str(tmp_path)
    save_memory(persist, {"decisions": [
        {"id": "a1", "domain": "cast", "text": "x",
         "status": "active", "alert": None, "ts": 1.0},
    ]})

    async def call_llm(system, user):
        raise AssertionError("不该压缩")

    await _consolidate_domain(persist, DecisionDomain.CAST, call_llm)


@pytest.mark.asyncio
async def test_run_distill_triggers_consolidation_when_over_quota(tmp_path):
    persist = str(tmp_path)
    seed = [
        {"id": f"a{i}", "domain": "plot", "text": f"t{i}",
         "status": "active", "alert": None, "ts": float(i)}
        for i in range(20)
    ]
    save_memory(persist, {"decisions": seed, "distilled_count": 0})

    calls = {"n": 0}

    async def call_llm(system, user):
        calls["n"] += 1
        if calls["n"] == 1:
            return '{"add": [{"text": "第21条", "domain": "plot", "alert": null}], "supersede": []}'
        return '{"merged": ["压缩后的 plot 决策"]}'

    await _run_distill(persist, [_msg("human", "x")], 5, call_llm)
    mem = load_memory(persist)
    active_plot = [d for d in mem["decisions"] if d["domain"] == "plot" and d["status"] == "active"]
    assert len(active_plot) <= 20
    assert calls["n"] == 2  # one distill + one consolidate


def test_render_memory_empty_when_no_visible_decisions():
    assert _render_memory({"decisions": []}) == ""


def test_render_memory_full_inject_when_no_active_signal():
    mem = {"decisions": [
        _decision("world", "世界观决策"), _decision("cast", "角色决策"),
        _decision("plot", "剧情决策"),
    ]}
    out = _render_memory(mem)
    assert "世界观决策" in out and "角色决策" in out and "剧情决策" in out


def test_render_memory_gates_to_active_chapter_domain():
    import engine.setup_chat.skeleton_pipeline as sp
    sp._ACTIVE_CHAPTER = 3
    mem = {"decisions": [
        _decision("plot", "剧情决策"), _decision("cast", "角色决策"),
        _decision("world", "世界观决策"), _decision("misc", "杂项决策"),
    ]}
    out = _render_memory(mem)
    assert "剧情决策" in out  # plot domain, gating hit
    assert "世界观决策" in out and "杂项决策" in out  # always-injected domains
    assert "角色决策" not in out  # cast domain not in scope


def test_render_memory_alert_bypasses_gating():
    import engine.setup_chat.skeleton_pipeline as sp
    sp._ACTIVE_CHAPTER = 3
    mem = {"decisions": [
        _decision("cast", "普通角色偏好"),
        _decision("cast", "角色A绝不能死", alert="veto"),
    ]}
    out = _render_memory(mem)
    assert "角色A绝不能死" in out  # alert cross-domain inject
    assert "普通角色偏好" not in out  # non-alert cast still gated


def test_render_memory_ignores_superseded():
    mem = {"decisions": [
        {"id": "d1", "domain": "misc", "text": "旧的", "status": "superseded",
         "alert": None, "ts": 1.0},
    ]}
    assert _render_memory(mem) == ""


def test_in_scope_domains_reflects_timeline_target():
    import engine.setup_chat.world_pipeline as wp
    wp._ACTIVE_TIMELINE_TARGET = (3, "角色A")
    assert _in_scope_domains() == {DecisionDomain.CAST}


def test_line_echoes_decision_matches_dict_text():
    from engine.setup_chat.memory import _line_echoes_decision

    decisions = [_decision("misc", "主角是孤儿剑客,武器是长剑")]
    assert _line_echoes_decision("- 主角是孤儿剑客,武器是长剑", decisions)
    assert not _line_echoes_decision("- 完全不相关的一行", decisions)


def test_strip_memory_for_display_removes_domain_subheaders():
    from engine.setup_chat.memory import strip_memory_for_display, _MEMORY_INTERNAL_TAG

    content = (
        f"{_MEMORY_INTERNAL_TAG}\n### world\n- 世界观决策\n### cast\n- 角色决策\n\n正文开始"
    )
    out = strip_memory_for_display(content)
    assert out == "正文开始"
    assert "###" not in out and "世界观决策" not in out


def test_safe_tail_keeps_tool_round_intact():
    ai = type("M", (), {"type": "ai", "content": "", "tool_calls": [{"id": "1"}, {"id": "2"}]})()
    t1 = ToolMessage(content="r1", tool_call_id="1")
    t2 = ToolMessage(content="r2", tool_call_id="2")
    human = _msg("human", "继续")
    msgs = [_msg("human", "旧")] * 8 + [ai, t1, t2, _msg("ai", "好了"), human]
    #When k=3 falls on t2, it must fall back to ai with a complete tool round.
    tail = _safe_tail_messages(msgs, 3)
    assert tail[0] is ai
    assert tail[1] is t1 and tail[2] is t2


@pytest.mark.asyncio
async def test_hook_feeds_memory_plus_untrimmed_tail(tmp_path, monkeypatch):
    """Feed model = memory + unsteamed tail (non-fixed K); the distillation background is asynchronous, and the water level is advanced only after completion."""
    monkeypatch.setattr(
        "engine.setup_chat.novel_context.build_inherited_setup_context",
        lambda: None,
    )

    # Gated on a release event rather than returning instantly: the hook itself now has a
    # genuine await point (asyncio.to_thread for tool routing), so the background distill
    # task gets a scheduling chance while the hook is suspended. A call_llm that resolves
    # immediately could race and finish before the hook returns; gating on the event proves
    # the hook doesn't wait for distillation regardless of scheduling order.
    release = asyncio.Event()

    async def call_llm(system, user):
        await release.wait()
        return '{"add": [{"text": "已确立 X", "domain": "misc", "alert": null}], "supersede": []}'

    hook = make_pre_model_hook(lambda: str(tmp_path), call_llm, K=4, T=8)
    msgs = [_msg("human" if i % 2 == 0 else "ai", f"m{i}") for i in range(12)]
    out = await hook({"messages": msgs})
    fed = out["llm_input_messages"]

    #Feed the entire unsteamed tail (the memory is still empty at this moment, because the distillation is not completed asynchronously) → 12 original messages + 1 manual mode banner
    from engine.setup_chat.memory import _ACTIVATION_HEADER
    from engine.setup_chat.mode import MANUAL_MODE_BANNER
    expected_banner = _ACTIVATION_HEADER + "\n\n" + MANUAL_MODE_BANNER
    assert [getattr(m, "content", "") for m in fed] == [expected_banner] + [f"m{i}" for i in range(12)]
    #Asynchronous:memory has not been updated when hook returns
    assert load_memory(str(tmp_path)).get("distilled_count", 0) == 0
    #Wait for the background distillation to be completed → the water level is advanced and the decision is merged
    release.set()
    await asyncio.gather(*[t for t in _bg_tasks if not t.done()])
    mem = load_memory(str(tmp_path))
    assert mem["distilled_count"] == 8  # _safe_tail_start(12, K=4)
    assert "已确立 X" in {d["text"] for d in mem["decisions"]}


@pytest.mark.asyncio
async def test_hook_under_threshold_no_distill(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "engine.setup_chat.novel_context.build_inherited_setup_context",
        lambda: None,
    )

    async def call_llm(system, user):
        raise AssertionError("不该蒸馏")

    hook = make_pre_model_hook(lambda: str(tmp_path), call_llm, K=4, T=8)
    msgs = [_msg("human", f"m{i}") for i in range(3)]
    out = await hook({"messages": msgs})
    fed = out["llm_input_messages"]
    from engine.setup_chat.memory import _ACTIVATION_HEADER
    from engine.setup_chat.mode import MANUAL_MODE_BANNER
    expected_banner = _ACTIVATION_HEADER + "\n\n" + MANUAL_MODE_BANNER
    assert [getattr(m, "content", "") for m in fed] == [expected_banner, "m0", "m1", "m2"]
    assert not [t for t in _bg_tasks if not t.done()]  #Distillation not triggered


@pytest.mark.asyncio
async def test_hook_caps_stuck_watermark_so_new_messages_appear(tmp_path, monkeypatch):
    """
After concurrent distillation writes cut back out of bounds (water level > current number of messages), it will be clamped back in each round.
    The feed window will not continue to degenerate into just memory - new messages can appear in the feed window immediately."""
    monkeypatch.setattr(
        "engine.setup_chat.novel_context.build_inherited_setup_context",
        lambda: None,
    )
    #After simulating the race condition: distilled_count far exceeds the current number of messages
    save_memory(str(tmp_path), {
        "decisions": [{"id": "d1", "domain": "misc", "text": "旧决策",
                        "status": "active", "alert": None, "ts": 1.0}],
        "distilled_count": 80,
    })

    async def call_llm(system, user):
        raise AssertionError("尾巴不足，不该蒸馏")

    hook = make_pre_model_hook(lambda: str(tmp_path), call_llm, K=4, T=100)
    msgs = [_msg("human", f"m{i}") for i in range(5)]
    await hook({"messages": msgs})
    #The water level has been clamped back to ≤ the current number of messages (no longer stuck at 80)
    assert load_memory(str(tmp_path))["distilled_count"] <= 5

    #Another new message → appears in the feeding window (not removed by the high water line clamp)
    out = await hook({"messages": [*msgs, _msg("human", "新消息")]})
    fed = out["llm_input_messages"]
    assert any(getattr(m, "content", "") == "新消息" for m in fed)


def test_build_agent_wires_pre_model_hook():
    import engine.setup_chat.agent as a

    src = inspect.getsource(a.build_agent)
    assert "pre_model_hook" in src and "make_pre_model_hook" in src


def test_distilled_count_roundtrips(tmp_path):
    save_memory(str(tmp_path), {"decisions": ["x"], "distilled_count": 7})
    assert load_memory(str(tmp_path))["distilled_count"] == 7


def test_watermark_defaults_zero():
    assert _watermark({"decisions": []}) == 0
    assert _watermark({"decisions": [], "distilled_count": 5}) == 5
    assert _watermark({"decisions": [], "distilled_count": None}) == 0
    assert _watermark({"decisions": [], "distilled_count": "bad"}) == 0


def test_distill_cut_below_threshold_returns_none():
    msgs = [_msg("human", f"m{i}") for i in range(10)]
    assert _distill_cut(msgs, 0, K=4, T=12) is None  #Tail 10 < T12


def test_distill_cut_triggers_and_leaves_k():
    msgs = [_msg("human" if i % 2 == 0 else "ai", f"m{i}") for i in range(20)]
    #tail 20 >= T8 → cut = _safe_tail_start(.,K=4) = 16 (no tool, n-K)
    assert _distill_cut(msgs, 0, K=4, T=8) == 16


def test_distill_cut_no_progress_returns_none():
    msgs = [_msg("human", f"m{i}") for i in range(10)]
    #The watermark is already at 8, cut=n-K=8, do not advance → None
    assert _distill_cut(msgs, 8, K=2, T=2) is None


def test_feed_start_skips_orphan_tool():
    t = ToolMessage(content="r", tool_call_id="1")
    msgs = [_msg("human", "a"), t, _msg("ai", "b")]
    #The watermark falls on an isolated tool → move forward to the next non-tool
    assert _feed_start(msgs, 1) == 2
    assert _feed_start(msgs, 0) == 0


def test_feed_start_rewinds_to_ai_when_watermark_on_tool_chain():
    ai = AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "1"}])
    t = ToolMessage(content="r", tool_call_id="1", name="x")
    msgs = [_msg("human", "a")] * 5 + [ai, t, _msg("human", "next")]
    assert _feed_start(msgs, 5) == 5
    #The water level falls on the tool and the AI ​​has been evaporated → skip the orphan tool
    assert _feed_start(msgs, 6) == 7


def test_repair_strips_incomplete_tool_round():
    ai = AIMessage(content="", tool_calls=[{"name": "a", "args": {}, "id": "1"}, {"name": "b", "args": {}, "id": "2"}], id="ai1")
    t1 = ToolMessage(content="r1", tool_call_id="1", name="a")
    human = _msg("human", "继续")
    msgs = [ai, t1, human]
    repaired, patches, report = repair_tool_call_sequence(msgs)
    assert len(repaired) == 4
    assert repaired[0].tool_calls
    assert isinstance(repaired[2], ToolMessage)
    assert repaired[2].tool_call_id == "2"
    assert repaired[2].status == "error"
    assert repaired[3] is human
    assert report.changed
    assert any(getattr(p, "id", None) == "synth-2" for p in patches)


def test_repair_keeps_complete_tool_round():
    ai = AIMessage(content="", tool_calls=[{"name": "a", "args": {}, "id": "1"}], id="ai1")
    t1 = ToolMessage(content="r1", tool_call_id="1", name="a")
    ai2 = AIMessage(content="好了", id="ai2")
    msgs = [ai, t1, ai2]
    repaired, patches, report = repair_tool_call_sequence(msgs)
    assert repaired == msgs
    assert patches == []
    assert not report.changed


def test_repair_coerces_orphan_tool_call_in_additional_kwargs():
    """
Streaming tool call interrupted: .tool_calls resolves to empty, but additional_kwargs['tool_calls'] remains of the original call.
    When langchain_openai transfers the payload, it will fall back and read additional_kwargs → resuscitate the air conditioner → DeepSeek 400.
    repair must detect additional_kwargs and force it into plain text (clear the residue), otherwise it will be permanently stuck."""
    #Breaking because arguments is incomplete JSON → .tool_calls resolves to empty and the call falls into invalid_tool_calls + additional_kwargs
    ai = AIMessage(
        content="明白了，我来改。",
        additional_kwargs={"tool_calls": [
            {"id": "call_x", "type": "function",
             "function": {"name": "generate_one_chapter", "arguments": '{"incomp'}},
        ]},
        id="ai1",
    )
    assert ai.tool_calls == [] and ai.invalid_tool_calls  #Reproduce true form
    human = _msg("human", "改好了吗")
    repaired, patches, report = repair_tool_call_sequence([ai, human])
    assert report.changed
    assert len(repaired) == 2
    #After the forced transfer, the three places no longer contain calls (the payload will no longer resurrect the dangling tool_call)
    assert repaired[0].tool_calls == []
    assert not getattr(repaired[0], "invalid_tool_calls", [])
    assert not (repaired[0].additional_kwargs or {}).get("tool_calls")
    assert repaired[0].content == "明白了，我来改。"
    assert repaired[1] is human


def test_tool_call_ids_detects_invalid_and_additional_kwargs():
    ai = AIMessage(content="x", additional_kwargs={
        "tool_calls": [{"id": "call_y", "type": "function",
                        "function": {"name": "f", "arguments": '{"bad'}}]})
    assert _tool_call_ids(ai) == {"call_y"}


def test_repair_drops_orphan_tool():
    t = ToolMessage(content="r", tool_call_id="1", name="a", id="t1")
    human = _msg("human", "hi")
    repaired, patches, report = repair_tool_call_sequence([t, human])
    assert repaired == [human]
    assert len(patches) == 1
    assert report.changed


def test_repair_changed_without_message_id():
    ai = AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "1"}])
    human = _msg("human", "继续")
    repaired, patches, report = repair_tool_call_sequence([ai, human])
    assert repaired[0].tool_calls
    assert isinstance(repaired[1], ToolMessage)
    assert report.changed
    assert len(patches) == 1
    assert patches[0].tool_call_id == "1"


@pytest.mark.asyncio
async def test_ensure_checkpoint_rewrites_broken_state(tmp_path):
    ai = AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "1"}], id="ai-broken")
    stored = [ai, _msg("human", "old")]

    class _FakeAgent:
        def __init__(self):
            self.updates: list = []

        async def aget_state(self, _cfg):
            return type("S", (), {"values": {"messages": list(stored)}})()

        async def aupdate_state(self, _cfg, values, **_kwargs):
            self.updates.append(values)

    agent = _FakeAgent()
    report = await ensure_checkpoint_messages_valid(agent, {"configurable": {"thread_id": "n1"}}, str(tmp_path))
    assert report.changed
    assert len(agent.updates) == 1
    msgs = agent.updates[0]["messages"]
    assert any(getattr(m, "tool_call_id", None) == "1" for m in msgs)


@pytest.mark.asyncio
async def test_hook_repairs_broken_tail_for_llm(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "engine.setup_chat.novel_context.build_inherited_setup_context",
        lambda: None,
    )
    ai = AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "1"}], id="ai-broken")
    msgs = [_msg("human", "old"), ai, _msg("human", "new")]

    async def call_llm(system, user):
        raise AssertionError("不该蒸馏")

    hook = make_pre_model_hook(lambda: str(tmp_path), call_llm, K=4, T=100)
    out = await hook({"messages": msgs})
    fed = out["llm_input_messages"]
    assert fed[-3].tool_calls
    assert isinstance(fed[-2], ToolMessage)
    assert "messages" in out


@pytest.mark.asyncio
async def test_run_distill_advances_watermark(tmp_path):
    async def call_llm(system, user):
        return '{"add": [{"text": "已确立 A", "domain": "misc", "alert": null}, ' \
               '{"text": "已确立 B", "domain": "misc", "alert": null}], "supersede": []}'

    await _run_distill(str(tmp_path), [_msg("human", "x"), _msg("ai", "y")], 6, call_llm)
    mem = load_memory(str(tmp_path))
    assert mem["distilled_count"] == 6
    texts = {d["text"] for d in mem["decisions"]}
    assert "已确立 A" in texts and "已确立 B" in texts


@pytest.mark.asyncio
async def test_run_distill_failure_keeps_watermark(tmp_path):
    save_memory(str(tmp_path), {
        "decisions": [{"id": "old1", "domain": "misc", "text": "旧",
                        "status": "active", "alert": None, "ts": 1.0}],
        "distilled_count": 3,
    })

    async def call_llm(system, user):
        raise RuntimeError("boom")

    await _run_distill(str(tmp_path), [_msg("human", "x")], 9, call_llm)
    mem = load_memory(str(tmp_path))
    assert mem["distilled_count"] == 3
    assert [d["text"] for d in mem["decisions"]] == ["旧"]


@pytest.mark.asyncio
async def test_run_distill_empty_keeps_watermark(tmp_path):
    save_memory(str(tmp_path), {"decisions": [], "distilled_count": 2})

    async def call_llm(system, user):
        return ""  #Unable to steam content

    await _run_distill(str(tmp_path), [_msg("human", "x")], 9, call_llm)
    assert load_memory(str(tmp_path))["distilled_count"] == 2


async def _noop_llm(system: str, user: str) -> str:
    return ""


def _activation_header() -> str:
    from engine.setup_chat.skill_activation import _ACTIVATION_HEADER
    return _ACTIVATION_HEADER


@pytest.mark.asyncio
async def test_pre_hook_injects_activated_skill_body(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "engine.setup_chat.novel_context.build_inherited_setup_context",
        lambda: None,
    )
    from engine.setup_chat import memory as mem_mod

    monkeypatch.setattr(mem_mod, "build_skill_activations", lambda msgs, d: ["插件引导正文XYZ"])
    hook = make_pre_model_hook(lambda: str(tmp_path), _noop_llm)
    from langchain_core.messages import HumanMessage
    out = await hook({"messages": [HumanMessage(content="写第三章剧情")]})
    fed = out.get("llm_input_messages") or []
    texts = [getattr(m, "content", "") for m in fed]
    assert any("插件引导正文XYZ" in t for t in texts)
    assert any(_activation_header() in t for t in texts)


@pytest.mark.asyncio
async def test_pre_hook_injects_active_seed(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "engine.setup_chat.novel_context.build_inherited_setup_context",
        lambda: None,
    )
    from engine.setup_chat import memory as mem_mod

    monkeypatch.setattr(mem_mod, "build_skill_activations", lambda msgs, d: [])
    import engine.setup_chat.skeleton_pipeline as sp
    monkeypatch.setattr(sp, "active_seed_injection", lambda: "SEED-MARKER-XYZ")

    hook = make_pre_model_hook(lambda: str(tmp_path), _noop_llm)
    from langchain_core.messages import HumanMessage
    out = await hook({"messages": [HumanMessage(content="扩写第三章骨架")]})
    texts = [getattr(m, "content", "") for m in (out.get("llm_input_messages") or [])]
    assert any("SEED-MARKER-XYZ" in t for t in texts)
    assert any(_activation_header() in t for t in texts)


@pytest.mark.asyncio
async def test_pre_hook_omits_seed_when_none(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "engine.setup_chat.novel_context.build_inherited_setup_context",
        lambda: None,
    )
    from engine.setup_chat import memory as mem_mod

    monkeypatch.setattr(mem_mod, "build_skill_activations", lambda msgs, d: [])
    import engine.setup_chat.skeleton_pipeline as sp
    monkeypatch.setattr(sp, "active_seed_injection", lambda: None)

    hook = make_pre_model_hook(lambda: str(tmp_path), _noop_llm)
    from langchain_core.messages import HumanMessage
    out = await hook({"messages": [HumanMessage(content="你好")]})
    texts = [getattr(m, "content", "") for m in (out.get("llm_input_messages") or [])]
    assert not any("SEED-MARKER" in t for t in texts)


@pytest.mark.asyncio
async def test_pre_hook_injects_active_timeline_seed(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "engine.setup_chat.novel_context.build_inherited_setup_context",
        lambda: None,
    )
    from engine.setup_chat import memory as mem_mod

    monkeypatch.setattr(mem_mod, "build_skill_activations", lambda msgs, d: [])
    import engine.setup_chat.world_pipeline as wp
    monkeypatch.setattr(wp, "active_timeline_seed_injection", lambda: "TIMELINE-SEED-MARKER-XYZ")

    hook = make_pre_model_hook(lambda: str(tmp_path), _noop_llm)
    from langchain_core.messages import HumanMessage
    out = await hook({"messages": [HumanMessage(content="推第三章甲的 timeline")]})
    texts = [getattr(m, "content", "") for m in (out.get("llm_input_messages") or [])]
    assert any("TIMELINE-SEED-MARKER-XYZ" in t for t in texts)
    assert any(_activation_header() in t for t in texts)


@pytest.mark.asyncio
async def test_pre_hook_omits_timeline_seed_when_none(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "engine.setup_chat.novel_context.build_inherited_setup_context",
        lambda: None,
    )
    from engine.setup_chat import memory as mem_mod

    monkeypatch.setattr(mem_mod, "build_skill_activations", lambda msgs, d: [])
    import engine.setup_chat.world_pipeline as wp
    monkeypatch.setattr(wp, "active_timeline_seed_injection", lambda: None)

    hook = make_pre_model_hook(lambda: str(tmp_path), _noop_llm)
    from langchain_core.messages import HumanMessage
    out = await hook({"messages": [HumanMessage(content="你好")]})
    texts = [getattr(m, "content", "") for m in (out.get("llm_input_messages") or [])]
    assert not any("TIMELINE-SEED-MARKER" in t for t in texts)


@pytest.mark.asyncio
async def test_pre_hook_injects_auto_banner_when_auto_mode_on(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "engine.setup_chat.novel_context.build_inherited_setup_context",
        lambda: None,
    )
    from engine.setup_chat import memory as mem_mod
    monkeypatch.setattr(mem_mod, "build_skill_activations", lambda msgs, d: [])
    from engine.setup_chat import mode as mode_mod
    monkeypatch.setattr(mode_mod, "_AUTO", True)

    hook = make_pre_model_hook(lambda: str(tmp_path), _noop_llm)
    from langchain_core.messages import HumanMessage
    out = await hook({"messages": [HumanMessage(content="帮我把这本书的设定建完")]})
    texts = [getattr(m, "content", "") for m in (out.get("llm_input_messages") or [])]
    assert any(mode_mod.AUTO_MODE_BANNER in t for t in texts)
    assert any(_activation_header() in t for t in texts)


@pytest.mark.asyncio
async def test_pre_hook_no_auto_banner_when_manual_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "engine.setup_chat.novel_context.build_inherited_setup_context",
        lambda: None,
    )
    from engine.setup_chat import memory as mem_mod
    monkeypatch.setattr(mem_mod, "build_skill_activations", lambda msgs, d: [])
    from engine.setup_chat import mode as mode_mod
    monkeypatch.setattr(mode_mod, "_AUTO", False)

    hook = make_pre_model_hook(lambda: str(tmp_path), _noop_llm)
    from langchain_core.messages import HumanMessage
    out = await hook({"messages": [HumanMessage(content="你好")]})
    texts = [getattr(m, "content", "") for m in (out.get("llm_input_messages") or [])]
    assert not any(mode_mod.AUTO_MODE_BANNER in t for t in texts)


@pytest.mark.asyncio
async def test_pre_model_hook_writes_routed_tool_names(tmp_path, monkeypatch):
    import engine.setup_chat.tool_router as tr

    monkeypatch.setattr(tr, "route_tool_names", lambda *a, **k: {"present_choices", "construct_world"})

    async def fake_llm(system, user):
        return ""

    hook = make_pre_model_hook(lambda: str(tmp_path), fake_llm)
    state = {"messages": [HumanMessage(content="你好")]}
    out = await hook(state)
    assert set(out["routed_tool_names"]) == {"present_choices", "construct_world"}


@pytest.mark.asyncio
async def test_pre_model_hook_does_not_block_event_loop(tmp_path, monkeypatch):
    """route_tool_names runs a CPU-bound embedding call; the hook must offload it to a
    thread (asyncio.to_thread) rather than run it inline, or every other coroutine on the
    process -- including the HTTP requests behind a frontend page navigation -- stalls for
    as long as the embedding takes."""
    import time

    import engine.setup_chat.tool_router as tr

    def slow_route_tool_names(*a, **k):
        time.sleep(0.2)
        return {"present_choices"}
    monkeypatch.setattr(tr, "route_tool_names", slow_route_tool_names)

    async def fake_llm(system, user):
        return ""

    hook = make_pre_model_hook(lambda: str(tmp_path), fake_llm)
    state = {"messages": [HumanMessage(content="你好")]}

    tick_count = 0

    async def ticker():
        nonlocal tick_count
        while True:
            await asyncio.sleep(0.02)
            tick_count += 1

    ticker_task = asyncio.create_task(ticker())
    try:
        await hook(state)
    finally:
        ticker_task.cancel()

    assert tick_count >= 5


@pytest.mark.asyncio
async def test_pre_hook_no_injection_when_router_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "engine.setup_chat.novel_context.build_inherited_setup_context",
        lambda: None,
    )
    from engine.setup_chat import memory as mem_mod

    monkeypatch.setattr(mem_mod, "build_skill_activations", lambda msgs, d: [])
    hook = make_pre_model_hook(lambda: str(tmp_path), _noop_llm)
    from langchain_core.messages import HumanMessage
    out = await hook({"messages": [HumanMessage(content="改个标题")]})
    texts = [getattr(m, "content", "") for m in (out.get("llm_input_messages") or [])]
    assert not any("建设管道进行中" in t for t in texts)
    from engine.setup_chat.mode import MANUAL_MODE_BANNER
    assert any(MANUAL_MODE_BANNER in t for t in texts)


@pytest.mark.asyncio
async def test_spawn_distill_single_flight(tmp_path):
    gate = asyncio.Event()

    async def call_llm(system, user):
        await gate.wait()
        return '{"add": [{"text": "X", "domain": "misc", "alert": null}], "supersede": []}'

    persist = str(tmp_path)
    _spawn_distill(persist, [_msg("human", "a")], 5, call_llm)
    _spawn_distill(persist, [_msg("human", "a")], 5, call_llm)  #Flying → Skip
    assert persist in _inflight
    inflight_tasks = [t for t in _bg_tasks if not t.done()]
    assert len(inflight_tasks) == 1
    gate.set()
    await asyncio.gather(*inflight_tasks)
    assert persist not in _inflight  #done_callback cleared


@pytest.mark.asyncio
async def test_spawn_distill_skips_empty_slice(tmp_path):
    async def call_llm(system, user):
        raise AssertionError("不该被调用")

    before = len(_bg_tasks)
    _spawn_distill(str(tmp_path), [], 5, call_llm)
    assert len(_bg_tasks) == before


@pytest.mark.asyncio
async def test_hook_includes_memory_system_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "engine.setup_chat.novel_context.build_inherited_setup_context",
        lambda: None,
    )
    save_memory(str(tmp_path), {
        "decisions": [{"id": "d1", "domain": "misc", "text": "老决策",
                        "status": "active", "alert": None, "ts": 1.0}],
        "distilled_count": 6,
    })

    async def call_llm(system, user):
        raise AssertionError("尾巴不足,不该蒸")

    hook = make_pre_model_hook(lambda: str(tmp_path), call_llm, K=4, T=8)
    msgs = [_msg("human" if i % 2 == 0 else "ai", f"m{i}") for i in range(9)]
    out = await hook({"messages": msgs})
    fed = out["llm_input_messages"]
    #The first one is memory system; followed by msgs[6:] (3 unsteamed tails)
    assert isinstance(fed[0], SystemMessage) and "老决策" in fed[0].content
    from engine.setup_chat.memory import _ACTIVATION_HEADER
    from engine.setup_chat.mode import MANUAL_MODE_BANNER
    expected_banner = _ACTIVATION_HEADER + "\n\n" + MANUAL_MODE_BANNER
    assert [getattr(m, "content", "") for m in fed[1:]] == [expected_banner, "m6", "m7", "m8"]


@pytest.mark.asyncio
async def test_hook_does_not_block_on_distill(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "engine.setup_chat.novel_context.build_inherited_setup_context",
        lambda: None,
    )
    gate = asyncio.Event()

    async def call_llm(system, user):
        await gate.wait()
        return '{"add": [{"text": "慢蒸出的决策", "domain": "misc", "alert": null}], "supersede": []}'

    hook = make_pre_model_hook(lambda: str(tmp_path), call_llm, K=4, T=8)
    msgs = [_msg("human" if i % 2 == 0 else "ai", f"m{i}") for i in range(12)]
    out = await hook({"messages": msgs})  #should not block on the gate
    assert len(out["llm_input_messages"]) == 13
    assert load_memory(str(tmp_path)).get("distilled_count", 0) == 0  #Distillation is still stuck
    gate.set()
    await asyncio.gather(*[t for t in _bg_tasks if not t.done()])
    assert load_memory(str(tmp_path))["distilled_count"] == 8


@pytest.mark.asyncio
async def test_hook_distill_writes_spawn_time_novel(tmp_path, monkeypatch):
    """
Capture persist when spawning; after that, even if active changes, it will be written back to the original novel file (no cross-file)."""
    monkeypatch.setattr(
        "engine.setup_chat.novel_context.build_inherited_setup_context",
        lambda: None,
    )
    novel_a = tmp_path / "a"
    novel_a.mkdir()

    async def call_llm(system, user):
        return '{"add": [{"text": "A 档决策", "domain": "misc", "alert": null}], "supersede": []}'

    hook = make_pre_model_hook(lambda: str(novel_a), call_llm, K=4, T=8)
    msgs = [_msg("human" if i % 2 == 0 else "ai", f"m{i}") for i in range(12)]
    await hook({"messages": msgs})
    await asyncio.gather(*[t for t in _bg_tasks if not t.done()])
    assert "A 档决策" in {d["text"] for d in load_memory(str(novel_a))["decisions"]}


def test_safe_stream_emit_len_holds_back_forming_block_header():
    """The formed internal block prefix is ​​retained (not exposed) to prevent stripping after live flash."""
    from engine.setup_chat.memory import safe_stream_emit_len

    #The half-block header "## current novel" is the true prefix of "## the current novel has been set" → withheld from this line
    buf = "好的，我来帮你。\n## 当前小说"
    n = safe_stream_emit_len(buf)
    assert buf[:n] == "好的，我来帮你。\n"  #Is that okay for a big guy?


def test_safe_stream_emit_len_releases_normal_heading():
    """
Ordinary ## headers (not internal block header prefixes) are allowed normally."""
    from engine.setup_chat.memory import safe_stream_emit_len

    buf = "前言\n## 我的小标题"
    assert safe_stream_emit_len(buf) == len(buf)  #Not any internal block prefix → full hair


def test_safe_stream_emit_len_no_trailing_line():
    """It ends with a line break (no half-line break) → full text."""
    from engine.setup_chat.memory import safe_stream_emit_len

    buf = "正文一段\n"
    assert safe_stream_emit_len(buf) == len(buf)


def _dangling_valid() -> list:
    return [
        HumanMessage(content="改第3章", id="h1"),
        AIMessage(
            content="好，我来改。",
            id="a1",
            tool_calls=[{"id": "call_1", "name": "patch_chapter", "args": {"chapter": 3, "ops": []}}],
        ),
    ]


def _dangling_invalid() -> list:
    m = AIMessage(content="", id="a1")
    m.additional_kwargs = {
        "tool_calls": [{"id": "call_x", "type": "function",
                        "function": {"name": "write_plot", "arguments": '{"chap'}}],
    }
    return [HumanMessage(content="写大纲", id="h1"), m]


class TestRepairModePair:
    def test_valid_dangling_gets_synth_failure_toolmessage(self):
        out, _patches, report = repair_tool_call_sequence(_dangling_valid(), mode=RepairMode.PAIR)
        assert report.changed
        assert report.dangling_ids == {"call_1"}
        assert report.dangling_tools == ["patch_chapter"]
        ai = out[1]
        assert ai.tool_calls and ai.tool_calls[0]["id"] == "call_1"
        tm = out[2]
        assert isinstance(tm, ToolMessage)
        assert tm.tool_call_id == "call_1"
        assert tm.status == "error"
        assert tm.content == INTERRUPTED_TOOL_RESULT

    def test_invalid_dangling_downgraded_with_marker_not_haode(self):
        out, _patches, report = repair_tool_call_sequence(_dangling_invalid(), mode=RepairMode.PAIR)
        assert report.changed
        assert report.dangling_ids == {"call_x"}
        ai = out[1]
        assert not ai.tool_calls
        assert ai.additional_kwargs.get("tool_calls") in (None, [])
        assert ai.content == INTERRUPTED_MARKER
        assert "好的。" not in ai.content

    def test_complete_round_untouched(self):
        msgs = _dangling_valid() + [
            ToolMessage(content="ok", tool_call_id="call_1", id="t1"),
            AIMessage(content="改好了", id="a2"),
        ]
        out, _patches, report = repair_tool_call_sequence(msgs, mode=RepairMode.PAIR)
        assert not report.changed
        assert out == msgs


class TestRepairModeResume:
    def test_valid_dangling_message_removed_entirely(self):
        out, _patches, report = repair_tool_call_sequence(_dangling_valid(), mode=RepairMode.RESUME)
        assert report.changed
        assert report.dangling_ids == {"call_1"}
        assert [getattr(m, "id", None) for m in out] == ["h1"]

    def test_invalid_dangling_message_removed_entirely(self):
        out, _patches, report = repair_tool_call_sequence(_dangling_invalid(), mode=RepairMode.RESUME)
        assert report.changed
        assert [getattr(m, "id", None) for m in out] == ["h1"]

    def test_partial_answers_of_removed_declaration_also_removed(self):
        msgs = [
            HumanMessage(content="x", id="h1"),
            AIMessage(content="", id="a1", tool_calls=[
                {"id": "c1", "name": "patch_chapter", "args": {}},
                {"id": "c2", "name": "write_plot", "args": {}},
            ]),
            ToolMessage(content="ok", tool_call_id="c1", id="t1"),
        ]
        out, _patches, report = repair_tool_call_sequence(msgs, mode=RepairMode.RESUME)
        assert report.changed
        assert [getattr(m, "id", None) for m in out] == ["h1"]
