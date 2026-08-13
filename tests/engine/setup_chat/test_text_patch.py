"""text_patch 纯函数与 patch_text_fragment 工具测试。"""
import pytest

from repo_test_helpers import seed_lore, seed_plot
from engine.setup_chat.text_patch import (
    TextPatchMatchPolicy,
    TextPatchMode,
    TextPatchOp,
    apply_text_patches,
    find_match_spans,
    join_manuscript_blocks,
    slice_manuscript_blocks,
    split_manuscript_blocks,
)


def test_literal_unique_success():
    r = apply_text_patches("甲乙对峙，甲先开口。", [
        TextPatchOp(mode=TextPatchMode.LITERAL, find="甲先开口", replace="乙先开口"),
    ])
    assert r.ok
    assert r.text == "甲乙对峙，乙先开口。"


def test_unique_fails_on_multiple_hits():
    r = apply_text_patches("甲说甲说", [
        TextPatchOp(find="甲", replace="乙", match_policy=TextPatchMatchPolicy.UNIQUE),
    ])
    assert not r.ok
    assert r.steps[0].hits == 2
    assert len(r.steps[0].previews) == 2


def test_unique_fails_on_zero_hits():
    r = apply_text_patches("甲乙对峙", [
        TextPatchOp(find="丙", replace="丁"),
    ])
    assert not r.ok
    assert "未命中" in (r.error or "")


def test_all_replaces_everywhere():
    r = apply_text_patches("星黏液与星黏液", [
        TextPatchOp(find="星黏液", replace="粘液", match_policy=TextPatchMatchPolicy.ALL),
    ])
    assert r.ok
    assert r.text == "粘液与粘液"
    assert r.steps[0].replaced == 2


def test_first_replaces_one():
    r = apply_text_patches("甲乙甲", [
        TextPatchOp(find="甲", replace="丙", match_policy=TextPatchMatchPolicy.FIRST),
    ])
    assert r.ok
    assert r.text == "丙乙甲"


def test_regex_replace():
    spans = find_match_spans("stage1【标记】end", find=r"【[^】]+】", mode=TextPatchMode.REGEX)
    assert len(spans) == 1
    r = apply_text_patches("stage1【标记】end", [
        TextPatchOp(mode=TextPatchMode.REGEX, find=r"【[^】]+】", replace=""),
    ])
    assert r.ok
    assert r.text == "stage1end"


def test_serial_patches_rollback_on_failure():
    r = apply_text_patches("甲乙丙", [
        TextPatchOp(find="甲", replace="A", match_policy=TextPatchMatchPolicy.ALL),
        TextPatchOp(find="不存在", replace="X"),
    ])
    assert not r.ok
    assert r.text == "甲乙丙"


def test_manuscript_split_join():
    md = "块一\n\n---\n\n块二"
    blocks = split_manuscript_blocks(md)
    assert len(blocks) == 2
    assert slice_manuscript_blocks(blocks, stage_num=2) == "块二"
    assert join_manuscript_blocks(blocks) == md


def _patch_plot(plot):
    seed_plot(plot)


def _plot_raw():
    import repositories as repo

    return repo.get_plot_repo().list_raw()


_PLOT = [{"chapter": 1, "title": "一", "stages": [
    {
        "stage_num": 1, "title": "对峙", "location": "部室",
        "description": "甲乙对峙", "characters": {"甲": {}},
        "beats": [{"text": "甲走向乙。"}],
    },
    {
        "stage_num": 2, "title": "登场", "location": "走廊",
        "description": "丙登场", "characters": {"丙": {}},
        "beats": [{"text": "丙出现。"}],
    },
]}]


def _patch_lore():
    seed_lore([
        {"name": "甲", "given_name": "甲", "role": "甲型", "gender": "female"},
        {"name": "丙", "given_name": "丙", "role": "乙型", "gender": "female"},
    ])


@pytest.mark.asyncio
async def test_patch_text_fragment_plot_skeleton_stage(monkeypatch, tmp_path):
    import engine.setup_chat.tools as t
    _patch_lore()
    _patch_plot(_PLOT)
    out = await t.patch_text_fragment.ainvoke({
        "source": "plot_skeleton",
        "chapter": 1,
        "scope": "stage",
        "stage_num": 1,
        "beat_idx": 0,
        "patches": [{"find": "甲走向", "replace": "甲快步走向"}],
    })
    assert "补丁完成" in out
    data = _plot_raw()
    st = data[0]["stages"][0]
    assert st["beats"][0]["text"] == "甲快步走向乙。"
    assert st["description"] == "甲乙对峙"  # 其它字段不被碰


@pytest.mark.asyncio
async def test_patch_text_fragment_unique_fail(monkeypatch, tmp_path):
    import engine.setup_chat.tools as t
    _patch_lore()
    _patch_plot(_PLOT)
    out = await t.patch_text_fragment.ainvoke({
        "source": "plot_description",
        "chapter": 1,
        "scope": "chapter",
        "patches": [{"find": "甲", "replace": "丁"}],
    })
    assert "失败" in out
    assert "命中" in out


@pytest.mark.asyncio
async def test_patch_text_fragment_manuscript(monkeypatch, tmp_path):
    import engine.setup_chat.tools as t
    from api.services import pipeline_catalog as pc

    ch_dir = tmp_path / "chapters" / "第1章"
    ch_dir.mkdir(parents=True)
    md_path = ch_dir / "第1章_主笔.md"
    md_path.write_text("### 【阶段一：开场】\n\n- **【过程描述】**：星黏液蔓延。\n\n---\n\n块二", encoding="utf-8")
    monkeypatch.setattr(pc, "chapters_dir", lambda: tmp_path / "chapters")

    out = await t.patch_text_fragment.ainvoke({
        "source": "manuscript",
        "chapter": 1,
        "scope": "manuscript_stage",
        "stage_num": 1,
        "patches": [{"find": "星黏液", "replace": "粘液", "match_policy": "all"}],
    })
    assert "补丁完成" in out
    body = md_path.read_text(encoding="utf-8")
    assert "粘液蔓延" in body
    assert "星黏液" not in body


@pytest.mark.asyncio
async def test_patch_text_fragment_dry_run_no_write(monkeypatch, tmp_path):
    import engine.setup_chat.tools as t
    _patch_lore()
    _patch_plot(_PLOT)
    out = await t.patch_text_fragment.ainvoke({
        "source": "plot_skeleton",
        "chapter": 1,
        "scope": "stage",
        "stage_num": 1,
        "beat_idx": 0,
        "patches": [{"find": "甲走向", "replace": "甲跑向"}],
        "dry_run": True,
    })
    assert "dry_run" in out
    data = _plot_raw()
    assert data[0]["stages"][0]["beats"][0]["text"] == "甲走向乙。"
