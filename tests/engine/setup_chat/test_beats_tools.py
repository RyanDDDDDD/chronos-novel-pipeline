"""beats 写/读/拍级 patch/失效 与声线查询工具的行为测试。"""
import engine.setup_chat.skeleton_writer as sw
import engine.setup_chat.tools as t
import pytest

from repo_test_helpers import seed_plot


@pytest.fixture(autouse=True)
def _suppress_background_review(monkeypatch):
    """write_chapter_skeleton marks review-pending on chapter completion; these beat/patch
    tests seed or patch in the same session -- suppress that gate unless explicitly tested."""
    import engine.setup_chat.skeleton_pipeline as sp
    sp._ACTIVE_REVIEWS.clear()
    monkeypatch.setattr(sp, "mark_review_active", lambda novel_id, chapter: None)
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_background_review.schedule_chapter_review_fix",
        lambda chapter: None,
    )
    yield
    sp._ACTIVE_REVIEWS.clear()


def _patch_plot(plot):
    seed_plot(plot)


def _plot_raw():
    import repositories as repo

    return repo.get_plot_repo().list_raw()


def _stub_writer(monkeypatch, beats):
    """Stub skeleton_writer.generate_stage_beats to return fixed beats regardless of which
    stage/overview it's called with -- these tests only need deterministic seed text, not
    real generation behavior (that's covered by test_skeleton_writer.py)."""
    async def fake(chapter, stage_num, *, overview, is_revision):
        return beats
    monkeypatch.setattr(sw, "generate_stage_beats", fake)


_BEATS = [
    {"text": "拍零：两人对峙。"},
    {"text": "拍一：丙推门而入，喊道：「我来了。」"},
]

_PLOT_WITH_BEATS = [{"chapter": 1, "title": "一", "stages": [
    {"stage_num": 1, "title": "对峙", "location": "庭院", "description": "甲乙对峙",
     "characters": {"甲": {}}, "beats": _BEATS},
    {"stage_num": 2, "title": "登场", "location": "门厅", "description": "丙登场",
     "characters": {"丙": {}}},
]}]


@pytest.mark.asyncio
async def test_write_chapter_skeleton_writes_beats_and_drops_legacy(monkeypatch, tmp_path):
    plot = [{"chapter": 1, "title": "一", "stages": [
        {"stage_num": 1, "description": "甲乙对峙", "characters": {"甲": {}}, "skeleton": "旧底稿"},
    ]}]
    _patch_plot(plot)
    _stub_writer(monkeypatch, [
        {"text": "拍零", "sensation_notes": []}, {"text": "拍一", "sensation_notes": []},
    ])
    out = await t.write_chapter_skeleton.ainvoke({
        "chapter": 1, "stages": [{"stage_num": 1, "overview": ""}],
    })
    assert "已生成" in out or "已写入" in out
    st = _plot_raw()[0]["stages"][0]
    assert [b["text"] for b in st["beats"]] == ["拍零", "拍一"]
    assert "skeleton" not in st


@pytest.mark.asyncio
async def test_patch_chapter_replace_beat(monkeypatch, tmp_path):
    _patch_plot(_PLOT_WITH_BEATS)
    monkeypatch.setattr(t, "_clear_archives_from", lambda ch: "")
    monkeypatch.setattr(
        "engine.setup_chat.tool_args.load_plot_grounding",
        lambda: {"character_names": ["甲", "乙", "丙"]},
    )
    out = await t.patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "replace_beat", "stage_num": 1, "beat_idx": 1,
         "beat": {"text": "拍一：丙夺门而入，怒喝：「都给我住手！」"}},
    ]})
    assert "已局部更新" in out
    st = _plot_raw()[0]["stages"][0]
    assert st["beats"][1]["text"] == "拍一：丙夺门而入，怒喝：「都给我住手！」"
    assert st["beats"][0]["text"] == "拍零：两人对峙。"  # 其它拍不动


@pytest.mark.asyncio
async def test_patch_chapter_replace_beat_out_of_range(monkeypatch, tmp_path):
    _patch_plot(_PLOT_WITH_BEATS)
    before = _plot_raw()
    out = await t.patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "replace_beat", "stage_num": 1, "beat_idx": 9, "beat": {"text": "x"}},
    ]})
    assert "9" in out and "拍" in out
    assert _plot_raw() == before  # 未写盘


@pytest.mark.asyncio
async def test_patch_chapter_replace_beat_on_unexpanded_stage(monkeypatch, tmp_path):
    _patch_plot( _PLOT_WITH_BEATS)
    out = await t.patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "replace_beat", "stage_num": 2, "beat_idx": 0, "beat": {"text": "x"}},
    ]})
    assert "尚未分拍" in out


