"""cast validator test: schema completeness + physique part slot legality + group image structure diversity."""
import pytest
from engine.setup.cast.cast_validator import (
    collect_character_field_errors,
    race_mismatch_advisory,
    validate_character,
    validate_character_edit,
    validate_roster,
)


@pytest.fixture(autouse=True)
def _no_world_races(monkeypatch):
    """Isolated environment world_bible: By default, the test novel has no race (race verification is skipped); the use case for testing race is set by yourself."""
    from engine.setup.cast import cast_validator as cv
    monkeypatch.setattr(cv, "_load_world_race_names", lambda: [], raising=False)


@pytest.fixture(autouse=True)
def _neutral_baseline_custom_fields(monkeypatch):
    import context.content_packs as cp

    monkeypatch.setattr(
        cp,
        "custom_fields",
        lambda: [
            cp.CustomFieldSpec(name="武器", required=True),
            cp.CustomFieldSpec(name="流派", required=True),
            cp.CustomFieldSpec(name="身份", required=True),
        ],
    )

def _base_sliders_ok() -> dict:
    return {
        "投入": {
            "level": 1,
            "text": "登场时略有保留的具体描述",
            "levels": {"0": "克制", "1": "略有保留", "2": "全情投入"},
        }
    }


def test_sliders_levels_missing_is_tolerated_for_legacy_shape():
    errs = collect_character_field_errors(
        name="角色甲", role="某类角色", gender="female",
        causal_anchors={"执念": "一句描述"}, physique={}, sliders={"投入": {"level": 1, "text": "x"}},
    )
    assert not any("levels" in e for e in errs)


def test_sliders_levels_wrong_keys_rejected():
    bad = _base_sliders_ok()
    bad["投入"]["levels"] = {"0": "克制", "1": "略有保留"}
    errs = collect_character_field_errors(
        name="角色甲", role="某类角色", gender="female",
        causal_anchors={"执念": "一句描述"}, physique={}, sliders=bad,
    )
    assert any("levels" in e for e in errs)


def test_sliders_level_out_of_own_levels_range_rejected():
    bad = _base_sliders_ok()
    bad["投入"]["level"] = 9
    errs = collect_character_field_errors(
        name="角色甲", role="某类角色", gender="female",
        causal_anchors={"执念": "一句描述"}, physique={}, sliders=bad,
    )
    assert any("level=9" in e for e in errs)


def test_sliders_level_within_own_levels_range_ok():
    errs = collect_character_field_errors(
        name="角色甲", role="某类角色", gender="female",
        causal_anchors={"执念": "一句描述"}, physique={}, sliders=_base_sliders_ok(),
    )
    assert not any("level=" in e for e in errs)


def test_role_no_longer_cross_checked_against_any_schema():
    errs = collect_character_field_errors(
        name="角色甲", role="随便起的新标签", gender="female",
        causal_anchors={"执念": "一句描述"}, physique={}, sliders=_base_sliders_ok(),
    )
    assert not any("不在 character_schema" in e or "role" in e.lower() for e in errs)


def _female():
    from engine.setup.cast.stance_schema import physique_slots
    return {
        "name": "A", "given_name": "A", "role": "甲", "gender": "female",
        "clothing_dna": {"color_palette": ["白"], "materials_preference": ["棉"],
                         "signature_outfit": "测试招牌常服", "accessories": ["测试配饰"]},
        "causal_anchors": {"起点": "...", "执念": "..."},
        "sliders": {"投入": 1},
        "physique": {k: "x" for k in physique_slots("female")},
        "personality": "尚待观察",
        "identity_background": "出身平平",
        "武器": "尚待观察",
        "流派": "尚待观察",
        "身份": "尚待观察",
    }


def _male():
    from engine.setup.cast.stance_schema import physique_slots
    return {
        "name": "B", "given_name": "B", "role": "乙", "gender": "male",
        "clothing_dna": {"color_palette": ["黑"], "materials_preference": ["铁"],
                         "signature_outfit": "测试招牌常服", "accessories": []},
        "causal_anchors": {"心结": "...", "渴望": "..."},
        "sliders": {"羁绊": 1},
        "physique": {k: "x" for k in physique_slots("male")},
        "personality": "尚待观察",
        "identity_background": "出身平平",
        "武器": "尚待观察",
        "流派": "尚待观察",
        "身份": "尚待观察",
    }


def test_validate_uses_dynamic_schema():
    assert validate_character(_female()) == []


def test_valid_female_passes():
    assert validate_character(_female()) == []


def test_valid_male_passes():
    assert validate_character(_male()) == []


