import engine.setup_chat.skeleton_writer as sw
import pytest

from repo_test_helpers import init_store, save_archive, seed_plot
from engine.setup_chat.tools import (
    generate_one_chapter,
    patch_chapter,
    write_chapter_skeleton,
)


@pytest.fixture(autouse=True)
def _suppress_background_review(monkeypatch):
    """write_chapter_skeleton now marks review-active on chapter completion; these
    patch-focused tests seed beats then patch in the same turn -- suppress that gate."""
    import engine.setup_chat.skeleton_pipeline as sp
    sp._ACTIVE_REVIEWS.clear()
    monkeypatch.setattr(sp, "mark_review_active", lambda novel_id, chapter: None)
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_background_review.schedule_chapter_review_fix",
        lambda chapter: None,
    )
    yield
    sp._ACTIVE_REVIEWS.clear()


def _stage(title="场景一"):
    return {"title": title, "location": "祭坛", "description": "事件"}


def _patch_plot(monkeypatch, tmp_path):
    """Initialize sqlite plot repo for plot-tool tests (archives live in SQLite, not filesystem)."""
    del tmp_path
    init_store()
    monkeypatch.setattr(
        "engine.setup_chat.tool_args.load_plot_grounding",
        lambda: {"character_names": ["甲"], "archetypes": ["天真烂漫型"]},
    )


def _plot_raw():
    import repositories as repo

    return repo.get_plot_repo().list_raw()


def _isolate_timeline(tmp_path, monkeypatch):
    novel_id = "test-novel"
    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", novel_id)
    (tmp_path / novel_id).mkdir(parents=True, exist_ok=True)
    import repositories

    repositories.init_repositories(novel_id)


def _patch_built_chapters(monkeypatch, built: dict[int, list[str]]) -> None:
    monkeypatch.setattr("engine.archive.archive_view._built_chapters", lambda: built)


def _stub_writer(monkeypatch, beats_by_stage):
    """Stub skeleton_writer.generate_stage_beats so write_chapter_skeleton seeding calls in
    these patch_chapter-focused tests get deterministic beat text without real generation."""
    async def fake(chapter, stage_num, *, overview, is_revision):
        return beats_by_stage[stage_num]
    monkeypatch.setattr(sw, "generate_stage_beats", fake)


def _seed_archive(tmp_path, chapter: int, name: str) -> None:
    """Seed a persisted archive row in SQLite for cascade/clear assertions."""
    del tmp_path
    save_archive(name, chapter, {"name": name, "stages": {}})


@pytest.mark.asyncio
async def test_generate_appends_without_wiping_prior(monkeypatch, tmp_path):
    _patch_plot(monkeypatch, tmp_path)
    await generate_one_chapter.ainvoke(
        {"chapter_index": 1, "title": "第一章", "core_xp": ["开端"], "stages": [_stage("一")]})
    out = await generate_one_chapter.ainvoke(
        {"chapter_index": 2, "title": "第二章", "core_xp": ["承"], "stages": [_stage("二")]})
    data = _plot_raw()
    assert [c["chapter"] for c in data] == [1, 2]          #Both chapters are there, but Chapter 1 has not been cleared.
    assert data[0]["title"] == "第一章" and data[1]["title"] == "第二章"
    assert "追加" in out


@pytest.mark.asyncio
async def test_generate_one_chapter_replace_cancels_active_review_before_proceeding(
    monkeypatch, tmp_path,
):
    _patch_plot(monkeypatch, tmp_path)
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")

    cancel_calls: list[tuple[str, int, bool]] = []

    async def fake_cancel(novel_id, chapter, *, restarting=True):
        cancel_calls.append((novel_id, chapter, restarting))

    monkeypatch.setattr(
        "engine.setup_chat.skeleton_background_review.cancel_active_review", fake_cancel,
    )

    await generate_one_chapter.ainvoke(
        {"chapter_index": 1, "title": "旧", "core_xp": ["基调"], "stages": [_stage()]},
    )
    cancel_calls.clear()

    out = await generate_one_chapter.ainvoke(
        {"chapter_index": 1, "title": "新", "core_xp": ["基调"], "stages": [_stage("新场景")]},
    )

    assert cancel_calls == [("n", 1, False)]
    assert "更新" in out
    data = _plot_raw()
    assert data[0]["title"] == "新"


@pytest.mark.asyncio
async def test_generate_one_chapter_append_does_not_cancel_review(monkeypatch, tmp_path):
    _patch_plot(monkeypatch, tmp_path)
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")

    cancel_calls: list[tuple[str, int]] = []

    async def fake_cancel(novel_id, chapter, *, restarting=True):
        cancel_calls.append((novel_id, chapter))

    monkeypatch.setattr(
        "engine.setup_chat.skeleton_background_review.cancel_active_review", fake_cancel,
    )

    await generate_one_chapter.ainvoke(
        {"chapter_index": 1, "title": "一", "core_xp": ["基调"], "stages": [_stage()]},
    )
    cancel_calls.clear()

    await generate_one_chapter.ainvoke(
        {"chapter_index": 2, "title": "二", "core_xp": ["基调"], "stages": [_stage("二")]},
    )

    assert cancel_calls == []


