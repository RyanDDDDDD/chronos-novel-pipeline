"""cast two rounds of output analysis + skeleton ↔ deep file merge test."""
from engine.setup.cast.parse import merge_cast, parse_round


def test_parse_round_tolerates_fence():
    raw = '```json\n[{"given_name":"甲"}]\n```'
    assert parse_round(raw) == [{"given_name": "甲"}]


def test_merge_pairs_by_given_name():
    sk = [{"given_name": "甲", "role": "甲", "gender": "female",
           "causal_anchors": {"起点": "w", "执念": "n"},
           "relationship_to_lead": "敌"}]
    dd = [{"given_name": "甲", "physique": {"chest": "c"}, "clothing_dna": {"x": 1},
           "sliders": {"投入": 3}}]
    roster = merge_cast(sk, dd)
    assert len(roster) == 1
    c = roster[0]
    assert c["name"] == "甲" and c["given_name"] == "甲"
    assert c["role"] == "甲" and c["causal_anchors"]["起点"] == "w"
    assert c["physique"] == {"chest": "c"}
    assert "relationship_to_lead" not in c  #Generating auxiliary fields does not enter lore


def test_merge_missing_deepdive_keeps_skeleton_only():
    sk = [{"given_name": "乙", "role": "乙", "gender": "male",
           "causal_anchors": {"心结": "d", "渴望": "o"}}]
    roster = merge_cast(sk, [])
    assert roster[0]["name"] == "乙" and "physique" not in roster[0]


def test_merge_skips_nameless():
    sk = [{"role": "甲"}, {"given_name": "丙", "role": "甲"}]
    roster = merge_cast(sk, [])
    assert [c["name"] for c in roster] == ["丙"]