def test_edit_validation_ignores_other_stale_characters():
    """
Single character editing only verifies the uniqueness of the changed character + name; other character formats should not be hindered by outdated formats (deadlock breaking)."""
    good = _female()
    stale = {"name": "旧", "given_name": "旧", "role": "submissive",  #Old format (illegal role)
             "gender": "female", "physique": {"chest": "x"}}  #old english key
    roster = [good, stale]
    #Full verification will report an error due to stale; single character verification only looks at good → passed
    assert validate_roster(roster) != []
    assert validate_character_edit(good, roster) == []


def test_edit_validation_flags_edited_char_own_errors():
    bad = _female()
    bad["physique"] = {"chest": "x"}  #The format of the character being changed is wrong → still needs to be reported
    assert validate_character_edit(bad, [bad]) != []


def test_edit_validation_flags_name_dup():
    a = _female()
    dup = _female()  #Name A
    errs = validate_character_edit(a, [a, dup])
    assert any("重复" in e for e in errs)


def test_causal_anchors_free_per_character():
    """The causal anchor is the role's personal setting, and the dimension name is not subject to the role schema - self-made dimensions are still legal."""
    c = _female()
    c["causal_anchors"] = {"专属创伤": "童年的某段经历", "私人执念": "对某物的渴求"}
    assert validate_character(c) == []


def test_empty_causal_value_flagged():
    """
Structural requirements: The description of each dimension name→description cannot be empty."""
    c = _female()
    c["causal_anchors"] = {"维度甲": "有内容", "维度乙": ""}
    assert any("causal_anchors" in e for e in validate_character(c))


def test_missing_physique_base_key_flagged():
    c = _female()
    del c["physique"]["胸部"]
    assert any("胸部" in e for e in validate_character(c))


def test_unknown_physique_key_flagged():
    c = _female()
    c["physique"]["bogus"] = "x"
    assert any("bogus" in e for e in validate_character(c))


def test_roster_duplicate_name_flagged():
    errs = validate_roster([_female(), _female()])
    assert any("重复" in e for e in errs)


def _race_char(race):
    from engine.setup.cast.stance_schema import physique_slots
    return {
        "name": "R", "given_name": "R", "role": "甲", "gender": "female",
        "clothing_dna": {"color_palette": ["黑"], "materials_preference": ["丝"],
                         "signature_outfit": "测试招牌常服", "accessories": []},
        "causal_anchors": {"执念": "x"}, "sliders": {"投入": 0},
        "physique": {k: "x" for k in physique_slots("female")}, "race": race,
        "personality": "尚待观察",
        "identity_background": "出身平平",
        "武器": "尚待观察",
        "流派": "尚待观察",
        "身份": "尚待观察",
    }


def test_race_existence_required_when_world_has_races(monkeypatch):
    from engine.setup.cast import cast_validator as cv
    monkeypatch.setattr(cv, "_load_world_race_names", lambda: ["精灵", "兽人"], raising=False)
    errs = validate_character(_race_char(""))  #Lack of race
    assert any("缺 race" in e for e in errs)


def test_race_invalid_flagged(monkeypatch):
    from engine.setup.cast import cast_validator as cv
    monkeypatch.setattr(cv, "_load_world_race_names", lambda: ["精灵", "兽人"], raising=False)
    errs = validate_character(_race_char("龙族"))  #Not in the world race
    assert any("不在世界设定种族" in e and "精灵" in e for e in errs)


def test_race_valid_passes_casefold(monkeypatch):
    from engine.setup.cast import cast_validator as cv
    monkeypatch.setattr(cv, "_load_world_race_names", lambda: ["精灵", "Orc"], raising=False)
    assert validate_character(_race_char(" orc ")) == []  #strip+casefold hit


def test_sliders_legacy_string_shape_tolerated():
    """存量小说的 sliders 仍是裸值（非 dict）——不因格式漂移报错，交下次 edit_character 自然升级。"""
    c = _female()
    c["sliders"] = {"投入": "登场时尚有保留"}
    assert validate_character(c) == []


def test_sliders_new_shape_out_of_range_level_flagged():
    c = _female()
    c["sliders"] = {
        "投入": {
            "level": 99,
            "text": "登场时尚有保留",
            "levels": {"0": "a", "1": "b", "2": "c"},
        }
    }
    errs = validate_character(c)
    assert any("不在合法档位" in e for e in errs)


def test_sliders_new_shape_valid_level_passes():
    c = _female()
    c["sliders"] = {
        "投入": {
            "level": 0,
            "text": "登场时尚有保留",
            "levels": {"0": "a", "1": "b", "2": "c"},
        }
    }
    assert validate_character(c) == []