@pytest.mark.asyncio
async def test_generate_replaces_existing_chapter(monkeypatch, tmp_path):
    _patch_plot(monkeypatch, tmp_path)
    await generate_one_chapter.ainvoke(
        {"chapter_index": 1, "title": "旧", "core_xp": ["基调"], "stages": [_stage()]})
    await generate_one_chapter.ainvoke(
        {"chapter_index": 2, "title": "第二章", "core_xp": ["基调"], "stages": [_stage()]})
    out = await generate_one_chapter.ainvoke(
        {"chapter_index": 1, "title": "新", "core_xp": ["基调"], "stages": [_stage()]})
    data = _plot_raw()
    assert len(data) == 2 and data[0]["title"] == "新" and data[1]["title"] == "第二章"
    assert "更新" in out


@pytest.mark.asyncio
async def test_generate_one_chapter_rejects_understaffed_chapter(monkeypatch, tmp_path):
    _patch_plot(monkeypatch, tmp_path)
    import engine.modes.author_loop_skill_prefs as prefs_mod
    monkeypatch.setattr(
        prefs_mod, "load_dialogue_prefs",
        lambda: {"detail_skills": [], "target_words": 3500},
    )
    out = await generate_one_chapter.ainvoke(
        {"chapter_index": 1, "title": "一", "core_xp": ["基调"], "stages": [_stage()]})
    assert "校验未通过，未写入" in out
    assert "仅 1 段" in out and "至少需要 2 段" in out
    assert _plot_raw() == []  # rejected before any write


@pytest.mark.asyncio
async def test_generate_one_chapter_appends_remaining_note_when_understaffed(monkeypatch, tmp_path):
    _patch_plot(monkeypatch, tmp_path)
    import engine.modes.author_loop_skill_prefs as prefs_mod
    monkeypatch.setattr(
        #target_words=1750 → suggested_min_stage_count=1，1 段即可通过硬门槛，不干扰本测试焦点
        prefs_mod, "load_dialogue_prefs", lambda: {"target_words": 1750, "auto_build_chapter_count": 5},
    )
    out = await generate_one_chapter.ainvoke(
        {"chapter_index": 1, "title": "一", "core_xp": ["基调"], "stages": [_stage()]})
    assert "已建 1/5 章，剩余 4 章待创建" in out


@pytest.mark.asyncio
async def test_generate_one_chapter_no_remaining_note_on_replace(monkeypatch, tmp_path):
    """替换既有章（非新增）不应提示剩余章数，即使总章数仍低于目标。"""
    _patch_plot(monkeypatch, tmp_path)
    import engine.modes.author_loop_skill_prefs as prefs_mod
    monkeypatch.setattr(
        prefs_mod, "load_dialogue_prefs", lambda: {"target_words": 1750, "auto_build_chapter_count": 5},
    )
    await generate_one_chapter.ainvoke(
        {"chapter_index": 1, "title": "一", "core_xp": ["基调"], "stages": [_stage()]})
    out = await generate_one_chapter.ainvoke(
        {"chapter_index": 1, "title": "一改", "core_xp": ["基调"], "stages": [_stage()]})
    assert "待创建" not in out


@pytest.mark.asyncio
async def test_generate_one_chapter_no_remaining_note_when_target_met(monkeypatch, tmp_path):
    _patch_plot(monkeypatch, tmp_path)
    import engine.modes.author_loop_skill_prefs as prefs_mod
    monkeypatch.setattr(
        prefs_mod, "load_dialogue_prefs", lambda: {"target_words": 1750, "auto_build_chapter_count": 1},
    )
    out = await generate_one_chapter.ainvoke(
        {"chapter_index": 1, "title": "一", "core_xp": ["基调"], "stages": [_stage()]})
    assert "待创建" not in out


@pytest.mark.asyncio
async def test_generate_rejects_gap(monkeypatch, tmp_path):
    _patch_plot(monkeypatch, tmp_path)
    out = await generate_one_chapter.ainvoke(
        {"chapter_index": 3, "title": "x", "core_xp": ["基调"], "stages": [_stage()]})
    assert "无法写入" in out
    assert _plot_raw() == []  #No disk written


def test_suggested_min_stage_count_examples():
    from engine.setup.plot.validator import suggested_min_stage_count
    assert suggested_min_stage_count(3000) == 2   # 3000/350 -> 9 beats -> ceil(9/5) = 2
    assert suggested_min_stage_count(1750) == 1   # 1750/350 -> 5 beats -> ceil(5/5) = 1
    assert suggested_min_stage_count(3500) == 2   # 3500/350 -> 10 beats -> ceil(10/5) = 2


