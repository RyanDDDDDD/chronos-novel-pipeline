"""cast sets up the built-in test: two rounds of ROUND analysis + prompt resource loading."""
from engine.setup.cast import questions


def test_two_rounds():
    r0 = questions.build_round(0, None)
    r1 = questions.build_round(1, {"summary": "选了甲乙"})
    assert r0 is not None and r1 is not None
    assert questions.build_round(2, None) is None  #only two rounds
    assert "选了甲乙" in r1["content"]  #prev_sel injection


def test_system_loadable():
    assert questions.load_system_prompt().strip()
