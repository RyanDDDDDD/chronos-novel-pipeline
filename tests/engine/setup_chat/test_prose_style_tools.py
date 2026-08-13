"""setup_chat tools: write_prose_style_preset / list_prose_style_presets / read_prose_style_preset
let the chat agent create/inspect prose style presets straight from spoken user requirements.
Per docs/superpowers/specs/2026-07-22-prose-style-card-unification-design.md."""
import pytest
from engine.setup_chat.tools import (
    edit_prose_style_preset,
    list_prose_style_presets,
    read_prose_style_preset,
    write_prose_style_preset,
)
from pydantic import ValidationError


@pytest.fixture
def prose_styles_env(tmp_path, monkeypatch):
    """Both the static and the auto/chat-generated preset directories point at subdirs of
    tmp_path; patching engine.execution.prose_style's module-level prose_styles_dir once is
    enough for all three tools (write/list/read all go through that same imported name).
    Also blanks out content-pack scanning so the real repo's mature-content-pack presets
    (contributed_dirs("prose_style_dirs")) don't leak into these "empty preset dir" assertions."""
    skills_root = tmp_path / "skills"
    (skills_root / "prose-styles").mkdir(parents=True)
    auto_dir = tmp_path / "auto"
    auto_dir.mkdir()
    monkeypatch.setattr("engine.execution.prose_style.SKILLS_DIR", str(skills_root))
    monkeypatch.setattr("engine.execution.prose_style.prose_styles_dir", lambda: str(auto_dir))
    monkeypatch.setattr("context.content_packs._packs_dir", lambda: tmp_path / "no-packs")
    return auto_dir


def _valid_args(**overrides) -> dict:
    args = {
        "slug": "cold-news",
        "title": "冷峻新闻体",
        "opening": "开场定位一段。",
        "techniques": [
            "**手法一**：只写事实与动作「示例」",
            "**手法二**：句子偏短「示例」",
            "**手法三**：不加评论「示例」",
        ],
        "examples": [
            {"label": "开场铺垫", "text": "他站在门口，没有说话。"},
            {"label": "高潮收尾", "text": "灯灭了。"},
        ],
        "taboos": ["忌堆砌形容词：会显得腻"],
    }
    args.update(overrides)
    return args


@pytest.mark.asyncio
async def test_write_prose_style_preset_writes_card_file(prose_styles_env):
    result = await write_prose_style_preset.ainvoke(_valid_args())
    assert "已写入文风预设「cold-news」" in result
    card = (prose_styles_env / "cold-news.md").read_text(encoding="utf-8")
    assert card.startswith("# 语感调色：冷峻新闻体")
    assert "他站在门口，没有说话。" in card


@pytest.mark.asyncio
async def test_write_prose_style_preset_rejects_existing_slug(prose_styles_env):
    await write_prose_style_preset.ainvoke(_valid_args(title="第一版"))
    result = await write_prose_style_preset.ainvoke(_valid_args(title="第二版"))
    assert "已存在" in result
    assert "edit_prose_style_preset" in result
    card = (prose_styles_env / "cold-news.md").read_text(encoding="utf-8")
    assert card.startswith("# 语感调色：第一版")


@pytest.mark.asyncio
async def test_write_prose_style_preset_rejects_static_slug(prose_styles_env):
    skills_root = prose_styles_env.parent / "skills" / "prose-styles"
    (skills_root / "cold-news.md").write_text("# 语感调色：静态版\n\n开场。\n", encoding="utf-8")
    result = await write_prose_style_preset.ainvoke(_valid_args())
    assert "受保护" in result
    assert not (prose_styles_env / "cold-news.md").exists()


@pytest.mark.asyncio
async def test_write_prose_style_preset_rejects_bad_slug(prose_styles_env):
    with pytest.raises(ValidationError):
        await write_prose_style_preset.ainvoke(_valid_args(slug="Bad Slug!"))


@pytest.mark.asyncio
async def test_write_prose_style_preset_rejects_too_few_techniques(prose_styles_env):
    with pytest.raises(ValidationError):
        await write_prose_style_preset.ainvoke(_valid_args(techniques=["只有一条"]))


@pytest.mark.asyncio
async def test_edit_prose_style_preset_overwrites_existing(prose_styles_env):
    await write_prose_style_preset.ainvoke(_valid_args(title="第一版"))
    result = await edit_prose_style_preset.ainvoke(_valid_args(title="第二版"))
    assert "已更新文风预设「cold-news」" in result
    card = (prose_styles_env / "cold-news.md").read_text(encoding="utf-8")
    assert card.startswith("# 语感调色：第二版")


@pytest.mark.asyncio
async def test_edit_prose_style_preset_rejects_static_slug(prose_styles_env):
    skills_root = prose_styles_env.parent / "skills" / "prose-styles"
    (skills_root / "cold-news.md").write_text("# 语感调色：静态版\n\n开场。\n", encoding="utf-8")
    result = await edit_prose_style_preset.ainvoke(_valid_args())
    assert "受保护" in result
    assert not (prose_styles_env / "cold-news.md").exists()


@pytest.mark.asyncio
async def test_edit_prose_style_preset_rejects_missing_slug(prose_styles_env):
    result = await edit_prose_style_preset.ainvoke(_valid_args())
    assert "未找到" in result
    assert "write_prose_style_preset" in result
    assert not (prose_styles_env / "cold-news.md").exists()


def test_list_prose_style_presets_tags_origin(prose_styles_env):
    skills_root = prose_styles_env.parent / "skills" / "prose-styles"
    (skills_root / "plain-explicit.md").write_text("# 语感调色：朴素\n\n开场。\n", encoding="utf-8")
    (prose_styles_env / "custom-a.md").write_text("# 语感调色：自定义A\n\n开场。\n", encoding="utf-8")
    out = list_prose_style_presets.invoke({})
    assert "plain-explicit｜语感调色：朴素（静态·不可改）" in out
    assert "custom-a｜语感调色：自定义A（可编辑）" in out


def test_list_prose_style_presets_empty_gives_hint(prose_styles_env):
    out = list_prose_style_presets.invoke({})
    assert "暂无任何文风预设" in out


def test_read_prose_style_preset_returns_full_card(prose_styles_env):
    (prose_styles_env / "custom-a.md").write_text("# 语感调色：自定义A\n\n开场句。\n", encoding="utf-8")
    out = read_prose_style_preset.invoke({"preset_id": "custom-a"})
    assert "开场句。" in out


def test_read_prose_style_preset_missing_gives_hint(prose_styles_env):
    out = read_prose_style_preset.invoke({"preset_id": "no-such"})
    assert "未找到预设" in out
    assert "list_prose_style_presets" in out
