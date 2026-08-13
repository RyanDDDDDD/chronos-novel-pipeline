"""scripts/migrate_prose_style_json_to_md.py: converts legacy JSON-format auto-generated prose
style presets (data/prose_styles/auto-<novel_id>.json) into the new full markdown card format
(auto-<novel_id>.md). Per docs/superpowers/specs/2026-07-22-prose-style-card-unification-design.md."""
import json

import pytest

from scripts.migrate_prose_style_json_to_md import (
    convert_legacy_preset,
    migrate_prose_style_json_to_md,
)


def test_convert_legacy_preset_unwraps_book_title_and_flattens_samples():
    data = {
        "id": "auto-nov1",
        "name": "《测试小说》风格",
        "rules": "句式偏短，多用感官细节。",
        "samples": {
            "环境": ["夜色浓稠。"], "台词": [], "动作": ["她攥紧了衣角。"],
            "亲密描写": [], "心理": [],
        },
    }
    fields = convert_legacy_preset(data)
    assert fields["title"] == "测试小说"
    assert fields["opening"] == "句式偏短，多用感官细节。"
    assert {"label": "环境", "text": "夜色浓稠。"} in fields["examples"]
    assert {"label": "动作", "text": "她攥紧了衣角。"} in fields["examples"]
    assert fields["techniques"] == []
    assert fields["taboos"] == []


def test_convert_legacy_preset_keeps_name_as_is_when_not_wrapped():
    data = {"id": "auto-nov2", "name": "随便起的名字", "rules": "r", "samples": {}}
    fields = convert_legacy_preset(data)
    assert fields["title"] == "随便起的名字"


def test_convert_legacy_preset_caps_examples_at_five():
    data = {
        "id": "x", "name": "X", "rules": "",
        "samples": {"环境": [f"句子{i}。" for i in range(8)]},
    }
    fields = convert_legacy_preset(data)
    assert len(fields["examples"]) == 5


@pytest.fixture
def prose_styles_env(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.migrate_prose_style_json_to_md.prose_styles_dir", lambda: str(tmp_path),
    )
    return tmp_path


def test_migrate_writes_md_and_removes_json(prose_styles_env):
    d = prose_styles_env
    (d / "auto-nov1.json").write_text(
        json.dumps({
            "id": "auto-nov1", "name": "《测试小说》风格", "rules": "句式偏短。",
            "samples": {"环境": ["夜色浓稠。"]},
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    migrated = migrate_prose_style_json_to_md()
    assert migrated == {"auto-nov1.json": "auto-nov1.md"}
    assert not (d / "auto-nov1.json").exists()
    card = (d / "auto-nov1.md").read_text(encoding="utf-8")
    assert card.startswith("# 语感调色：测试小说")
    assert "夜色浓稠。" in card


def test_migrate_noop_when_no_json_files(prose_styles_env):
    assert migrate_prose_style_json_to_md() == {}