@pytest.mark.asyncio
async def test_regenerate_chapter_clears_skeleton(monkeypatch, tmp_path):
    """
Rewrite an existing chapter → The chapter skeleton is cleared and a prompt for reconstruction is returned."""
    from engine.setup_chat.tools import write_chapter_skeleton
    _patch_plot(monkeypatch, tmp_path)
    await generate_one_chapter.ainvoke(
        {"chapter_index": 1, "title": "旧", "core_xp": ["基调"], "stages": [_stage()]})
    #Expand beats
    _stub_writer(monkeypatch, {1: [{"text": "已扩写的底稿", "sensation_notes": []}]})
    await write_chapter_skeleton.ainvoke(
        {"chapter": 1, "stages": [{"stage_num": 1, "overview": ""}]})
    assert _plot_raw()[0]["stages"][0]["beats"][0]["text"] == "已扩写的底稿"
    #Rewrite chapter → beats should be cleared
    out = await generate_one_chapter.ainvoke(
        {"chapter_index": 1, "title": "新", "core_xp": ["基调"], "stages": [_stage()]})
    st = _plot_raw()[0]["stages"][0]
    assert "beats" not in st
    assert "重置" in out and "write_chapter_skeleton" in out


@pytest.mark.asyncio
async def test_regenerate_chapter_clears_downstream_archives(monkeypatch, tmp_path):
    """整章替换无法逐段 diff description，无条件清该章及以后已构建的 archive/timeline。"""
    _isolate_timeline(tmp_path, monkeypatch)
    _patch_plot(monkeypatch, tmp_path)
    await generate_one_chapter.ainvoke(
        {"chapter_index": 1, "title": "旧", "core_xp": ["基调"], "stages": [_stage()]})
    _patch_built_chapters(monkeypatch, {1: ["甲"]})
    _seed_archive(tmp_path, 1, "甲")
    from context import character_timeline as ct
    ct.append_stage("甲", 1, 1, {})

    out = await generate_one_chapter.ainvoke(
        {"chapter_index": 1, "title": "新", "core_xp": ["基调"], "stages": [_stage()]})

    assert [s["chapter"] for s in ct.load_timeline("甲")["snapshots"]] == []
    assert "角色档案已清空" in out and "write_character_archive" in out
    assert len(_plot_raw()) == 1  #plot 本身仍照常写入

@pytest.mark.asyncio
async def test_generate_append_new_chapter_keeps_archives(monkeypatch, tmp_path):
    """追加新章（非替换）没有已构建 archive 可清，note 应为空。"""
    _patch_plot(monkeypatch, tmp_path)
    out = await generate_one_chapter.ainvoke(
        {"chapter_index": 1, "title": "一", "core_xp": ["基调"], "stages": [_stage()]})
    assert "角色档案已清空" not in out


async def _seed_chapter(titles):
    """
Create a chapter containing several stages (divided by titles) for patch testing."""
    await generate_one_chapter.ainvoke({
        "chapter_index": 1, "title": "一", "core_xp": ["基调"],
        "stages": [_stage(t) for t in titles]})


@pytest.mark.asyncio
async def test_patch_replace_touches_only_target_stage_and_field(monkeypatch, tmp_path):
    """replace only changes the specified fields of the specified segment, leaving other segments and unspecified fields unchanged."""
    _patch_plot(monkeypatch, tmp_path)
    await _seed_chapter(["段一", "段二"])
    await patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "replace", "stage_num": 2, "fields": {"description": "改后的事件"}}]})
    stages = _plot_raw()[0]["stages"]
    assert stages[0]["description"] == "事件"        #Duan Yi did not move
    assert stages[1]["description"] == "改后的事件"   #Paragraph 2 has been changed
    assert stages[1]["title"] == "段二"              #Not reserved for fields
    assert [s["stage_num"] for s in stages] == [1, 2]


@pytest.mark.asyncio
async def test_patch_replace_description_clears_that_stage_skeleton(monkeypatch, tmp_path):
    """
Change the description of a certain segment → Only the skeleton of this segment becomes invalid, and the skeleton of the sibling segments remains."""
    _patch_plot(monkeypatch, tmp_path)
    await _seed_chapter(["段一", "段二"])
    _stub_writer(monkeypatch, {
        1: [{"text": "底稿一", "sensation_notes": []}],
        2: [{"text": "底稿二", "sensation_notes": []}],
    })
    await write_chapter_skeleton.ainvoke({"chapter": 1, "stages": [
        {"stage_num": 1, "overview": ""}, {"stage_num": 2, "overview": ""}]})
    out = await patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "replace", "stage_num": 1, "fields": {"description": "新大纲"}}]})
    stages = _plot_raw()[0]["stages"]
    assert "beats" not in stages[0]
    assert stages[1]["beats"][0]["text"] == "底稿二"
    assert "beats" in out and "1" in out


