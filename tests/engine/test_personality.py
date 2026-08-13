from context.personality import resolved_personality


def test_resolved_personality_prefers_personality_field():
    assert resolved_personality({"personality": "外冷内热"}) == "外冷内热"


def test_resolved_personality_empty_when_missing():
    assert resolved_personality({}) == ""


def test_resolved_personality_ignores_legacy_archetype_key():
    assert resolved_personality({"archetype": "沉稳内敛型"}) == ""
