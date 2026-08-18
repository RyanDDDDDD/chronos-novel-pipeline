import engine.setup_chat.chapter_review as cr
import engine.setup_chat.skeleton_writer as sw
import engine.setup_chat.tools as t
import pytest

from repo_test_helpers import seed_plot


@pytest.fixture(autouse=True)
def _reset_review_active():
    import engine.setup_chat.skeleton_pipeline as sp
    sp._ACTIVE_REVIEWS.clear()
    yield
    sp._ACTIVE_REVIEWS.clear()


def _patch_plot(plot):
    seed_plot(plot)


def _plot_raw():
    import repositories as repo

    return repo.get_plot_repo().list_raw()


_PLOT = [{"chapter": 1, "title": "一", "stages": [
    {"stage_num": 1, "description": "甲乙对峙", "characters": {"甲": {}}},
    {"stage_num": 2, "description": "丙登场", "characters": {"丙": {}}},
]}]


def _stub_writer(monkeypatch, beats_by_stage=None, *, fail_stage=None, error="模型超时"):
    """Stub skeleton_writer.generate_stage_beats so write_chapter_skeleton tests don't need a
    real LLM. beats_by_stage: {stage_num: [beat dicts]}, defaults to one canned beat per stage.
    fail_stage: if given, that stage_num's call returns `error` (an error string) instead."""
    async def fake(chapter, stage_num, *, overview, is_revision):
        if fail_stage is not None and stage_num == fail_stage:
            return error
        beats = (beats_by_stage or {}).get(stage_num)
        if beats is not None:
            return beats
        return [{"text": f"stage{stage_num}默认拍文", "sensation_notes": []}]
    monkeypatch.setattr(sw, "generate_stage_beats", fake)


@pytest.mark.asyncio
async def test_write_skeleton_back_to_stage(monkeypatch, tmp_path):
    _patch_plot(_PLOT)
    _stub_writer(monkeypatch, {1: [{"text": "扩写后的丰富底稿…", "sensation_notes": []}]})
    out = await t.write_chapter_skeleton.ainvoke({
        "chapter": 1, "stages": [{"stage_num": 1, "overview": ""}],
    })
    assert "第 1 章" in out or "已" in out
    data = _plot_raw()
    st = data[0]["stages"]
    assert st[0]["beats"][0]["text"] == "扩写后的丰富底稿…"
    assert st[0]["description"] == "甲乙对峙"
    assert "beats" not in st[1]


@pytest.mark.asyncio
async def test_write_chapter_skeleton_rejects_stale_version(monkeypatch, tmp_path):
    _patch_plot(_PLOT)
    _stub_writer(monkeypatch, {1: [{"text": "扩写后的丰富底稿…", "sensation_notes": []}]})

    import repositories

    # A write that "already landed" -- bumps chapter 1's on-disk version by one.
    outline, version = repositories.get_plot_repo().get_outline_with_version(1)
    repositories.get_plot_repo().save_chapter_if_version_matches(1, outline, version)

    import repositories.sqlite_repositories as sqlite_repositories
    real_get = sqlite_repositories.SqlitePlotRepository.get_outline_with_version

    def _stale_get(self, chapter):
        result = real_get(self, chapter)
        if result is None:
            return None
        data, _real_version = result
        return data, version  # report the pre-bump version on purpose

    monkeypatch.setattr(
        sqlite_repositories.SqlitePlotRepository, "get_outline_with_version", _stale_get,
    )

    out = await t.write_chapter_skeleton.ainvoke({
        "chapter": 1, "stages": [{"stage_num": 1, "overview": ""}],
    })
    assert "已被修改" in out


@pytest.mark.asyncio
async def test_write_skeleton_bad_stage(monkeypatch, tmp_path):
    _patch_plot(_PLOT)
    out = await t.write_chapter_skeleton.ainvoke({
        "chapter": 1, "stages": [{"stage_num": 9, "overview": ""}],
    })
    assert "stage" in out and "9" in out


@pytest.mark.asyncio
async def test_write_skeleton_updates_plot_indexer_cache(monkeypatch, tmp_path):
    """After writing the skeleton, the repositories must be immediately visible without restarting the application."""
    del tmp_path
    _patch_plot(_PLOT)
    _stub_writer(monkeypatch, {1: [{"text": "扩写后的丰富底稿…", "sensation_notes": []}]})

    from repositories import get_plot_repo
    _, before = get_plot_repo().chapter_segments(1)
    assert not before[0].get("beats")

    await t.write_chapter_skeleton.ainvoke({
        "chapter": 1, "stages": [{"stage_num": 1, "overview": ""}],
    })

    _, after = get_plot_repo().chapter_segments(1)
    assert after[0]["beats"][0]["text"] == "扩写后的丰富底稿…"


