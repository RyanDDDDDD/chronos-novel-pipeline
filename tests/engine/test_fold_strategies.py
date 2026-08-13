from context.character_resolver import fold_delta


def test_default_strategies_match_legacy():
    #sliders: None ignore retention
    acc = {"sliders": {"resistance": 80, "addiction": 10}}
    out = fold_delta(acc, {"sliders": {"addiction": 30, "resistance": None}})
    assert out["sliders"] == {"resistance": 80, "addiction": 30}
    #physique: None remove subfields
    acc = {"physique": {"breast": "A", "womb": "x"}}
    out = fold_delta(acc, {"physique": {"womb": None, "hip": "y"}})
    assert out["physique"] == {"breast": "A", "hip": "y"}
    #Scalar global replacement
    assert fold_delta({"gender": "female"}, {"gender": "xeno"})["gender"] == "xeno"


def test_explicit_strategies_override():
    #Explicitly mark foo as deep_ignore_none
    acc = {"foo": {"a": 1}}
    out = fold_delta(acc, {"foo": {"b": 2, "a": None}}, strategies={"foo": "deep_ignore_none"})
    assert out["foo"] == {"a": 1, "b": 2}
