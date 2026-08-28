def test_character_fields_args_includes_custom_fields(monkeypatch):
    import context.content_packs as cp
    import engine.setup_chat.tool_args as ta

    monkeypatch.setattr(
        cp, "custom_fields",
        lambda: [cp.CustomFieldSpec(name="性癖", required=False)],
    )
    Args = ta._build_character_fields_args()
    assert "性癖" in Args.model_fields


def test_character_fields_args_custom_field_uses_pack_description(monkeypatch):
    import context.content_packs as cp
    import engine.setup_chat.tool_args as ta

    monkeypatch.setattr(
        cp, "custom_fields",
        lambda: [cp.CustomFieldSpec(name="性癖", required=True, description="SENTINEL自定义描述")],
    )
    Args = ta._build_character_fields_args()
    assert Args.model_fields["性癖"].description == "SENTINEL自定义描述"


def test_character_fields_args_custom_field_falls_back_to_generic_description(monkeypatch):
    import context.content_packs as cp
    import engine.setup_chat.tool_args as ta

    monkeypatch.setattr(
        cp, "custom_fields",
        lambda: [cp.CustomFieldSpec(name="无描述字段", required=False)],
    )
    Args = ta._build_character_fields_args()
    assert Args.model_fields["无描述字段"].description == "无描述字段（自定义字段，可选）"


def test_character_fields_args_required_custom_field_enforced(monkeypatch):
    import context.content_packs as cp
    import engine.setup_chat.tool_args as ta

    monkeypatch.setattr(
        cp, "custom_fields",
        lambda: [cp.CustomFieldSpec(name="必填癖", required=True)],
    )
    Args = ta._build_character_fields_args()
    assert Args.model_fields["必填癖"].is_required()


def test_gender_physique_description_reflects_content_packs_each_call(monkeypatch):
    """核心回归：本次 bug 的根因是这两个 description 只在进程首次 import 时算过一次；
    这条测试要求同一进程内先后两次调用，拿到不同的结果——而不是像改造前那样永远返回
    import 时刻冻结的同一个字符串。"""
    import context.content_packs as cp
    import engine.setup_chat.tool_args as ta

    monkeypatch.setattr(cp, "get_gender_values", lambda: ["male", "female"])
    monkeypatch.setattr(cp, "physique_slots", lambda g: cp.BASELINE_PHYSIQUE_SLOTS[g])
    baseline_args = ta._build_character_fields_args()
    baseline_gender_desc = baseline_args.model_fields["gender"].description
    baseline_physique_desc = baseline_args.model_fields["physique"].description
    assert "xeno" not in (baseline_gender_desc or "")
    assert "生殖器" not in (baseline_physique_desc or "")

    monkeypatch.setattr(cp, "get_gender_values", lambda: ["male", "female", "xeno"])
    monkeypatch.setattr(
        cp, "physique_slots",
        lambda g: (cp.BASELINE_PHYSIQUE_SLOTS.get(g, frozenset()) | {"生殖器"}) if g != "female"
        else cp.BASELINE_PHYSIQUE_SLOTS["female"] | {"私处"},
    )
    adult_args = ta._build_character_fields_args()
    adult_gender_desc = adult_args.model_fields["gender"].description
    adult_physique_desc = adult_args.model_fields["physique"].description

    assert adult_gender_desc != baseline_gender_desc
    assert "xeno" in (adult_gender_desc or "")
    assert adult_physique_desc != baseline_physique_desc


def test_race_field_description_reflects_world_races_each_call(monkeypatch):
    """Race names come from world_bible, which may be written mid-session (construct_world
    then add_character in AUTO mode) -- description must be rebuilt per call, not frozen."""
    import engine.setup_chat.tool_args as ta

    monkeypatch.setattr(ta, "_race_field_description", lambda: "世界设定未声明种族时留空")
    no_race_args = ta._build_character_fields_args()
    assert "精灵" not in (no_race_args.model_fields["race"].description or "")

    monkeypatch.setattr(
        ta, "_race_field_description",
        lambda: "所属种族（必填），须从世界设定 races 中选一：人族、精灵",
    )
    with_race_args = ta._build_character_fields_args()
    race_desc = with_race_args.model_fields["race"].description or ""
    assert "人族" in race_desc
    assert "精灵" in race_desc


def test_race_field_description_reads_live_world_bible(tmp_path, monkeypatch):
    import json

    import engine.setup_chat.tool_args as ta
    import repositories
    from repo_test_helpers import seed_world

    monkeypatch.setenv("CHRONOS_NOVELS_DIR", str(tmp_path / "novels"))
    monkeypatch.setenv("CHRONOS_ACTIVE_NOVEL", "default")
    (tmp_path / "novels" / "default").mkdir(parents=True, exist_ok=True)
    (tmp_path / "novels" / "active.json").write_text(
        json.dumps({"active": "default"}), encoding="utf-8",
    )
    repositories.drop_repositories("default")
    repositories.reset_repositories()
    seed_world({"races": [{"name": "人族", "desc": "凡躯"}, {"name": "精灵", "desc": "长寿"}]})

    desc = ta._race_field_description()
    assert "人族" in desc
    assert "精灵" in desc


def test_format_race_field_description_with_explicit_names():
    import engine.setup_chat.tool_args as ta

    assert "人族" in ta.format_race_field_description(["人族", "精灵"])
    assert ta.format_race_field_description([]) == "所属种族；世界设定未声明种族时留空"


def test_build_add_character_args_returns_fresh_class_each_call(monkeypatch):
    import engine.setup_chat.tool_args as ta

    a1 = ta.build_add_character_args()
    a2 = ta.build_add_character_args()
    assert a1 is not a2  # 每次现建，不缓存——这正是本次要修的行为
    for name in ("given_name", "role", "gender", "physique", "personality"):
        assert name in a1.model_fields


def test_build_edit_character_args_has_name_field(monkeypatch):
    import engine.setup_chat.tool_args as ta

    Args = ta.build_edit_character_args()
    assert "name" in Args.model_fields
    assert "given_name" in Args.model_fields  # 继承自 CharacterFieldsArgs 基础字段
