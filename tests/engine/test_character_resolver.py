"""Role file fold parsing - pure function, does not rely on langgraph."""
from context.character_resolver import fold_delta, resolve_from


def test_scalar_replace():
    out = fold_delta({"gender": "female"}, {"gender": "xeno"})
    assert out["gender"] == "xeno"


def test_fold_address_ref_per_target_merge():
    #Only change the name of A, and B will continue to use it (per-target deep merger)
    acc = {"address_ref": {"甲": ["主人"], "乙": ["姐姐"]}}
    out = fold_delta(acc, {"address_ref": {"甲": ["主上"]}})
    assert out["address_ref"] == {"甲": ["主上"], "乙": ["姐姐"]}


def test_fold_address_ref_null_removes_target():
    #The special name for A disappears → null delete the object entry
    acc = {"address_ref": {"甲": ["主人"], "乙": ["姐姐"]}}
    out = fold_delta(acc, {"address_ref": {"甲": None}})
    assert out["address_ref"] == {"乙": ["姐姐"]}


def test_fold_self_ref_default_and_target():
    #_default baseline + per-target coverage coexistence, merge by object
    acc = {"self_ref": {"_default": ["我"]}}
    out = fold_delta(acc, {"self_ref": {"甲": ["奴婢"]}})
    assert out["self_ref"] == {"_default": ["我"], "甲": ["奴婢"]}


def test_state_replace_sliders_merge():
    #Overall state replacement; sliders deep merge (coaxial coverage)
    out = fold_delta({"state": {"physiology": "p0"}, "sliders": {"resistance": 5}},
                     {"state": {"physiology": "p1"}, "sliders": {"resistance": 2}})
    assert out["state"] == {"physiology": "p1"}
    assert out["sliders"] == {"resistance": 2}


def test_sliders_partial_delta_keeps_other_axis():
    #Only update the delta of addiction and do not erase the existing resistance (claims/wording, etc. all depend on resistance)
    out = fold_delta({"sliders": {"resistance": 0, "addiction": 3}},
                     {"sliders": {"addiction": 5}})
    assert out["sliders"] == {"resistance": 0, "addiction": 5}


def test_sliders_none_does_not_wipe():
    #None (parsing failure) should be ignored and retained, rather than erased (unlike physique's None=remove)
    out = fold_delta({"sliders": {"resistance": 0, "addiction": 3}},
                     {"sliders": {"resistance": None, "addiction": 5}})
    assert out["sliders"] == {"resistance": 0, "addiction": 5}


def test_physique_deep_merge_add():
    out = fold_delta({"physique": {"chest": "单薄", "intimate": "淡雅"}},
                     {"physique": {"custom_slot": "异化异化A"}})
    assert out["physique"]["chest"] == "单薄"
    assert out["physique"]["custom_slot"] == "异化异化A"


def test_physique_null_removes_subfield():
    out = fold_delta({"physique": {"chest": "单薄", "custom_slot": "异化异化A"}},
                     {"physique": {"custom_slot": None}})
    assert "custom_slot" not in out["physique"]
    assert out["physique"]["chest"] == "单薄"


def test_resolve_from_accumulates_with_rollback():
    lore = {"name": "女主丙", "gender": "female",
            "physique": {"chest": "单薄"}, "self_ref": "我"}
    deltas = [
        {"chapter": 6, "stage": 1, "delta": {"sliders": {"resistance": 4}}},
        {"chapter": 6, "stage": 2, "delta": {
            "gender": "xeno",
            "physique": {"genital": "异化A", "face": "异化A区域"},
            "self_ref": "占位自称"}},
        {"chapter": 7, "stage": 1, "delta": {
            "gender": "female", "physique": {"genital": None}}},
    ]
    s62 = resolve_from(lore, deltas, 6, 2)
    assert s62["gender"] == "xeno"
    assert s62["physique"]["genital"] == "异化A"
    assert s62["physique"]["face"] == "异化A区域"
    assert s62["self_ref"] == "占位自称"
    s71 = resolve_from(lore, deltas, 7, 1)
    assert s71["gender"] == "female"
    assert "genital" not in s71["physique"]
    assert s71["physique"]["face"] == "异化A区域"
    assert s71["physique"]["chest"] == "单薄"


def test_resolve_idempotent():
    lore = {"name": "A", "gender": "female", "physique": {"x": "1"}}
    deltas = [{"chapter": 6, "stage": 1, "delta": {"gender": "xeno"}}]
    assert resolve_from(lore, deltas, 6, 1) == resolve_from(lore, deltas, 6, 1)


def test_resolve_no_delta_returns_lore_copy():
    lore = {"name": "A", "gender": "female"}
    out = resolve_from(lore, [], 6, 1)
    assert out["gender"] == "female"
    out["gender"] = "xeno"
    assert lore["gender"] == "female"


def test_fold_replace_scalar_and_deep_remove_none():
    acc = {"gender": "female", "physique": {"a": 1, "b": 2}}
    out = fold_delta(acc, {"gender": "xeno", "physique": {"b": None, "c": 3}})
    assert out["gender"] == "xeno"
    assert out["physique"] == {"a": 1, "c": 3}   #b is deleted by None
    assert acc["physique"] == {"a": 1, "b": 2}   #Input parameters remain unchanged


def test_resolve_from_accumulates_in_order():
    lore = {"x": 0}
    snaps = [
        {"chapter": 1, "stage": 2, "delta": {"x": 2}},
        {"chapter": 1, "stage": 1, "delta": {"x": 1}},
    ]
    assert resolve_from(lore, snaps, 1, 1)["x"] == 1   #Only to (1,1)
    assert resolve_from(lore, snaps, 1, 2)["x"] == 2   #Accumulates to (1,2)


def test_resolve_from_falls_back_to_lore_sliders_when_no_delta_touches_axis():
    #Lore's own sliders baseline (formerly the separately-named sliders_init) seeds the same
    #deep_ignore_none fold as every stage delta -- an axis no delta ever touches should still
    #resolve to the lore starting value, not disappear.
    lore = {"sliders": {"侵蚀度": {"level": 1, "text": "初动摇"}, "警惕度": {"level": 3, "text": "戒备"}}}
    snapshots = [{
        "chapter": 1, "stage": 1,
        "delta": {"sliders": {"侵蚀度": {"level": 2, "text": "加深"}}},  #只碰"侵蚀度"这一轴
    }]
    resolved = resolve_from(lore, snapshots, chapter=1, stage=1)
    assert resolved["sliders"]["侵蚀度"] == {"level": 2, "text": "加深"}  #被 delta 覆盖
    assert resolved["sliders"]["警惕度"] == {"level": 3, "text": "戒备"}  #沿用 lore 起点，未丢失