@pytest.mark.asyncio
async def test_patch_replace_description_clears_chapter_and_downstream_archives(monkeypatch, tmp_path):
    """
改某段 description → 该章及以后所有角色的已构建 archive/timeline 失效，需连带清空并提示重构。"""
    _isolate_timeline(tmp_path, monkeypatch)
    _patch_plot(monkeypatch, tmp_path)
    await _seed_chapter(["段一", "段二"])
    await generate_one_chapter.ainvoke(
        {"chapter_index": 2, "title": "二", "core_xp": ["基调"], "stages": [_stage()]})
    _patch_built_chapters(monkeypatch, {1: ["甲"], 2: ["甲"]})
    _seed_archive(tmp_path, 1, "甲")
    _seed_archive(tmp_path, 2, "甲")

    from context import character_timeline as ct
    ct.append_stage("甲", 1, 1, {})
    ct.append_stage("甲", 2, 1, {})

    out = await patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "replace", "stage_num": 1, "fields": {"description": "新大纲"}}]})

    assert [s["chapter"] for s in ct.load_timeline("甲")["snapshots"]] == []
    assert "角色档案已清空" in out and "write_character_archive" in out
    #未涉及的段落数据不受影响
    stages = _plot_raw()[0]["stages"]
    assert stages[1]["description"] == "事件"


@pytest.mark.asyncio
async def test_patch_replace_non_description_field_keeps_archives(monkeypatch, tmp_path):
    """只改 title/characters 等非 description 字段 → 不触发 archive/timeline 清空。"""
    _isolate_timeline(tmp_path, monkeypatch)
    _patch_plot(monkeypatch, tmp_path)
    await _seed_chapter(["段一"])
    _patch_built_chapters(monkeypatch, {1: ["甲"]})
    _seed_archive(tmp_path, 1, "甲")

    out = await patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "replace", "stage_num": 1, "fields": {"title": "新标题"}}]})

    assert "角色档案已清空" not in out


@pytest.mark.asyncio
async def test_patch_replace_beats_directly_is_kept(monkeypatch, tmp_path):
    """Directly give the beats field → retain the disk without triggering invalidation."""
    _patch_plot(monkeypatch, tmp_path)
    await _seed_chapter(["段一"])
    await patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "replace", "stage_num": 1, "fields": {"beats": [{"text": "新底稿"}]}}]})
    stages = _plot_raw()[0]["stages"]
    assert stages[0]["beats"][0]["text"] == "新底稿"


@pytest.mark.asyncio
async def test_patch_add_inserts_and_renumbers(monkeypatch, tmp_path):
    """
add inserts and rearranges stage_num after the specified section (no skips)."""
    _patch_plot(monkeypatch, tmp_path)
    await _seed_chapter(["一", "二"])
    await patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "add", "after_stage_num": 1, "stage": _stage("插入")}]})
    stages = _plot_raw()[0]["stages"]
    assert [s["title"] for s in stages] == ["一", "插入", "二"]
    assert [s["stage_num"] for s in stages] == [1, 2, 3]


@pytest.mark.asyncio
async def test_patch_add_prepend(monkeypatch, tmp_path):
    """after_stage_num=0 inserts to the front."""
    _patch_plot(monkeypatch, tmp_path)
    await _seed_chapter(["一"])
    await patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "add", "after_stage_num": 0, "stage": _stage("最前")}]})
    stages = _plot_raw()[0]["stages"]
    assert [s["title"] for s in stages] == ["最前", "一"]
    assert [s["stage_num"] for s in stages] == [1, 2]


@pytest.mark.asyncio
async def test_patch_remove_and_renumbers(monkeypatch, tmp_path):
    """
remove: Rearrange the segments after deleting them to avoid sequence number jumps."""
    _patch_plot(monkeypatch, tmp_path)
    await _seed_chapter(["一", "二", "三"])
    await patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "remove", "stage_num": 2}]})
    stages = _plot_raw()[0]["stages"]
    assert [s["title"] for s in stages] == ["一", "三"]
    assert [s["stage_num"] for s in stages] == [1, 2]


def _fake_local_review(monkeypatch, calls: list[int]):
    """Stub engine.setup_chat.chapter_review.run_stage_local_review: records which
    stage_num it was called with, returns one canned transition + stage verdict
    each time so the report always has visible content to assert on."""
    import engine.author_loop.self_review as sr
    from engine.setup_chat.chapter_review import StageReview, TransitionReview

    async def _fake(stages, stage_num):
        calls.append(stage_num)
        return (
            [TransitionReview(stage_num, stage_num + 1,
                              sr.SelfReviewVerdict("accept", 8.0, [("coherence", 8)], ""))],
            [StageReview(stage_num,
                        sr.SelfReviewVerdict("accept", 9.0, [("style", 9)], ""))],
        )
    monkeypatch.setattr(
        "engine.setup_chat.chapter_review.run_stage_local_review", _fake)


