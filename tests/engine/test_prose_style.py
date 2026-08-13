"""文风卡动态拼装与注入测试。"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "backend"))


@pytest.fixture
def prose_env(tmp_path, monkeypatch):
    """隔离 skills 与 active 小说目录，且不让真仓库的内容包泄漏进来
    （contributed_dirs("prose_style_dirs") 不隔离的话会读到真实 hooks/content_packs/ 下的
    预设，污染这里对静态预设列表的断言）。"""
    skills = tmp_path / "skills"
    presets = skills / "prose-styles"
    presets.mkdir(parents=True)
    (presets / "plain-direct.md").write_text("PLAIN", encoding="utf-8")
    (presets / "plain-explicit.md").write_text("PLAIN_EXPLICIT", encoding="utf-8")

    novels = tmp_path / "novels"
    novel_dir = novels / "default"
    (novel_dir / "lore").mkdir(parents=True)
    (novel_dir / "plot").mkdir()
    (novel_dir / "chapters").mkdir()

    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(novels))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "default")
    monkeypatch.setattr("engine.execution.prose_style.SKILLS_DIR", str(skills))
    monkeypatch.setattr("context.content_packs._packs_dir", lambda: tmp_path / "no-packs")
    return skills, novel_dir


def _write_novel_settings(novel_dir, settings: dict) -> None:
    """prose_style now lives in chronos.sqlite3's documents table (doc_key='novel_settings'),
    not novel.json -- write through the same SqliteStore path production code uses."""
    from repositories.sqlite_store import SqliteStore

    SqliteStore(novel_dir.name).save_doc("novel_settings", "", settings)


def _write_raw_novel_settings_doc(novel_dir, raw: str) -> None:
    """Simulates a corrupt novel_settings doc (invalid JSON in data_json column) to exercise
    the same defensive fallback the old corrupt-novel.json test covered."""
    from repositories.sqlite_store import get_connection
    from utils.paths import novel_dir as novel_dir_path

    conn = get_connection(os.path.join(novel_dir_path(novel_dir.name), "chronos.sqlite3"))
    conn.execute(
        "INSERT OR REPLACE INTO documents (doc_key, data_json) VALUES ('novel_settings', ?)",
        (raw,),
    )
    conn.commit()


def test_build_card_concats_preset_addendum(prose_env):
    from engine.execution.prose_style import build_active_prose_style_card

    _, novel_dir = prose_env
    _write_novel_settings(
        novel_dir,
        {"prose_style": {"preset": "plain-explicit", "custom_addendum": "额外要求"}},
    )
    card = build_active_prose_style_card()
    assert "PLAIN_EXPLICIT" in card and "额外要求" in card
    #顺序：preset(PLAIN_EXPLICIT) → custom(额外要求)
    assert card.index("PLAIN_EXPLICIT") < card.index("额外要求")


def test_missing_preset_yields_empty_card(prose_env):
    from engine.execution.prose_style import build_active_prose_style_card

    _, novel_dir = prose_env
    _write_novel_settings(novel_dir, {"prose_style": {"preset": "no-such-preset"}})
    #底座已退役：preset 缺失且无 custom → 空卡（注入层对空串是 no-op）
    assert build_active_prose_style_card() == ""


def test_no_config_defaults_plain_direct(prose_env):
    from engine.execution.prose_style import build_active_prose_style_card

    _, novel_dir = prose_env
    #novel_settings doc 完全没写过（对应旧测试"novel.json 存在但没有 prose_style 字段"的场景）
    card = build_active_prose_style_card()
    assert "PLAIN" in card


def test_blank_addendum_skipped(prose_env):
    from engine.execution.prose_style import build_active_prose_style_card

    _, novel_dir = prose_env
    _write_novel_settings(
        novel_dir, {"prose_style": {"preset": "plain-explicit", "custom_addendum": ""}},
    )
    card = build_active_prose_style_card()
    assert card == "PLAIN_EXPLICIT"


def test_corrupt_novel_json_falls_back(prose_env):
    from engine.execution.prose_style import build_active_prose_style_card

    _, novel_dir = prose_env
    _write_raw_novel_settings_doc(novel_dir, "{bad json")
    card = build_active_prose_style_card()
    assert "PLAIN" in card


def test_prose_style_card_loads():
    """底座已退役：卡内容来自 per-novel preset；反向禁用卡（prose-style-negative.md）
    因对 LLM 不生效已整体移除，机械护栏改走 style_guard.py 硬编码。"""
    from engine.execution.prose_style import build_active_prose_style_card

    card = build_active_prose_style_card()
    assert isinstance(card, str)
    assert card.strip()
    assert "语感调色" in card


def test_render_prose_style_card_full_structure():
    from engine.execution.prose_style import render_prose_style_card

    card = render_prose_style_card(
        title="清冷疏离",
        opening="开场定位一段。",
        techniques=["**留白**：只写动作「示例」"],
        examples=[
            {"label": "开场铺垫", "text": "夜色浓稠。"},
            {"label": "高潮收尾", "text": "他松开了手。"},
        ],
        taboos=["忌堆砌形容词：会显得腻"],
    )
    assert card.startswith("# 语感调色：清冷疏离")
    assert "开场定位一段。" in card
    assert "## 这套怎么写（发挥方向）" in card
    assert "- **留白**：只写动作「示例」" in card
    assert "## 风格样例" in card
    assert "> **示例1·开场铺垫**" in card
    assert "> 夜色浓稠。" in card
    assert "> **示例2·高潮收尾**" in card
    assert "## 这套忌讳" in card
    assert "- 忌堆砌形容词：会显得腻" in card


def test_render_prose_style_card_skips_empty_sections():
    from engine.execution.prose_style import render_prose_style_card

    card = render_prose_style_card(
        title="极简", opening="开场。", techniques=[], examples=[], taboos=[],
    )
    assert card == "# 语感调色：极简\n\n开场。"
    assert "## " not in card


@pytest.fixture
def prose_env_with_auto(prose_env, monkeypatch):
    """Adds an auto/chat-generated preset directory on top of prose_env (now stores .md files
    just like the static directory)."""
    skills, novel_dir = prose_env
    auto_dir = skills.parent / "data_prose_styles"
    auto_dir.mkdir(parents=True)
    monkeypatch.setattr("engine.execution.prose_style.prose_styles_dir", lambda: str(auto_dir))
    return skills, novel_dir, auto_dir


def test_load_preset_card_renders_auto_generated_markdown(prose_env_with_auto):
    from engine.execution.prose_style import load_preset_card

    _, _, auto_dir = prose_env_with_auto
    (auto_dir / "auto-nov1.md").write_text(
        "# 语感调色：测试小说风格\n\n"
        "句式偏短，多用感官细节。\n\n"
        "## 风格样例\n\n> **示例1·环境**\n> 夜色浓稠。\n",
        encoding="utf-8",
    )
    card = load_preset_card("auto-nov1")
    assert "句式偏短，多用感官细节。" in card
    assert "夜色浓稠。" in card


def test_load_preset_card_prefers_static_over_auto(prose_env_with_auto):
    from engine.execution.prose_style import load_preset_card

    skills, _, auto_dir = prose_env_with_auto
    (auto_dir / "plain-explicit.md").write_text("# 语感调色：冒充\n\n冒充内容\n", encoding="utf-8")
    assert load_preset_card("plain-explicit") == "PLAIN_EXPLICIT"


def test_list_prose_style_presets_merges_static_and_auto(prose_env_with_auto):
    from engine.execution.prose_style import list_prose_style_presets

    _, _, auto_dir = prose_env_with_auto
    (auto_dir / "auto-nov1.md").write_text("# 语感调色：测试小说风格\n\n开场。\n", encoding="utf-8")
    ids = {p["id"] for p in list_prose_style_presets()}
    titles = {p["title"] for p in list_prose_style_presets()}
    assert "plain-direct" in ids and "plain-explicit" in ids and "auto-nov1" in ids
    assert "语感调色：测试小说风格" in titles


def test_list_prose_style_presets_missing_auto_dir_is_fine(prose_env, tmp_path, monkeypatch):
    """auto 目录不存在时（没有小说自动生成过文风）不报错，只返回静态预设。用一个确定不存在
    的 tmp 子路径隔离，不能依赖"真实 data/prose_styles/ 恰好是空的"这个不可靠的前提。"""
    from engine.execution.prose_style import list_prose_style_presets

    monkeypatch.setattr(
        "engine.execution.prose_style.prose_styles_dir",
        lambda: str(tmp_path / "no_such_auto_dir"),
    )
    ids = {p["id"] for p in list_prose_style_presets()}
    assert ids == {"plain-direct", "plain-explicit"}


def test_is_static_preset_true_for_static_file(prose_env_with_auto):
    from engine.execution.prose_style import is_static_preset

    assert is_static_preset("plain-explicit") is True


def test_is_static_preset_false_for_custom_or_missing(prose_env_with_auto):
    from engine.execution.prose_style import is_static_preset

    _, _, auto_dir = prose_env_with_auto
    (auto_dir / "auto-nov1.md").write_text("# 语感调色：测试\n\n开场。\n", encoding="utf-8")
    assert is_static_preset("auto-nov1") is False
    assert is_static_preset("no-such-id") is False


def test_list_prose_style_presets_tags_origin(prose_env_with_auto):
    from engine.execution.prose_style import list_prose_style_presets

    _, _, auto_dir = prose_env_with_auto
    (auto_dir / "auto-nov1.md").write_text("# 语感调色：测试小说风格\n\n开场。\n", encoding="utf-8")
    by_id = {p["id"]: p["origin"] for p in list_prose_style_presets()}
    assert by_id["plain-direct"] == "static"
    assert by_id["auto-nov1"] == "custom"


def test_static_prose_style_dirs_includes_content_pack_contributions(monkeypatch):
    """Regression for the 2026-07-29 prose-style migration: content-pack-specific presets
    now live under hooks/content_packs/<pack>/prose_styles/ instead of
    skills/prose-styles/, reached only via contributed_dirs("prose_style_dirs")."""
    from engine.execution.prose_style import _static_prose_style_dirs

    monkeypatch.setattr(
        "context.content_packs.contributed_dirs",
        lambda attr: ["/fake/pack/prose_styles"] if attr == "prose_style_dirs" else [],
    )
    assert "/fake/pack/prose_styles" in _static_prose_style_dirs()


def test_list_prose_style_presets_includes_content_pack_contributions(prose_env, monkeypatch, tmp_path):
    from engine.execution.prose_style import list_prose_style_presets

    pack_dir = tmp_path / "pack_prose_styles"
    pack_dir.mkdir()
    (pack_dir / "pack-exclusive.md").write_text("# 语感调色：内容包专属示例\n\n正文。\n", encoding="utf-8")
    monkeypatch.setattr(
        "context.content_packs.contributed_dirs",
        lambda attr: [str(pack_dir)] if attr == "prose_style_dirs" else [],
    )
    by_id = {p["id"]: p["origin"] for p in list_prose_style_presets()}
    assert by_id["pack-exclusive"] == "static"


def test_default_prose_style_preset():
    from engine.execution.prose_style import default_prose_style_preset

    assert default_prose_style_preset() == "plain-direct"


def test_read_active_prose_style_config_defaults_to_plain_direct(prose_env):
    from engine.execution.prose_style import read_active_prose_style_config

    _, novel_dir = prose_env
    _write_novel_settings(novel_dir, {})
    cfg = read_active_prose_style_config()
    assert cfg["preset"] == "plain-direct"
