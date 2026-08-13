"""回合门控图:事件契约、线程纯净、记忆压缩(按 stage)、断点续跑。"""
import engine.author_loop.dialogue_mode.react_graph as rg
import pytest
from engine.author_loop.dialogue_mode.state import BeatInput, StageInput
from langchain_core.messages import ToolMessage


class FakeTurns:
    """prose_turn 按 stage 出正文。"""

    def __init__(self, prose_of=None):
        self._prose_of = prose_of or (lambda i, msgs: f"[正文{i}]")
        self.prose_calls = 0

    async def prose_turn(self, messages, *, step):
        self.prose_calls += 1
        return self._prose_of(step, messages)


async def _fake_llm(s, u, *a, **k):
    return ("PASS", 0, 0)


@pytest.fixture(autouse=True)
def _default_review_passes(monkeypatch):
    """默认让既有测试跳过审核门控——不测审核本身的用例不用关心字数/相似度/保真阈值。
    专门测审核行为的用例在各自函数体内用 monkeypatch.setattr(rg, "review_candidate", ...)
    覆盖这个默认值（同一个 monkeypatch 实例里后设置的生效）。"""
    from engine.author_loop.dialogue_mode.stage_review import ReviewResult

    async def _always_pass(**kw):
        return ReviewResult(passed=True, notes=[])
    monkeypatch.setattr(rg, "review_candidate", _always_pass)