@pytest.mark.asyncio
async def test_patch_chapter_description_change_clears_beats(monkeypatch, tmp_path):
    _patch_plot(_PLOT_WITH_BEATS)
    monkeypatch.setattr(t, "_clear_archives_from", lambda ch: "")
    monkeypatch.setattr(
        "engine.setup_chat.tool_args.load_plot_grounding",
        lambda: {"character_names": ["甲", "乙", "丙"]},
    )
    out = await t.patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "replace", "stage_num": 1, "fields": {"description": "改成新走向"}},
    ]})
    assert "失效" in out
    st = _plot_raw()[0]["stages"][0]
    assert "beats" not in st


@pytest.mark.asyncio
async def test_patch_chapter_add_op_schedules_cascade_even_without_cleared_beats(monkeypatch, tmp_path):
    """add/remove/replace_beat ops never populate `cleared` (only a description-driven beats
    wipe does), so they never used to trigger _clear_archives_from's schedule_timeline_cascade
    call -- yet `add` can still introduce a brand-new character into the chapter's roster.
    schedule_timeline_cascade must now fire unconditionally after every successful patch_chapter
    write so a newly-added character's archive still gets auto-built in the background."""
    _patch_plot( _PLOT_WITH_BEATS)
    monkeypatch.setattr(
        "engine.setup_chat.tool_args.load_plot_grounding",
        lambda: {"character_names": ["甲", "乙", "丙", "丁"]},
    )
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: [n for n in ("甲", "乙", "丙", "丁") if n in text],
    )
    calls: list[tuple[int, list[str] | None]] = []
    monkeypatch.setattr(
        "engine.setup_chat.timeline_auto.schedule_timeline_cascade",
        lambda min_chapter, names=None: calls.append((min_chapter, names)),
    )
    out = await t.patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "add", "after_stage_num": 2,
         "stage": {"title": "新段", "location": "门外", "description": "丁登场了。"}},
    ]})
    assert "已局部更新" in out
    assert calls == [(1, ["甲", "乙", "丙", "丁"])]


@pytest.mark.asyncio
async def test_patch_chapter_records_invalidation_tasks(monkeypatch, tmp_path):
    import engine.setup_chat.plan_runner as pr_mod
    pr_mod._PENDING_REPAIR.clear()
    _patch_plot( _PLOT_WITH_BEATS)
    monkeypatch.setattr(t, "_clear_archives_from", lambda ch: "")
    monkeypatch.setattr(
        "engine.setup_chat.tool_args.load_plot_grounding",
        lambda: {"character_names": ["甲", "乙", "丙"]},
    )
    out = await t.patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "replace", "stage_num": 1, "fields": {"description": "改后的对峙"}},
    ]})
    assert "已局部更新" in out
    assert "重扩第1章 stage1 骨架" in out
    assert pr_mod.pending_invalidation_note() == ""


@pytest.mark.asyncio
async def test_read_chapter_skeleton_renders_beats(monkeypatch, tmp_path):
    _patch_plot( _PLOT_WITH_BEATS)
    out = await t.read_chapter_skeleton.ainvoke({"chapter": 1})
    assert "【拍0】拍零：两人对峙。" in out
    assert "【拍1】拍一：丙推门而入，喊道：「我来了。」" in out
    assert "（待扩写）" in out  # stage2 无 beats


@pytest.mark.asyncio
async def test_query_character_voice_no_card(monkeypatch):
    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.resolve_card_state",
        lambda name, ch, sg: {},
    )
    out = await t.query_character_voice.ainvoke({
        "character": "乙", "chapter": 1, "stage_num": 1,
    })
    assert "无档案" in out


@pytest.mark.asyncio
async def test_query_character_voice_returns_persona_grounding(monkeypatch):
    monkeypatch.setattr(
        "engine.author_loop.dialogue_mode.chapter_state.resolve_card_state",
        lambda name, ch, sg: {
            "personality": "怯懦顺从", "verbal_tic": "句尾带『那个…』",
            "self_ref": {"_default": ["我"]},
        },
    )
    out = await t.query_character_voice.ainvoke({
        "character": "甲", "chapter": 1, "stage_num": 2,
    })
    assert "人格" in out and "怯懦顺从" in out
    assert "口癖" in out and "那个" in out
    assert "自称池：我" in out
    assert "语料" not in out  # 语料检索机制已删，输出不再提语料


