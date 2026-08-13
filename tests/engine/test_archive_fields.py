from engine.archive.archive_fields import _STAGE_BOUND_FIELDS, expected_archive_fields


def test_includes_lore_fields_minus_stage_bound_plus_extensions_stages():
    lore_index = {
        "甲": {"name": "甲", "role": "female", "physique": {"x": 1}, "personality": "p",
               "clothing": "裙", "causal_anchors": {}},
        "乙": {"name": "乙", "role": "male", "gender": "male"},
    }
    fields = expected_archive_fields(lore_index)
    assert {"name", "role", "causal_anchors"} <= fields
    assert {"extensions", "stages"} <= fields
    assert not (_STAGE_BOUND_FIELDS & fields)
    assert "personality" not in fields


def test_empty_lore_still_has_extensions_and_stages():
    assert expected_archive_fields({}) == {"extensions", "stages"}


def test_race_and_identity_background_are_stage_bound():
    lore_index = {
        "甲": {"name": "甲", "role": "female", "race": "人类",
               "identity_background": "普通学生", "causal_anchors": {}},
    }
    fields = expected_archive_fields(lore_index)
    assert "race" not in fields
    assert "identity_background" not in fields
    assert {"race", "identity_background"} <= _STAGE_BOUND_FIELDS