def _stages(n=2, beats_per_stage=1):
    return [
        StageInput(
            chapter=1, stage=i, characters=["甲"],
            beats=[BeatInput(beat_intent=f"b{i}-{j}", characters=["甲"], chapter=1, stage=i)
                   for j in range(beats_per_stage)],
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_happy_path_events_and_parts(monkeypatch):
    async def fake_init(cards, stage_description, call_llm):
        return {"甲": {"psychology": "稳"}}

    async def fake_derive(prior, text, call_llm):
        return prior
    monkeypatch.setattr(rg, "derive_initial_states", fake_init)
    monkeypatch.setattr(rg, "derive_character_states", fake_derive)
    events = []

    async def emit(ev):
        events.append(ev)
    out = await rg.run_react_chapter_graph(_stages(2), FakeTurns(), _fake_llm, emit=emit)
    assert out == "[正文0]\n\n[正文1]"
    segs = [e for e in events if e["type"] == "author_loop_segment"]
    assert [(e["agent"], e["text"]) for e in segs] == [("synthesis", "[正文0]"),
                                                       ("synthesis", "[正文1]")]
    progress = [e for e in events if e["type"] == "author_loop_chapter_progress"]
    assert progress[-1]["done"] == 2 and progress[-1]["total"] == 2


@pytest.mark.asyncio
async def test_author_thread_contains_only_creation_rounds():
    """主笔线程纯净:每 stage=任务包+正文两条,无 ToolMessage/无状态请求。"""
    graph = rg.build_react_chapter_graph(FakeTurns(), _fake_llm)
    stages = [rg._stage_to_dict(s, i) for i, s in enumerate(_stages(2))]
    final = await graph.ainvoke(
        rg._initial_state(stages, prose_style=""),
        {"recursion_limit": 100, "configurable": {}},
    )
    msgs = final["messages"]
    assert len(msgs) == 1 + 2 * 2  #system + 每 stage(任务包+正文)
    assert not any(isinstance(m, ToolMessage) for m in msgs)
    assert not any("请报告状态" in str(m.content) for m in msgs)


@pytest.mark.asyncio
async def test_llm_view_compacts_old_stages_keeps_recent_full():
    """>KEEP_FULL_STAGES 个 stage 前的回合坍缩成骨架概要;最近 stage 全量;checkpoint 原文不动。"""
    seen_views = {}

    class SpyTurns(FakeTurns):
        async def prose_turn(self, messages, *, step):
            seen_views[step] = list(messages)
            return await super().prose_turn(messages, step=step)

    graph = rg.build_react_chapter_graph(SpyTurns(), _fake_llm)
    stages = [rg._stage_to_dict(s, i) for i, s in enumerate(_stages(3))]
    final = await graph.ainvoke(
        rg._initial_state(stages, prose_style=""),
        {"recursion_limit": 100, "configurable": {}},
    )
    view = seen_views[2]  #KEEP_FULL_STAGES=1 → 写第 3 个 stage 时只有第 2 个 stage 全量可见
    joined = "\n".join(str(m.content) for m in view)
    assert "【第 1 个 stage 定稿概要】" in joined and "b0-0" in joined
    assert "[正文0]" not in joined
    assert "[正文1]" in joined
    full = "\n".join(str(m.content) for m in final["messages"])
    assert "[正文0]" in full  #checkpoint 侧原文完整保留,压缩只是视图


@pytest.mark.asyncio
async def test_llm_view_full_before_cutoff():
    """前 KEEP_FULL_STAGES+1 个 stage 内不坍缩(cutoff<=0 直接原样)。"""
    seen_views = {}

    class SpyTurns(FakeTurns):
        async def prose_turn(self, messages, *, step):
            seen_views[step] = list(messages)
            return await super().prose_turn(messages, step=step)

    await rg.run_react_chapter_graph(_stages(2), SpyTurns(), _fake_llm)
    joined = "\n".join(str(m.content) for m in seen_views[1])
    assert "[正文0]" in joined and "定稿概要" not in joined


@pytest.mark.asyncio
async def test_resume_progress_starts_from_checkpoint_stage_idx(tmp_path):
    """续跑时 chapter_progress 应从 checkpoint 的 stage_idx 续报,不能重置为 done=0。"""
    crashed = {"done": False}
    progress: list[dict] = []

    async def emit(ev):
        progress.append(ev)

    class FlakyTurns(FakeTurns):
        async def prose_turn(self, messages, *, step):
            if step == 1 and not crashed["done"]:
                crashed["done"] = True
                raise RuntimeError("boom@stage2")
            return await super().prose_turn(messages, step=step)

    cp = str(tmp_path / "cp.sqlite")
    with pytest.raises(Exception):  #noqa: B017
        await rg.run_react_chapter_persisted(_stages(2), FlakyTurns(), _fake_llm, emit=emit,
                                             cp_path=cp, thread_id="ch1")
    progress.clear()
    await rg.run_react_chapter_persisted(_stages(2), FlakyTurns(), _fake_llm, emit=emit,
                                         cp_path=cp, thread_id="ch1", resume=True)
    first = next(e for e in progress if e["type"] == "author_loop_chapter_progress")
    assert first["done"] == 1
    assert first["total"] == 2
    assert first["chapter"] == 1


@pytest.mark.asyncio
async def test_persisted_resume_after_crash(tmp_path):
    """stage2 首跑崩溃→同 thread resume 不重写 stage1(镜像旧图回归)。"""
    crashed = {"done": False}

    class FlakyTurns(FakeTurns):
        async def prose_turn(self, messages, *, step):
            if step == 1 and not crashed["done"]:
                crashed["done"] = True
                raise RuntimeError("boom@stage2")
            return await super().prose_turn(messages, step=step)

    cp = str(tmp_path / "cp.sqlite")
    with pytest.raises(Exception):  #noqa: B017
        await rg.run_react_chapter_persisted(_stages(2), FlakyTurns(), _fake_llm,
                                             cp_path=cp, thread_id="ch1")
    out = await rg.run_react_chapter_persisted(_stages(2), FlakyTurns(), _fake_llm,
                                               cp_path=cp, thread_id="ch1", resume=True)
    assert out == "[正文0]\n\n[正文1]"


@pytest.mark.asyncio
async def test_part_stage_idx_tracks_origin_stage_skipping_empty_prose():
    """空正文 stage 被跳过时,part_stage_idx 必须精确记录每条 parts 真实来自哪个 stage 下标,
    不能假设 parts 与 stages 按位置 1:1(否则拼章时标题/地点会错位甚至全部丢失)。"""
    prose_of = lambda i, msgs: "" if i == 1 else f"[正文{i}]"  #noqa: E731
    graph = rg.build_react_chapter_graph(FakeTurns(prose_of), _fake_llm)
    stages = [rg._stage_to_dict(s, i) for i, s in enumerate(_stages(3))]
    final = await graph.ainvoke(
        rg._initial_state(stages, prose_style=""),
        {"recursion_limit": 100, "configurable": {}},
    )
    assert final["parts"] == ["[正文0]", "[正文2]"]
    assert final["part_stage_idx"] == [0, 2]


def test_stage_to_dict_carries_sensation_notes():
    beat = BeatInput(beat_intent="拍甲", sensation_notes=["小腹发烫"])
    stage = StageInput(chapter=1, stage=1, characters=["甲"], beats=[beat])
    d = rg._stage_to_dict(stage, 0)
    assert d["beats"][0]["sensation_notes"] == ["小腹发烫"]


def test_stage_to_dict_carries_dialogue_draft():
    beat = BeatInput(beat_intent="拍甲", dialogue_draft="甲：你好。")
    stage = StageInput(chapter=1, stage=1, characters=["甲"], beats=[beat])
    d = rg._stage_to_dict(stage, 0)
    assert d["beats"][0]["dialogue_draft"] == "甲：你好。"


@pytest.mark.asyncio
async def test_emit_entry_state_broadcasts_initial_derivation_result():
    events = []

    async def emit(ev):
        events.append(ev)
    initial = {"甲": {"psychology": "稳", "posture": "站立", "clothing": "常服",
                     "action": "", "demeanor": ""}}
    await rg._emit_entry_state(emit, initial)
    entry = [e for e in events if e.get("entry")]
    assert len(entry) == 1 and entry[0]["index"] == -1
    names = {c["name"] for c in entry[0]["characters"]}
    assert names == {"甲"}


def test_state_row_has_five_fields():
    row = rg._state_row("甲", {
        "psychology": "稳", "posture": "站立", "clothing": "便装",
        "action": "叉腰", "demeanor": "平静",
    })
    assert row == {
        "name": "甲", "psychology": "稳", "posture": "站立",
        "clothing": "便装", "action": "叉腰", "demeanor": "平静",
    }


@pytest.mark.asyncio
async def test_derives_initial_state_once_then_derives_next_state_per_stage(monkeypatch):
    init_calls = []
    derive_calls = []

    async def fake_init(cards, stage_description, call_llm):
        init_calls.append(1)
        return {"甲": {"psychology": "初始"}}

    async def fake_derive(prior, text, call_llm):
        derive_calls.append(prior)
        return {"甲": {"psychology": f"推演自{prior.get('甲', {}).get('psychology', '')}"}}
    monkeypatch.setattr(rg, "derive_initial_states", fake_init)
    monkeypatch.setattr(rg, "derive_character_states", fake_derive)
    monkeypatch.setattr(rg, "render_character_card", lambda name, chapter, stage: f"角色：{name}")

    await rg.run_react_chapter_graph(_stages(2), FakeTurns(), _fake_llm)
    assert len(init_calls) == 1  # 只在开场调一次
    assert len(derive_calls) == 2  # 每个 stage 定稿后各调一次


def test_initial_state_no_longer_accepts_detail_skills():
    """system prompt 不再含卡片文本。"""
    state = rg._initial_state([], prose_style="")
    assert "卡片" not in str(state["messages"][0].content)


@pytest.mark.asyncio
async def test_review_gate_retries_then_passes(monkeypatch):
    """审核不通过 → 反馈进主笔线程 → 主笔重写 → 第二次通过 → 用第二版正文定稿。"""
    import engine.author_loop.dialogue_mode.react_graph as rgm
    from engine.author_loop.dialogue_mode.stage_review import ReviewResult

    calls = {"n": 0}
    prose_versions = {"v": 0}

    async def flaky_review(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return ReviewResult(passed=False, notes=["字数不够"])
        return ReviewResult(passed=True, notes=[])
    monkeypatch.setattr(rgm, "review_candidate", flaky_review)

    def prose_of(i, msgs):
        prose_versions["v"] += 1
        return f"[版本{prose_versions['v']}]"
    turns = FakeTurns(prose_of)
    out = await rg.run_react_chapter_graph(_stages(1), turns, _fake_llm)
    assert out == "[版本2]"
    assert turns.prose_calls == 2  # 重写了一次


@pytest.mark.asyncio
async def test_review_gate_gives_up_after_max_retries_and_alarms(monkeypatch):
    """连续不通过撞上重试上限 → 带病落账(用末次候选) + 报警,不阻塞章节完成。"""
    import engine.author_loop.dialogue_mode.react_graph as rgm
    from engine.author_loop.dialogue_mode.stage_review import ReviewResult

    async def always_fail(**kw):
        return ReviewResult(passed=False, notes=["还是不达标"])
    monkeypatch.setattr(rgm, "review_candidate", always_fail)

    alarms = []
    monkeypatch.setattr(rgm, "report_alarm", lambda *a, **k: alarms.append((a, k)))
    monkeypatch.setattr(rgm, "record_census", lambda *a, **k: None)

    turns = FakeTurns(lambda i, msgs: "[末次候选]")
    out = await rg.run_react_chapter_graph(_stages(1), turns, _fake_llm)
    assert out == "[末次候选]"
    assert turns.prose_calls == rgm.MAX_STAGE_REVIEW_RETRIES + 1  # 首次 + 4 次重试
    assert any(a[0][0] == "章节审核-带病落账" for a in alarms)


@pytest.mark.asyncio
async def test_review_gate_feedback_enters_author_thread(monkeypatch):
    """审核反馈要真的进主笔的 messages 线程(同线程内修订,不是开新对话)。"""
    import engine.author_loop.dialogue_mode.react_graph as rgm
    from engine.author_loop.dialogue_mode.stage_review import ReviewResult

    calls = {"n": 0}

    async def flaky_review(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return ReviewResult(passed=False, notes=["漏写了拍2的关键情节"])
        return ReviewResult(passed=True, notes=[])
    monkeypatch.setattr(rgm, "review_candidate", flaky_review)

    graph = rg.build_react_chapter_graph(FakeTurns(), _fake_llm)
    stages = [rg._stage_to_dict(s, i) for i, s in enumerate(_stages(1))]
    final = await graph.ainvoke(
        rg._initial_state(stages, prose_style=""),
        {"recursion_limit": 100, "configurable": {}},
    )
    joined = "\n".join(str(m.content) for m in final["messages"])
    assert "漏写了拍2的关键情节" in joined
    assert "审核未通过" in joined


@pytest.mark.asyncio
async def test_review_gate_skips_empty_prose():
    """空正文(stage 被跳过的情形)不该走审核——直接定稿(维持原有跳空拍不变量)。"""
    prose_of = lambda i, msgs: ""  # noqa: E731
    turns = FakeTurns(prose_of)
    out = await rg.run_react_chapter_graph(_stages(1), turns, _fake_llm)
    assert out == ""
    assert turns.prose_calls == 1  # 没有因为空正文触发重试


@pytest.mark.asyncio
async def test_task_packet_node_emits_recall_event(monkeypatch, tmp_path):
    import utils.paths as paths
    monkeypatch.setattr(paths, "lore_dir", lambda: str(tmp_path))

    async def fake_init(cards, stage_description, call_llm):
        return {"甲": {"psychology": "稳"}}

    async def fake_derive(prior, text, call_llm):
        return prior
    monkeypatch.setattr(rg, "derive_initial_states", fake_init)
    monkeypatch.setattr(rg, "derive_character_states", fake_derive)

    events = []

    async def emit(ev):
        events.append(ev)
    await rg.run_react_chapter_graph(_stages(1), FakeTurns(), _fake_llm, emit=emit)

    recall_events = [e for e in events if e["type"] == "author_loop_recall"]
    assert len(recall_events) == 1
    assert recall_events[0]["index"] == 0
    assert isinstance(recall_events[0]["recall_context"], str)


@pytest.mark.asyncio
async def test_task_packet_node_does_not_block_event_loop(monkeypatch, tmp_path):
    """recall_relevant_context runs a CPU-bound embedding query; the task_packet node must
    offload it to a thread (asyncio.to_thread) rather than run it inline, or every other
    coroutine on the process -- including the HTTP requests behind a frontend page
    navigation -- stalls for as long as the embedding takes."""
    import asyncio
    import time

    import utils.paths as paths
    monkeypatch.setattr(paths, "lore_dir", lambda: str(tmp_path))

    async def fake_init(cards, stage_description, call_llm):
        return {"甲": {"psychology": "稳"}}

    async def fake_derive(prior, text, call_llm):
        return prior
    monkeypatch.setattr(rg, "derive_initial_states", fake_init)
    monkeypatch.setattr(rg, "derive_character_states", fake_derive)

    import engine.memory_recall.recall as recall_mod

    def slow_recall(*a, **k):
        time.sleep(0.2)
        return "", {}, []
    monkeypatch.setattr(recall_mod, "recall_relevant_context", slow_recall)

    tick_count = 0

    async def ticker():
        nonlocal tick_count
        while True:
            await asyncio.sleep(0.02)
            tick_count += 1

    ticker_task = asyncio.create_task(ticker())
    try:
        await rg.run_react_chapter_graph(_stages(1), FakeTurns(), _fake_llm)
    finally:
        ticker_task.cancel()

    assert tick_count >= 5


@pytest.mark.asyncio
async def test_task_packet_node_passes_recall_prefs_to_recall(monkeypatch, tmp_path):
    """_task_packet_node must read recall_cooldown_turns/recall_top_k from dialogue prefs
    and pass them through to recall_relevant_context as cooldown_turns/max_items."""
    import utils.paths as paths
    monkeypatch.setattr(paths, "lore_dir", lambda: str(tmp_path))

    captured_kwargs: dict = {}

    def fake_recall(*a, **k):
        captured_kwargs.update(k)
        return "", {}, []

    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"recall_cooldown_turns": 20, "recall_top_k": 8},
    )

    import engine.memory_recall.recall as recall_mod
    monkeypatch.setattr(recall_mod, "recall_relevant_context", fake_recall)

    async def fake_init(cards, stage_description, call_llm):
        return {"甲": {"psychology": "稳"}}

    async def fake_derive(prior, text, call_llm):
        return prior
    monkeypatch.setattr(rg, "derive_initial_states", fake_init)
    monkeypatch.setattr(rg, "derive_character_states", fake_derive)

    await rg.run_react_chapter_graph(_stages(1), FakeTurns(), _fake_llm)

    assert captured_kwargs.get("max_items") == 8
    assert captured_kwargs.get("cooldown_turns") == 20


@pytest.mark.asyncio
async def test_finalize_stage_archives_event_log_entry(monkeypatch, tmp_path):
    import utils.paths as paths
    monkeypatch.setattr(paths, "lore_dir", lambda: str(tmp_path))

    async def fake_call_llm(system, user, *a, **k):
        if k.get("_log_agent") == "state_derive":
            return "{}", 0, 0
        return (
            '{"events": [{"event": "阿明推开门", "time": "深夜",'
            ' "location": "书房", "characters": ["甲"], "entities": ["甲"]}]}',
            0, 0,
        )

    stage = {"chapter": 3, "stage": 2, "characters": ["甲"], "beats": []}
    await rg._finalize_stage(
        config={"configurable": {}}, i=1, stage=stage, prose="甲推开门，屋里漆黑一片。",
        chapter=3, stage_num=2, character_states={}, call_llm=fake_call_llm,
    )

    from engine.memory_recall.event_log import load_event_log
    entries = load_event_log().get("entries") or []
    assert len(entries) == 1
    assert entries[0]["chapter"] == 3
    assert entries[0]["summary"] == "阿明推开门"
    assert entries[0]["characters"] == ["甲"]
    assert entries[0]["origin"] == "author_loop"


@pytest.mark.asyncio
async def test_finalize_stage_archives_multiple_event_log_entries(monkeypatch, tmp_path):
    import utils.paths as paths
    monkeypatch.setattr(paths, "lore_dir", lambda: str(tmp_path))

    async def fake_call_llm(system, user, *a, **k):
        if k.get("_log_agent") == "state_derive":
            return "{}", 0, 0
        return (
            '{"events": ['
            '{"event": "甲推开门", "time": "深夜", "location": "书房", "characters": ["甲"], "entities": ["甲"]},'
            '{"event": "乙想起童年", "time": "十年前", "location": "", "characters": ["乙"], "entities": ["乙"]}'
            ']}',
            0, 0,
        )

    emitted: list[dict] = []

    async def emit(ev):
        emitted.append(ev)

    stage = {"chapter": 3, "stage": 2, "characters": ["甲", "乙"], "beats": []}
    await rg._finalize_stage(
        config={"configurable": {"emit": emit}}, i=1, stage=stage,
        prose="甲推开门。乙忽然想起童年。",
        chapter=3, stage_num=2, character_states={}, call_llm=fake_call_llm,
    )

    from engine.memory_recall.event_log import load_event_log
    entries = load_event_log().get("entries") or []
    assert len(entries) == 2
    assert [e["summary"] for e in entries] == ["甲推开门", "乙想起童年"]
    ev = next(e for e in emitted if e["type"] == "author_loop_event_log")
    assert len(ev["entries"]) == 2


@pytest.mark.asyncio
async def test_derive_calls_are_tagged_with_state_derive_agent(monkeypatch):
    """Single stage → derive_initial_states once + derive_character_states once, both tagged
    state_derive; _finalize_stage's own memory-recall archival fold (see
    test_finalize_stage_archives_event_log_entry) also rides call_llm but is tagged
    memory_recall, not state_derive -- this test only asserts about the two derive calls."""
    captured_kwargs = []

    async def spy_call_llm(s, u, *a, **k):
        captured_kwargs.append(k)
        return ("PASS", 0, 0)

    async def fake_init(cards, stage_description, call_llm):
        await call_llm("sys", "user")
        return {"甲": {"psychology": "稳"}}

    async def fake_derive(prior, text, call_llm):
        await call_llm("sys", "user")
        return prior

    monkeypatch.setattr(rg, "derive_initial_states", fake_init)
    monkeypatch.setattr(rg, "derive_character_states", fake_derive)

    await rg.run_react_chapter_graph(_stages(1), FakeTurns(), spy_call_llm)

    agents = [k.get("_log_agent") for k in captured_kwargs]
    assert agents.count("state_derive") == 2  # init once + derive once
    assert agents.count("memory_recall") == 1  # _archive_stage_event's own extract call