@pytest.mark.asyncio
async def test_write_chapter_skeleton_writes_sensation_notes(monkeypatch, tmp_path):
    plot = [{"chapter": 1, "title": "一", "stages": [
        {"stage_num": 1, "description": "甲乙对峙", "characters": {"甲": {}}},
    ]}]
    _patch_plot( plot)
    _stub_writer(monkeypatch, [{"text": "拍零", "sensation_notes": ["小腹一阵酥麻"]}])
    out = await t.write_chapter_skeleton.ainvoke({
        "chapter": 1, "stages": [{"stage_num": 1, "overview": ""}],
    })
    assert "已生成" in out or "已写入" in out
    rendered = t.read_chapter_skeleton.invoke({"chapter": 1})
    assert "体感参考" in rendered and "小腹一阵酥麻" in rendered


@pytest.mark.asyncio
async def test_write_chapter_skeleton_sensation_notes_defaults_empty(monkeypatch, tmp_path):
    plot = [{"chapter": 1, "title": "一", "stages": [
        {"stage_num": 1, "description": "甲登场", "characters": {"甲": {}}},
    ]}]
    _patch_plot( plot)
    _stub_writer(monkeypatch, [{"text": "拍零", "sensation_notes": []}])
    await t.write_chapter_skeleton.ainvoke({
        "chapter": 1, "stages": [{"stage_num": 1, "overview": ""}],
    })
    rendered = t.read_chapter_skeleton.invoke({"chapter": 1})
    assert "体感参考" not in rendered


@pytest.mark.asyncio
async def test_patch_chapter_set_beat_dialogue(monkeypatch, tmp_path):
    _patch_plot(_PLOT_WITH_BEATS)
    monkeypatch.setattr(t, "_clear_archives_from", lambda ch: "")
    monkeypatch.setattr(
        "engine.setup_chat.tool_args.load_plot_grounding",
        lambda: {"character_names": ["甲", "乙", "丙"]},
    )
    out = await t.patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "set_beat_dialogue", "stage_num": 1, "beat_idx": 0,
         "dialogue_draft": "甲（意图：试探）：你在做什么。"},
    ]})
    assert "已局部更新" in out
    st = _plot_raw()[0]["stages"][0]
    assert st["beats"][0]["dialogue_draft"] == "甲（意图：试探）：你在做什么。"
    assert st["beats"][0]["text"] == "拍零：两人对峙。"  # 只改台词草稿，正文不动
    assert st["beats"][1].get("dialogue_draft") is None  # 其它拍不受影响


@pytest.mark.asyncio
async def test_patch_chapter_set_beat_dialogue_does_not_trigger_review(monkeypatch, tmp_path):
    """跟 replace_beat 不同：改台词草稿是独立字段的编辑，不该触发过渡/保真审查。"""
    _patch_plot( _PLOT_WITH_BEATS)
    monkeypatch.setattr(
        "engine.setup_chat.tool_args.load_plot_grounding",
        lambda: {"character_names": ["甲", "乙", "丙"]},
    )

    async def fail_if_called(stages, sn):
        raise AssertionError("set_beat_dialogue 不应触发 run_stage_local_review")
    monkeypatch.setattr(
        "engine.setup_chat.chapter_review.run_stage_local_review", fail_if_called,
    )
    out = await t.patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "set_beat_dialogue", "stage_num": 1, "beat_idx": 0, "dialogue_draft": "台词"},
    ]})
    assert "已局部更新" in out


@pytest.mark.asyncio
async def test_patch_chapter_set_beat_dialogue_out_of_range(monkeypatch, tmp_path):
    _patch_plot(_PLOT_WITH_BEATS)
    before = _plot_raw()
    out = await t.patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "set_beat_dialogue", "stage_num": 1, "beat_idx": 9, "dialogue_draft": "x"},
    ]})
    assert "9" in out and "拍" in out
    assert _plot_raw() == before  # 未写盘


@pytest.mark.asyncio
async def test_patch_chapter_set_beat_dialogue_on_unexpanded_stage(monkeypatch, tmp_path):
    _patch_plot( _PLOT_WITH_BEATS)
    out = await t.patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "set_beat_dialogue", "stage_num": 2, "beat_idx": 0, "dialogue_draft": "x"},
    ]})
    assert "尚未分拍" in out


@pytest.mark.asyncio
async def test_write_chapter_skeleton_fills_dialogue_draft_per_beat(monkeypatch, tmp_path):
    plot = [{"chapter": 1, "title": "一", "stages": [
        {"stage_num": 1, "description": "甲乙对峙", "characters": {"甲": {}}},
    ]}]
    _patch_plot(plot)
    _stub_writer(monkeypatch, [
        {"text": "拍零", "sensation_notes": []}, {"text": "拍一", "sensation_notes": []},
    ])

    async def fake_draft(chapter, stage_num, beat_text, characters, prev_text):
        return f"{beat_text}的台词草稿"
    monkeypatch.setattr("engine.setup_chat.dialogue_draft.draft_beat_dialogue", fake_draft)

    await t.write_chapter_skeleton.ainvoke({
        "chapter": 1, "stages": [{"stage_num": 1, "overview": ""}],
    })
    st = _plot_raw()[0]["stages"][0]
    assert st["beats"][0]["dialogue_draft"] == "拍零的台词草稿"
    assert st["beats"][1]["dialogue_draft"] == "拍一的台词草稿"