@pytest.mark.asyncio
async def test_patch_replace_beat_triggers_local_review(monkeypatch, tmp_path):
    """replace_beat 改了内容 → 自动触发一次局部审查(只查这段,不是整章)，结果附在返回文本里。"""
    _patch_plot(monkeypatch, tmp_path)
    await _seed_chapter(["段一", "段二"])
    _stub_writer(monkeypatch, {
        1: [{"text": "底稿一", "sensation_notes": []}],
        2: [{"text": "底稿二", "sensation_notes": []}],
    })
    await write_chapter_skeleton.ainvoke({"chapter": 1, "stages": [
        {"stage_num": 1, "overview": ""}, {"stage_num": 2, "overview": ""}]})
    calls: list[int] = []
    _fake_local_review(monkeypatch, calls)

    out = await patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "replace_beat", "stage_num": 1, "beat_idx": 0, "beat": {"text": "改后底稿一"}}]})

    assert calls == [1]
    assert "过渡通过" in out and "文风" in out


@pytest.mark.asyncio
async def test_patch_replace_with_beats_triggers_local_review(monkeypatch, tmp_path):
    """replace 直接给新 beats(不是清空失效那种)→ 也算内容变化,触发局部审查。"""
    _patch_plot(monkeypatch, tmp_path)
    await _seed_chapter(["段一"])
    calls: list[int] = []
    _fake_local_review(monkeypatch, calls)

    await patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "replace", "stage_num": 1, "fields": {"beats": [{"text": "新底稿"}]}}]})

    assert calls == [1]


@pytest.mark.asyncio
async def test_patch_description_change_clearing_beats_does_not_trigger_review(monkeypatch, tmp_path):
    """description 改动导致 beats 被清空失效的那一段——没内容可审,不该触发审查。"""
    _patch_plot(monkeypatch, tmp_path)
    await _seed_chapter(["段一", "段二"])
    _stub_writer(monkeypatch, {
        1: [{"text": "底稿一", "sensation_notes": []}],
        2: [{"text": "底稿二", "sensation_notes": []}],
    })
    await write_chapter_skeleton.ainvoke({"chapter": 1, "stages": [
        {"stage_num": 1, "overview": ""}, {"stage_num": 2, "overview": ""}]})
    calls: list[int] = []
    _fake_local_review(monkeypatch, calls)

    await patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "replace", "stage_num": 1, "fields": {"description": "新大纲"}}]})

    assert calls == []


@pytest.mark.asyncio
async def test_patch_add_does_not_trigger_review(monkeypatch, tmp_path):
    """add 插入的新段还没有 beats,没东西可审。"""
    _patch_plot(monkeypatch, tmp_path)
    await _seed_chapter(["一", "二"])
    calls: list[int] = []
    _fake_local_review(monkeypatch, calls)

    await patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "add", "after_stage_num": 1, "stage": _stage("插入")}]})

    assert calls == []


@pytest.mark.asyncio
async def test_patch_remove_triggers_review_of_newly_adjacent_pair(monkeypatch, tmp_path):
    """删掉中间段后,原本被隔开的两段变成新的相邻关系——对这一对触发审查。"""
    _patch_plot(monkeypatch, tmp_path)
    await _seed_chapter(["一", "二", "三"])
    _stub_writer(monkeypatch, {
        1: [{"text": "底稿一", "sensation_notes": []}],
        2: [{"text": "底稿二", "sensation_notes": []}],
        3: [{"text": "底稿三", "sensation_notes": []}],
    })
    await write_chapter_skeleton.ainvoke({"chapter": 1, "stages": [
        {"stage_num": 1, "overview": ""}, {"stage_num": 2, "overview": ""},
        {"stage_num": 3, "overview": ""}]})
    calls: list[int] = []
    _fake_local_review(monkeypatch, calls)

    await patch_chapter.ainvoke({"chapter": 1, "ops": [{"op": "remove", "stage_num": 2}]})

    #删掉原 stage2 后,原 stage1/stage3 重排成新的 1/2,二者互为新相邻——两侧都作为触发点各查一次
    assert sorted(calls) == [1, 2]


@pytest.mark.asyncio
async def test_patch_multiple_touched_stages_dedupes_shared_transition(monkeypatch, tmp_path):
    """同批改了两个相邻段(各自 replace_beat)→ 两段各自触发一次局部审查调用,
    但渲染报告里共享的那条过渡不该重复出现两遍。"""
    _patch_plot(monkeypatch, tmp_path)
    await _seed_chapter(["段一", "段二"])
    _stub_writer(monkeypatch, {
        1: [{"text": "底稿一", "sensation_notes": []}],
        2: [{"text": "底稿二", "sensation_notes": []}],
    })
    await write_chapter_skeleton.ainvoke({"chapter": 1, "stages": [
        {"stage_num": 1, "overview": ""}, {"stage_num": 2, "overview": ""}]})
    calls: list[int] = []
    _fake_local_review(monkeypatch, calls)

    out = await patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "replace_beat", "stage_num": 1, "beat_idx": 0, "beat": {"text": "改一"}},
        {"op": "replace_beat", "stage_num": 2, "beat_idx": 0, "beat": {"text": "改二"}},
    ]})

    assert sorted(calls) == [1, 2]
    assert out.count("stage1→stage2") == 1  #去重:两侧都会产出同一条过渡,只渲染一次