@pytest.mark.asyncio
async def test_read_skeleton_seed_renders(monkeypatch, tmp_path):
    import engine.setup_chat.tools as tt

    del tmp_path
    _patch_plot(_PLOT)

    out = await tt.read_skeleton_seed.ainvoke({"chapter": 1})
    assert "甲" in out and "甲乙对峙" in out
    assert "## 世界观" in out
    assert "## 角色档案" in out
    assert "{" not in out


@pytest.mark.asyncio
async def test_set_chapter_direction_records_and_confirms(monkeypatch):
    import engine.setup_chat.skeleton_pipeline as sp
    sp._DIRECTION_SET.clear()
    out = await t.set_chapter_direction.ainvoke({"chapter": 2, "direction": "甲线"})
    assert "已记录" in out
    assert 2 in sp._DIRECTION_SET


@pytest.mark.asyncio
async def test_set_stage_lens_records_and_confirms(monkeypatch):
    import engine.setup_chat.skeleton_pipeline as sp
    sp._LENS_CHOSEN.clear()
    out = await t.set_stage_lens.ainvoke({"chapter": 2, "stage_num": 1, "angles": ["压迫感"]})
    assert "已记录" in out
    assert sp._LENS_CHOSEN[(2, 1)] == ["压迫感"]


@pytest.mark.asyncio
async def test_set_stage_extensions_records_and_confirms(monkeypatch):
    import engine.setup_chat.skeleton_pipeline as sp
    sp._EXT_CHOSEN.clear()
    out = await t.set_stage_extensions.ainvoke({"chapter": 2, "stage_num": 1, "extensions": []})
    assert "已记录" in out
    assert sp._EXT_CHOSEN[(2, 1)] == []


@pytest.mark.asyncio
async def test_write_chapter_skeleton_clears_stage_markers_on_success(monkeypatch, tmp_path):
    import engine.setup_chat.skeleton_pipeline as sp

    class _Repo:
        def list_raw(self):
            return [{"chapter": 2, "stages": [{"stage_num": 1}]}]
        def get_outline_with_version(self, chapter):
            if chapter != 2:
                return None
            return {"chapter": 2, "stages": [{"stage_num": 1}]}, 1
        def save_chapter_if_version_matches(self, chapter, data, expected_version):
            return expected_version + 1
        def save_all(self, chapters):
            pass
    monkeypatch.setattr("repositories.get_plot_repo", lambda: _Repo())
    _stub_writer(monkeypatch)
    sp.set_stage_lens(2, 1, ["a"])
    sp.set_stage_extensions(2, 1, [])
    await t.write_chapter_skeleton.ainvoke(
        {"chapter": 2, "stages": [{"stage_num": 1, "overview": ""}]}
    )
    assert (2, 1) not in sp._LENS_CHOSEN
    assert (2, 1) not in sp._EXT_CHOSEN


@pytest.mark.asyncio
async def test_write_chapter_skeleton_no_report_when_chapter_incomplete(monkeypatch, tmp_path):
    _patch_plot(_PLOT)
    _stub_writer(monkeypatch)
    out = await t.write_chapter_skeleton.ainvoke({
        "chapter": 1, "stages": [{"stage_num": 1, "overview": ""}],
    })
    assert "过渡审查" not in out


@pytest.mark.asyncio
async def test_write_chapter_skeleton_dispatches_background_review_when_chapter_complete(
    monkeypatch, tmp_path,
):
    _patch_plot(_PLOT)
    _stub_writer(monkeypatch, {1: [{"text": "第一段底稿。", "sensation_notes": []}],
                               2: [{"text": "第二段底稿。", "sensation_notes": []}]})

    import engine.setup_chat.skeleton_pipeline as sp

    scheduled = []

    def fake_schedule(chapter):
        scheduled.append(chapter)

    monkeypatch.setattr(
        "engine.setup_chat.skeleton_background_review.schedule_chapter_review_fix",
        fake_schedule,
    )
    monkeypatch.setattr("utils.paths.active_novel_id", lambda: "n")
    monkeypatch.setattr(
        sp, "mark_review_active",
        lambda novel_id, chapter: sp._ACTIVE_REVIEWS.setdefault(novel_id, set()).add(chapter),
    )

    out = await t.write_chapter_skeleton.ainvoke({
        "chapter": 1, "stages": [{"stage_num": 1, "overview": ""}],
    })
    assert scheduled == []  # chapter not complete yet (stage 2 still unwritten)
    assert sp.is_review_active("n", 1) is False

    out = await t.write_chapter_skeleton.ainvoke({
        "chapter": 1, "stages": [{"stage_num": 2, "overview": ""}],
    })

    assert "第 1 章" in out
    assert "后台" in out
    assert "审查" in out
    assert scheduled == [1]
    assert sp.is_review_active("n", 1) is True


