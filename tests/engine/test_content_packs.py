"""content_packs SSOT test: baseline-only + fixture pack merge, no real content-pack dependency."""
from __future__ import annotations

import textwrap

import pytest

from context import content_packs as cp

_FIXTURE_HOOK = textwrap.dedent('''
    from context.content_packs import ContentPack, CustomFieldSpec

    CONTENT_PACK = ContentPack(
        extra_genders=["nonbinary"],
        extra_physique_slots_by_gender={"nonbinary": {"胸部"}},
        slot_annotations={"胸部": "夹具测试注释"},
        custom_fields=[CustomFieldSpec(name="爱好癖", required=True, timeline_delta=True)],
    )
''')


@pytest.fixture(autouse=True)
def _reset_cache():
    cp.reload_content_packs()
    yield
    cp.reload_content_packs()


def _write_fixture_pack(tmp_path, name="fixture_pack"):
    pack_dir = tmp_path / name
    pack_dir.mkdir()
    (pack_dir / "hook.py").write_text(_FIXTURE_HOOK, encoding="utf-8")
    return tmp_path


def test_baseline_has_no_content_packs(monkeypatch, tmp_path):
    monkeypatch.setattr(cp, "_packs_dir", lambda: tmp_path / "empty")
    assert cp.get_gender_values() == ["male", "female"]
    assert cp.physique_slots("male") == {"体型", "肌肤", "面部", "体格", "手部"}
    assert cp.physique_slots("female") == {"体型", "肌肤", "面部", "胸部", "腰腹", "臀部", "四肢"}
    assert cp.custom_fields() == []
    assert cp.slot_annotations() == {}


def test_missing_packs_dir_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(cp, "_packs_dir", lambda: tmp_path / "does_not_exist")
    assert cp.scan_content_packs() == []


def test_fixture_pack_extends_baseline(monkeypatch, tmp_path):
    root = _write_fixture_pack(tmp_path)
    monkeypatch.setattr(cp, "_packs_dir", lambda: root)
    assert cp.get_gender_values() == ["male", "female", "nonbinary"]
    # nonbinary 不是基线性别，没有专属身体基线 → 降级继承 female 的身体槽，
    # 再叠加包追加的"胸部"（已在 female 基线里，并集不变）。
    assert cp.physique_slots("nonbinary") == cp.physique_slots("female")
    assert cp.slot_annotations() == {"胸部": "夹具测试注释"}
    fields = cp.custom_fields()
    assert len(fields) == 1 and fields[0].name == "爱好癖" and fields[0].required


def test_extra_gender_without_own_baseline_inherits_female_body_slots(monkeypatch, tmp_path):
    """回归用例：内容包只追加私处/生殖器类槽（不重定义身体基线）的额外性别
    （如 xeno），不该只剩这两个槽——必须继承 female 的体型/肌肤/面部等身体槽，
    否则 LLM 建人设时没地方写身体特征，只能全塞进生殖器/私处一个字段。"""
    pack_dir = tmp_path / "xeno_like_pack"
    pack_dir.mkdir()
    (pack_dir / "hook.py").write_text(textwrap.dedent('''
        from context.content_packs import ContentPack

        CONTENT_PACK = ContentPack(
            extra_genders=["xeno"],
            extra_physique_slots_by_gender={
                "male": {"生殖器"},
                "female": {"私处"},
                "xeno": {"私处", "生殖器"},
            },
        )
    '''), encoding="utf-8")
    monkeypatch.setattr(cp, "_packs_dir", lambda: tmp_path)
    assert cp.physique_slots("xeno") == cp.physique_slots("female") | {"私处", "生殖器"}


def test_duplicate_custom_field_name_raises(monkeypatch, tmp_path):
    root = tmp_path
    for i in range(2):
        pack_dir = root / f"dup_{i}"
        pack_dir.mkdir()
        (pack_dir / "hook.py").write_text(textwrap.dedent('''
            from context.content_packs import ContentPack, CustomFieldSpec
            CONTENT_PACK = ContentPack(custom_fields=[CustomFieldSpec(name="重名字段")])
        '''), encoding="utf-8")
    monkeypatch.setattr(cp, "_packs_dir", lambda: root)
    with pytest.raises(ValueError, match="重名字段"):
        cp.custom_fields()


def test_baseline_state_derive_fields_without_packs(monkeypatch, tmp_path):
    monkeypatch.setattr(cp, "_packs_dir", lambda: tmp_path / "empty")
    fields = cp.state_derive_fields()
    assert len(fields) == 5
    assert [f.key for f in fields] == ["psychology", "posture", "clothing", "action", "demeanor"]
    assert all(f.kind == "text" for f in fields)


def test_state_derive_fields_pack_override_and_extras(monkeypatch, tmp_path):
    pack_dir = tmp_path / "pack_a"
    pack_dir.mkdir()
    (pack_dir / "hook.py").write_text(textwrap.dedent('''
        from context.content_packs import ContentPack, StateFieldSpec
        CONTENT_PACK = ContentPack(state_fields=[
            StateFieldSpec("demeanor", "神态", "text", "override demeanor hint"),
            StateFieldSpec("extra_field", "额外", "scored_desc", "extra scored_desc hint"),
        ])
    '''), encoding="utf-8")
    monkeypatch.setattr(cp, "_packs_dir", lambda: tmp_path)
    fields = cp.state_derive_fields()
    assert [f.key for f in fields] == [
        "psychology", "posture", "clothing", "action", "demeanor", "extra_field",
    ]
    assert fields[4].derive_hint == "override demeanor hint"
    assert fields[5].kind == "scored_desc"