def test_sliders_new_shape_missing_text_flagged():
    c = _female()
    c["sliders"] = {"投入": {"level": 0, "text": ""}}
    errs = validate_character(c)
    assert any("level:int, text:非空str" in e for e in errs)


def test_race_skipped_when_world_has_no_races(monkeypatch):
    from engine.setup.cast import cast_validator as cv
    monkeypatch.setattr(cv, "_load_world_race_names", lambda: [], raising=False)
    assert validate_character(_race_char("")) == []  #No race → no forced race


def test_collect_field_errors_mismatch_ignored_when_not_strict():
    errs = collect_character_field_errors(
        name="角色甲", role="某类角色", gender="female",
        causal_anchors={"执念": "一句描述"}, physique={}, sliders=_base_sliders_ok(),
        race="不存在的种族", world_races=["精灵族", "人类"],
        strict_race_membership=False,
    )
    assert not any("race" in e.lower() or "种族" in e for e in errs)


def test_collect_field_errors_empty_race_still_hard_when_not_strict():
    errs = collect_character_field_errors(
        name="角色甲", role="某类角色", gender="female",
        causal_anchors={"执念": "一句描述"}, physique={}, sliders=_base_sliders_ok(),
        race="", world_races=["精灵族", "人类"],
        strict_race_membership=False,
    )
    assert any("缺 race" in e for e in errs)


def test_collect_field_errors_mismatch_still_hard_by_default():
    errs = collect_character_field_errors(
        name="角色甲", role="某类角色", gender="female",
        causal_anchors={"执念": "一句描述"}, physique={}, sliders=_base_sliders_ok(),
        race="不存在的种族", world_races=["精灵族", "人类"],
    )
    assert any("不在世界设定种族" in e and "不存在的种族" in e for e in errs)


def test_race_mismatch_advisory_empty_world(monkeypatch):
    from engine.setup.cast import cast_validator as cv
    monkeypatch.setattr(cv, "_load_world_race_names", lambda: [], raising=False)
    assert race_mismatch_advisory(_race_char("龙族")) == ""


def test_race_mismatch_advisory_match_casefold(monkeypatch):
    from engine.setup.cast import cast_validator as cv
    monkeypatch.setattr(cv, "_load_world_race_names", lambda: ["精灵", "Orc"], raising=False)
    assert race_mismatch_advisory(_race_char(" orc ")) == ""


def test_race_mismatch_advisory_empty_race(monkeypatch):
    from engine.setup.cast import cast_validator as cv
    monkeypatch.setattr(cv, "_load_world_race_names", lambda: ["精灵族", "人类"], raising=False)
    assert race_mismatch_advisory(_race_char("")) == ""


def test_race_mismatch_advisory_mismatch(monkeypatch):
    from engine.setup.cast import cast_validator as cv
    monkeypatch.setattr(cv, "_load_world_race_names", lambda: ["精灵族", "人类"], raising=False)
    text = race_mismatch_advisory(_race_char("龙族"))
    assert text
    assert "R" in text
    assert "龙族" in text
    assert "精灵族" in text or "人类" in text


def test_gender_validity_reflects_content_packs(monkeypatch):
    """_ALLOWED_GENDERS 不再是写死的三态，而是当前激活内容包的合并结果。"""
    from engine.setup.cast import cast_validator as cv
    import context.content_packs as cp

    monkeypatch.setattr(cp, "get_gender_values", lambda: ["male", "female"])
    errs = cv.collect_character_field_errors(
        name="X", role="甲", gender="xeno", causal_anchors={"起点": "x", "执念": "x"},
        physique={}, sliders={"投入": 0},
        clothing_dna={"color_palette": ["黑"], "materials_preference": ["棉"],
                      "signature_outfit": "测试招牌常服", "accessories": []},
    )
    assert any("gender 须为" in e for e in errs)


def test_required_fields_extended_by_content_pack_custom_fields(monkeypatch):
    from engine.setup.cast import cast_validator as cv
    import context.content_packs as cp

    monkeypatch.setattr(
        cp, "custom_fields",
        lambda: [cp.CustomFieldSpec(name="武器", required=True)],
    )
    c = _female()
    del c["武器"]  #不带"武器"字段 → 应报缺必填
    errs = cv.validate_character(c)
    assert any("武器" in e for e in errs)
    c["武器"] = "长枪"
    assert cv.validate_character(c) == []


def test_validate_character_requires_identity_background():
    char = _female()
    del char["identity_background"]
    errs = validate_character(char)
    assert any("identity_background" in e for e in errs)


def test_validate_character_passes_with_identity_background():
    assert validate_character(_female()) == []