@pytest.mark.asyncio
async def test_write_chapter_skeleton_no_background_dispatch_when_chapter_incomplete(
    monkeypatch, tmp_path,
):
    _patch_plot(_PLOT)
    _stub_writer(monkeypatch)

    scheduled = []
    monkeypatch.setattr(
        "engine.setup_chat.skeleton_background_review.schedule_chapter_review_fix",
        lambda chapter: scheduled.append(chapter),
    )

    out = await t.write_chapter_skeleton.ainvoke({
        "chapter": 1, "stages": [{"stage_num": 1, "overview": ""}],
    })
    assert scheduled == []
    assert "后台" not in out


@pytest.mark.asyncio
async def test_write_chapter_skeleton_generation_failure_persists_nothing(monkeypatch, tmp_path):
    """All-or-nothing: if any stage's generation fails, nothing in the batch is written."""
    _patch_plot(_PLOT)
    _stub_writer(monkeypatch, fail_stage=2, error="模型返回的 JSON 解析失败")

    out = await t.write_chapter_skeleton.ainvoke({
        "chapter": 1,
        "stages": [{"stage_num": 1, "overview": ""}, {"stage_num": 2, "overview": ""}],
    })

    assert "2" in out
    assert "模型返回的 JSON 解析失败" in out
    data = _plot_raw()
    st = data[0]["stages"]
    assert "beats" not in st[0]  # stage 1 would have succeeded alone, but nothing persists
    assert "beats" not in st[1]


@pytest.mark.asyncio
async def test_write_chapter_skeleton_revision_calls_generator_with_is_revision_true(
    monkeypatch, tmp_path,
):
    plot_with_beats = [{"chapter": 1, "title": "一", "stages": [
        {"stage_num": 1, "description": "甲乙对峙", "characters": {"甲": {}},
         "beats": [{"text": "旧拍文", "sensation_notes": []}]},
    ]}]
    _patch_plot(plot_with_beats)

    captured = {}

    async def fake(chapter, stage_num, *, overview, is_revision):
        captured["is_revision"] = is_revision
        captured["overview"] = overview
        return [{"text": "改后拍文", "sensation_notes": []}]
    monkeypatch.setattr(sw, "generate_stage_beats", fake)

    await t.write_chapter_skeleton.ainvoke({
        "chapter": 1, "stages": [{"stage_num": 1, "overview": "改成更压抑的基调"}],
    })

    assert captured["is_revision"] is True
    assert captured["overview"] == "改成更压抑的基调"


@pytest.mark.asyncio
async def test_read_skeleton_seed_marks_chapter_active(monkeypatch, tmp_path):
    import engine.setup_chat.skeleton_pipeline as sp
    sp._ACTIVE_CHAPTER = None

    del tmp_path
    _patch_plot(_PLOT)

    await t.read_skeleton_seed.ainvoke({"chapter": 1})
    assert sp._ACTIVE_CHAPTER == 1


@pytest.mark.asyncio
async def test_read_skeleton_seed_missing_chapter_does_not_mark_active(monkeypatch, tmp_path):
    import engine.setup_chat.skeleton_pipeline as sp
    sp._ACTIVE_CHAPTER = None
    _patch_plot(_PLOT)

    await t.read_skeleton_seed.ainvoke({"chapter": 99})
    assert sp._ACTIVE_CHAPTER is None


@pytest.mark.asyncio
async def test_write_skeleton_clears_active_chapter_on_completion(monkeypatch, tmp_path):
    import engine.setup_chat.skeleton_pipeline as sp
    sp._ACTIVE_CHAPTER = 1
    #single-stage chapter: writing its only stage completes the chapter
    single_stage_plot = [{"chapter": 1, "title": "一", "stages": [
        {"stage_num": 1, "description": "甲乙对峙", "characters": {"甲": {}}},
    ]}]
    _patch_plot(single_stage_plot)
    _stub_writer(monkeypatch)

    await t.write_chapter_skeleton.ainvoke({
        "chapter": 1, "stages": [{"stage_num": 1, "overview": ""}],
    })
    assert sp._ACTIVE_CHAPTER is None


@pytest.mark.asyncio
async def test_write_skeleton_keeps_active_chapter_when_incomplete(monkeypatch, tmp_path):
    import engine.setup_chat.skeleton_pipeline as sp
    sp._ACTIVE_CHAPTER = 1
    #_PLOT has two stages; writing only stage 1 leaves stage 2 unexpanded
    _patch_plot(_PLOT)
    _stub_writer(monkeypatch)

    await t.write_chapter_skeleton.ainvoke({
        "chapter": 1, "stages": [{"stage_num": 1, "overview": ""}],
    })
    assert sp._ACTIVE_CHAPTER == 1