@pytest.mark.asyncio
async def test_patch_unknown_chapter(monkeypatch, tmp_path):
    _patch_plot(monkeypatch, tmp_path)
    out = await patch_chapter.ainvoke({"chapter": 9, "ops": [
        {"op": "replace", "stage_num": 1, "fields": {"description": "x"}}]})
    assert "不存在" in out


@pytest.mark.asyncio
async def test_patch_unknown_stage_leaves_data_intact(monkeypatch, tmp_path):
    """Stages that cannot be located → The entire batch will not be written, and the original data will not be modified."""
    _patch_plot(monkeypatch, tmp_path)
    await _seed_chapter(["一"])
    out = await patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "replace", "stage_num": 5, "fields": {"description": "x"}}]})
    assert "无 stage 5" in out
    stages = _plot_raw()[0]["stages"]
    assert stages[0]["description"] == "事件"


@pytest.mark.asyncio
async def test_patch_remove_last_stage_rejected(monkeypatch, tmp_path):
    """
Delete until no paragraph is left → Reject (retain at least 1 paragraph), the original data remains unchanged."""
    _patch_plot(monkeypatch, tmp_path)
    await _seed_chapter(["一"])
    out = await patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "remove", "stage_num": 1}]})
    assert "至少需保留" in out
    stages = _plot_raw()[0]["stages"]
    assert len(stages) == 1


@pytest.mark.asyncio
async def test_patch_core_xp_alone_without_ops(monkeypatch, tmp_path):
    """core_xp 可单独给，不需要同时带 ops——整章其它字段/stages 不受影响。"""
    _patch_plot(monkeypatch, tmp_path)
    await _seed_chapter(["段一", "段二"])
    out = await patch_chapter.ainvoke({"chapter": 1, "ops": [], "core_xp": ["爽文", "复仇"]})
    assert "题材基调已替换" in out
    data = _plot_raw()[0]
    assert data["core_xp"] == ["爽文", "复仇"]
    assert [s["title"] for s in data["stages"]] == ["段一", "段二"]  #stages 未动


@pytest.mark.asyncio
async def test_patch_core_xp_alongside_stage_ops(monkeypatch, tmp_path):
    """core_xp 可以和 stage ops 一起给，两者都生效。"""
    _patch_plot(monkeypatch, tmp_path)
    await _seed_chapter(["段一", "段二"])
    await patch_chapter.ainvoke({
        "chapter": 1,
        "ops": [{"op": "replace", "stage_num": 2, "fields": {"description": "改后的事件"}}],
        "core_xp": ["悬疑"],
    })
    data = _plot_raw()[0]
    assert data["core_xp"] == ["悬疑"]
    assert data["stages"][1]["description"] == "改后的事件"


@pytest.mark.asyncio
async def test_patch_neither_ops_nor_core_xp_rejected(monkeypatch, tmp_path):
    """ops 和 core_xp 都不给 → 校验拒绝，不写入。"""
    _patch_plot(monkeypatch, tmp_path)
    await _seed_chapter(["一"])
    with pytest.raises(Exception, match="至少给一个"):
        await patch_chapter.ainvoke({"chapter": 1, "ops": []})


@pytest.mark.asyncio
async def test_patch_core_xp_omitted_leaves_it_unchanged(monkeypatch, tmp_path):
    """不给 core_xp（沿用默认 None）→ 原有 core_xp 不受影响。"""
    _patch_plot(monkeypatch, tmp_path)
    await _seed_chapter(["段一", "段二"])
    await patch_chapter.ainvoke({"chapter": 1, "ops": [
        {"op": "replace", "stage_num": 1, "fields": {"description": "新大纲"}}]})
    data = _plot_raw()[0]
    assert data["core_xp"] == ["基调"]  #_seed_chapter 里种下的原值


@pytest.mark.asyncio
async def test_patch_chapter_core_skips_review_when_run_review_false(monkeypatch, tmp_path):
    """手动编辑入口（REST）调用时不该触发局部 LLM 审查——那是给 chat agent 用的质量把关，
    手动编辑是用户主动改，不需要 agent 再评判一次。"""
    seed_plot([{
        "chapter": 1, "title": "第一章", "core_xp": [],
        "stages": [{"stage_num": 1, "title": "开场", "location": "客厅", "description": "旧描述",
                    "characters": {"甲": {}}, "beats": [{"text": "旧拍", "sensation_notes": []}]}],
    }])
    monkeypatch.setattr(
        "engine.setup_chat.tool_args.load_plot_grounding",
        lambda: {"character_names": ["甲"], "archetypes": ["天真烂漫型"]},
    )

    review_called = {"n": 0}

    async def fake_review(*_a, **_k):
        review_called["n"] += 1
        return [], []

    monkeypatch.setattr(
        "engine.setup_chat.chapter_review.run_stage_local_review", fake_review,
    )

    from engine.setup_chat.tools import _patch_chapter_core

    ok, msg = await _patch_chapter_core(
        1,
        [{"op": "replace_beat", "stage_num": 1, "beat_idx": 0, "beat": {"text": "新拍", "sensation_notes": []}}],
        run_review=False,
    )
    assert ok is True
    assert review_called["n"] == 0
    saved = _plot_raw()
    assert saved[0]["stages"][0]["beats"][0]["text"] == "新拍"