def test_duplicate_state_derive_field_raises(monkeypatch, tmp_path):
    for i in range(2):
        pack_dir = tmp_path / f"dup_{i}"
        pack_dir.mkdir()
        (pack_dir / "hook.py").write_text(textwrap.dedent('''
            from context.content_packs import ContentPack, StateFieldSpec
            CONTENT_PACK = ContentPack(state_fields=[
                StateFieldSpec("extra_field", "额外", "scored_desc", "hint"),
            ])
        '''), encoding="utf-8")
    monkeypatch.setattr(cp, "_packs_dir", lambda: tmp_path)
    with pytest.raises(ValueError, match="状态推演字段重名"):
        cp.state_derive_fields()


def test_render_custom_fields_block_str_and_list(monkeypatch, tmp_path):
    root = _write_fixture_pack(tmp_path)
    monkeypatch.setattr(cp, "_packs_dir", lambda: root)
    lines = cp.render_custom_fields_block({"爱好癖": "收集邮票"})
    assert lines == ["爱好癖：收集邮票"]
    assert cp.render_custom_fields_block({"爱好癖": ""}) == []
    assert cp.render_custom_fields_block({}) == []


def test_bad_hook_file_is_skipped_not_raised(monkeypatch, tmp_path):
    pack_dir = tmp_path / "broken"
    pack_dir.mkdir()
    (pack_dir / "hook.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    monkeypatch.setattr(cp, "_packs_dir", lambda: tmp_path)
    assert cp.scan_content_packs() == []


def test_active_identity_none_without_packs(monkeypatch, tmp_path):
    monkeypatch.setattr(cp, "_packs_dir", lambda: tmp_path / "empty")
    assert cp.active_identity() is None


def test_active_identity_returns_pack_override(monkeypatch, tmp_path):
    pack_dir = tmp_path / "fixture_pack"
    pack_dir.mkdir()
    (pack_dir / "hook.py").write_text(textwrap.dedent('''
        from context.content_packs import ContentPack

        CONTENT_PACK = ContentPack(identity="SENTINEL身份覆写")
    '''), encoding="utf-8")
    monkeypatch.setattr(cp, "_packs_dir", lambda: pack_dir.parent)
    assert cp.active_identity() == "SENTINEL身份覆写"


def test_contributed_dirs_empty_when_no_packs(monkeypatch, tmp_path):
    monkeypatch.setattr(cp, "_packs_dir", lambda: tmp_path / "empty")
    assert cp.contributed_dirs("setup_chat_skill_dirs") == []


def test_contributed_dirs_returns_absolute_paths(monkeypatch, tmp_path):
    pack_dir = tmp_path / "fixture_pack"
    pack_dir.mkdir()
    (pack_dir / "hook.py").write_text(textwrap.dedent('''
        from context.content_packs import ContentPack

        CONTENT_PACK = ContentPack(
            setup_chat_skill_dirs=["setup_chat_skills/thing-one"],
            detail_skill_dirs=["detail_skills"],
        )
    '''), encoding="utf-8")
    monkeypatch.setattr(cp, "_packs_dir", lambda: tmp_path)
    assert cp.contributed_dirs("setup_chat_skill_dirs") == [
        str(pack_dir / "setup_chat_skills" / "thing-one")
    ]
    assert cp.contributed_dirs("detail_skill_dirs") == [str(pack_dir / "detail_skills")]


def test_active_portrait_directive_none_without_packs(monkeypatch, tmp_path):
    monkeypatch.setattr(cp, "_packs_dir", lambda: tmp_path / "empty")
    assert cp.active_portrait_directive() is None


def test_active_portrait_directive_reads_pack_declaration(monkeypatch, tmp_path):
    pack_dir = tmp_path / "fixture_pack"
    pack_dir.mkdir()
    (pack_dir / "hook.py").write_text(textwrap.dedent('''
        from context.content_packs import ContentPack

        CONTENT_PACK = ContentPack(portrait_prompt_directive="custom portrait directive text")
    '''), encoding="utf-8")
    monkeypatch.setattr(cp, "_packs_dir", lambda: tmp_path)
    assert cp.active_portrait_directive() == "custom portrait directive text"


def test_active_prose_style_extraction_prompt_none_without_packs(monkeypatch, tmp_path):
    monkeypatch.setattr(cp, "_packs_dir", lambda: tmp_path / "empty")
    assert cp.active_prose_style_extraction_prompt() is None


def test_active_prose_style_extraction_prompt_reads_pack_declaration(monkeypatch, tmp_path):
    pack_dir = tmp_path / "fixture_pack"
    pack_dir.mkdir()
    (pack_dir / "hook.py").write_text(textwrap.dedent('''
        from context.content_packs import ContentPack

        CONTENT_PACK = ContentPack(prose_style_extraction_prompt="SENTINEL文风抽取覆写")
    '''), encoding="utf-8")
    monkeypatch.setattr(cp, "_packs_dir", lambda: tmp_path)
    assert cp.active_prose_style_extraction_prompt() == "SENTINEL文风抽取覆写"