@pytest.mark.asyncio
async def test_write_chapter_skeleton_dialogue_draft_gets_previous_beat_as_context(
    monkeypatch, tmp_path,
):
    plot = [{"chapter": 1, "title": "一", "stages": [
        {"stage_num": 1, "description": "甲乙对峙", "characters": {"甲": {}}},
    ]}]
    _patch_plot( plot)
    _stub_writer(monkeypatch, [
        {"text": "拍零", "sensation_notes": []}, {"text": "拍一", "sensation_notes": []},
    ])
    captured = []

    async def fake_draft(chapter, stage_num, beat_text, characters, prev_text):
        captured.append((beat_text, prev_text))
        return ""
    monkeypatch.setattr("engine.setup_chat.dialogue_draft.draft_beat_dialogue", fake_draft)

    await t.write_chapter_skeleton.ainvoke({
        "chapter": 1, "stages": [{"stage_num": 1, "overview": ""}],
    })
    by_beat_text = dict(captured)
    assert by_beat_text["拍零"] == ""  # 本段首拍，没有更早的段 → 无最近上下文
    assert by_beat_text["拍一"] == "拍零"  # 同段上一拍


@pytest.mark.asyncio
async def test_write_chapter_skeleton_dialogue_draft_crosses_stage_boundary(monkeypatch, tmp_path):
    plot = [{"chapter": 1, "title": "一", "stages": [
        {"stage_num": 1, "description": "甲乙对峙", "characters": {"甲": {}},
         "beats": [{"text": "上一段最后一拍", "sensation_notes": []}]},
        {"stage_num": 2, "description": "丙登场", "characters": {"丙": {}}},
    ]}]
    _patch_plot( plot)
    _stub_writer(monkeypatch, [{"text": "新段首拍", "sensation_notes": []}])
    captured = []

    async def fake_draft(chapter, stage_num, beat_text, characters, prev_text):
        captured.append((stage_num, beat_text, prev_text))
        return ""
    monkeypatch.setattr("engine.setup_chat.dialogue_draft.draft_beat_dialogue", fake_draft)

    await t.write_chapter_skeleton.ainvoke({
        "chapter": 1, "stages": [{"stage_num": 2, "overview": ""}],
    })
    assert captured == [(2, "新段首拍", "上一段最后一拍")]


@pytest.mark.asyncio
async def test_write_chapter_skeleton_dialogue_draft_skips_stage_with_no_characters(
    monkeypatch, tmp_path,
):
    plot = [{"chapter": 1, "title": "一", "stages": [
        {"stage_num": 1, "description": "空场"},
    ]}]
    _patch_plot( plot)
    _stub_writer(monkeypatch, [{"text": "拍零", "sensation_notes": []}])
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: [],
    )

    async def fake_draft(chapter, stage_num, beat_text, characters, prev_text):
        assert characters == []
        return ""
    monkeypatch.setattr("engine.setup_chat.dialogue_draft.draft_beat_dialogue", fake_draft)

    out = await t.write_chapter_skeleton.ainvoke({
        "chapter": 1, "stages": [{"stage_num": 1, "overview": ""}],
    })
    assert "已生成" in out or "已写入" in out


@pytest.mark.asyncio
async def test_write_chapter_skeleton_dialogue_draft_derives_characters_from_description(
    monkeypatch, tmp_path,
):
    """After plot stage `characters` field removal, roster must come from scan_characters(description)."""
    plot = [{"chapter": 1, "title": "一", "stages": [
        {"stage_num": 1, "description": "甲乙对峙"},
    ]}]
    _patch_plot(plot)
    _stub_writer(monkeypatch, [{"text": "拍零", "sensation_notes": []}])
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: ["甲", "乙"] if "甲乙" in text else [],
    )

    async def fake_draft(chapter, stage_num, beat_text, characters, prev_text):
        assert characters == ["甲", "乙"]
        return "甲：你好。"
    monkeypatch.setattr("engine.setup_chat.dialogue_draft.draft_beat_dialogue", fake_draft)

    await t.write_chapter_skeleton.ainvoke({
        "chapter": 1, "stages": [{"stage_num": 1, "overview": ""}],
    })
    st = _plot_raw()[0]["stages"][0]
    assert st["beats"][0]["dialogue_draft"] == "甲：你好。"