@pytest.mark.asyncio
async def test_patch_chapter_core_cancels_active_review_before_proceeding(monkeypatch, tmp_path):
    """Instead of rejecting, patch_chapter now cancels the in-flight review job (via
    cancel_active_review) and proceeds with its own normal edit -- confirmed here by mocking
    cancel_active_review and asserting it was awaited with the right args, and that the patch
    itself still goes through."""
    seed_plot([{
        "chapter": 2, "title": "第二章", "core_xp": [],
        "stages": [{"stage_num": 1, "title": "开场", "location": "客厅", "description": "旧描述",
                    "characters": {"甲": {}}, "beats": [{"text": "旧拍", "sensation_notes": []}]}],
    }])
    monkeypatch.setattr(
        "engine.setup_chat.tool_args.load_plot_grounding",
        lambda: {"character_names": ["甲"], "archetypes": ["天真烂漫型"]},
    )
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")

    cancel_calls = []

    async def fake_cancel(novel_id, chapter):
        cancel_calls.append((novel_id, chapter))

    monkeypatch.setattr(
        "engine.setup_chat.skeleton_background_review.cancel_active_review", fake_cancel,
    )

    from engine.setup_chat.tools import _patch_chapter_core

    ok, msg = await _patch_chapter_core(
        2, [{"op": "replace_beat", "stage_num": 1, "beat_idx": 0, "beat": {"text": "新拍", "sensation_notes": []}}],
        run_review=False,
    )

    assert ok is True
    assert cancel_calls == [("n", 2)]
    saved = _plot_raw()
    assert saved[0]["stages"][0]["beats"][0]["text"] == "新拍"


@pytest.mark.asyncio
async def test_patch_chapter_core_reschedules_review_when_chapter_still_complete(
    monkeypatch, tmp_path,
):
    seed_plot([{
        "chapter": 2, "title": "第二章", "core_xp": [],
        "stages": [{"stage_num": 1, "title": "开场", "location": "客厅", "description": "旧描述",
                    "characters": {"甲": {}}, "beats": [{"text": "旧拍", "sensation_notes": []}]}],
    }])
    monkeypatch.setattr(
        "engine.setup_chat.tool_args.load_plot_grounding",
        lambda: {"character_names": ["甲"], "archetypes": ["天真烂漫型"]},
    )
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")

    async def noop_cancel(novel_id, chapter):
        pass

    monkeypatch.setattr(
        "engine.setup_chat.skeleton_background_review.cancel_active_review", noop_cancel,
    )

    import engine.setup_chat.skeleton_pipeline as sp

    scheduled = []
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_background_review.schedule_chapter_review_fix",
        lambda chapter: scheduled.append(chapter),
    )
    monkeypatch.setattr(
        sp, "mark_review_active",
        lambda novel_id, chapter: sp._ACTIVE_REVIEWS.setdefault(novel_id, set()).add(chapter),
    )

    from engine.setup_chat.tools import _patch_chapter_core

    ok, _msg = await _patch_chapter_core(
        2, [{"op": "replace_beat", "stage_num": 1, "beat_idx": 0, "beat": {"text": "新拍", "sensation_notes": []}}],
        run_review=False,
    )

    assert ok is True
    assert scheduled == [2]  # stage 1's beats are still non-empty -> chapter_skeleton_complete
    assert sp.is_review_active("n", 2) is True


@pytest.mark.asyncio
async def test_patch_chapter_core_skips_reschedule_when_is_reviewed(monkeypatch, tmp_path):
    seed_plot([{
        "chapter": 2, "title": "第二章", "core_xp": [],
        "stages": [{"stage_num": 1, "title": "开场", "location": "客厅", "description": "旧描述",
                    "characters": {"甲": {}}, "beats": [{"text": "旧拍", "sensation_notes": []}]}],
    }])
    monkeypatch.setattr(
        "engine.setup_chat.tool_args.load_plot_grounding",
        lambda: {"character_names": ["甲"], "archetypes": ["天真烂漫型"]},
    )
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")

    async def noop_cancel(novel_id, chapter):
        pass

    monkeypatch.setattr(
        "engine.setup_chat.skeleton_background_review.cancel_active_review", noop_cancel,
    )

    scheduled = []
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_background_review.schedule_chapter_review_fix",
        lambda chapter: scheduled.append(chapter),
    )

    from engine.setup_chat.tools import _patch_chapter_core

    ok, _msg = await _patch_chapter_core(
        2,
        [{"op": "replace_beat", "stage_num": 1, "beat_idx": 0, "beat": {"text": "新拍", "sensation_notes": []}}],
        run_review=False,
        is_reviewed=True,
    )

    assert ok is True
    assert scheduled == []
    saved = _plot_raw()
    assert saved[0].get("skeleton_reviewed") is True


@pytest.mark.asyncio
async def test_patch_chapter_core_schedules_cascade_scoped_to_chapter_roster(monkeypatch, tmp_path):
    seed_plot([{
        "chapter": 2, "title": "第二章", "core_xp": [],
        "stages": [{"stage_num": 1, "title": "开场", "location": "客厅", "description": "甲乙对峙",
                    "characters": {"甲": {}, "乙": {}}, "beats": [{"text": "旧拍", "sensation_notes": []}]}],
    }])
    monkeypatch.setattr(
        "engine.setup_chat.tool_args.load_plot_grounding",
        lambda: {"character_names": ["甲", "乙"], "archetypes": ["天真烂漫型"]},
    )
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")
    monkeypatch.setattr(
        "engine.memory_recall.entity_index.scan_characters",
        lambda text: [n for n in ("甲", "乙") if n in text],
    )

    async def noop_cancel(novel_id, chapter):
        pass
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_background_review.cancel_active_review", noop_cancel,
    )

    captured = {}
    monkeypatch.setattr(
        "engine.setup_chat.timeline_auto.schedule_timeline_cascade",
        lambda min_chapter, names=None: captured.update(min_chapter=min_chapter, names=names),
    )

    from engine.setup_chat.tools import _patch_chapter_core

    await _patch_chapter_core(
        2, [{"op": "replace_beat", "stage_num": 1, "beat_idx": 0, "beat": {"text": "新拍", "sensation_notes": []}}],
        run_review=False,
    )

    assert captured == {"min_chapter": 2, "names": ["甲", "乙"]}


@pytest.mark.asyncio
async def test_patch_chapter_core_runs_review_by_default(monkeypatch, tmp_path):
    """默认（对话 agent 走的路径）仍要跑审查——行为不能因为这次重构而变。"""
    seed_plot([{
        "chapter": 1, "title": "第一章", "core_xp": [],
        "stages": [{"stage_num": 1, "title": "开场", "location": "客厅", "description": "旧描述",
                    "characters": {"甲": {}}, "beats": [{"text": "旧拍", "sensation_notes": []}]}],
    }])
    monkeypatch.setattr(
        "engine.setup_chat.tool_args.load_plot_grounding",
        lambda: {"character_names": ["甲"], "archetypes": ["天真烂漫型"]},
    )

    review_called = {"n": 0}

    async def fake_review(*_a, **_k):
        review_called["n"] += 1
        return [], []

    monkeypatch.setattr(
        "engine.setup_chat.chapter_review.run_stage_local_review", fake_review,
    )

    from engine.setup_chat.tools import _patch_chapter_core

    ok, _msg = await _patch_chapter_core(
        1,
        [{"op": "replace_beat", "stage_num": 1, "beat_idx": 0, "beat": {"text": "新拍2", "sensation_notes": []}}],
    )
    assert ok is True
    assert review_called["n"] == 1


@pytest.mark.asyncio
async def test_delete_chapter_core_not_found(monkeypatch, tmp_path):
    _patch_plot(monkeypatch, tmp_path)

    from engine.setup_chat.tools import _delete_chapter_core

    ok, msg, detail = await _delete_chapter_core(5)
    assert ok is False and "未找到" in msg and detail == {}


@pytest.mark.asyncio
async def test_delete_chapter_core_removes_chapter_and_cascades_archives(monkeypatch, tmp_path):
    _isolate_timeline(tmp_path, monkeypatch)
    _patch_plot(monkeypatch, tmp_path)
    await generate_one_chapter.ainvoke(
        {"chapter_index": 1, "title": "第一章", "core_xp": ["开端"], "stages": [_stage("一")]})
    await generate_one_chapter.ainvoke(
        {"chapter_index": 2, "title": "第二章", "core_xp": ["承"], "stages": [_stage("二")]})
    _patch_built_chapters(monkeypatch, {1: ["甲"], 2: ["甲"]})
    _seed_archive(tmp_path, 1, "甲")
    _seed_archive(tmp_path, 2, "甲")
    manuscript_dir = tmp_path / "chapters" / "第1章"
    manuscript_dir.mkdir(parents=True, exist_ok=True)
    (manuscript_dir / "第1章_主笔.md").write_text("正文", encoding="utf-8")

    from engine.setup_chat.tools import _delete_chapter_core
    import utils.paths as up
    monkeypatch.setattr(up, "chapters_dir", lambda: str(tmp_path / "chapters"))
    from context import character_timeline as ct
    ct.append_stage("甲", 1, 1, {})
    ct.append_stage("甲", 2, 1, {})

    ok, msg, detail = await _delete_chapter_core(1)
    assert ok is True
    assert "已删除第 1 章" in msg
    assert "第2章" in msg  # advisory about cascaded archive invalidation

    remaining = _plot_raw()
    assert [c["chapter"] for c in remaining] == [2]
    assert not manuscript_dir.exists()
    assert detail["chapter"] == 1
    assert detail["cleared_archive_chapters"] == [1, 2]
    assert detail["cleared_archive_characters"] == ["甲"]
