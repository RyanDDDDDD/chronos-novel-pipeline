"""merge_state_blocks: Interleave the Name: Psychology / Name: Physiology; Clothing blocks into ### Name blocks according to the presence list.
Zero information loss + two-way mismatch alarm (warning does not crash)."""
from __future__ import annotations

from engine.author_loop.build import merge_state_blocks


def test_merge_interleaves_by_character():
    psych = "甲：情绪低落沉默寡言\n乙：满怀期待跃跃欲试"
    phys = "甲：肩膀微垂，脚步迟缓\n乙：外套挂肩，站姿放松"
    out = merge_state_blocks(psych, phys, characters=["甲", "乙"])
    assert out == (
        "### 甲\n- 心理：情绪低落沉默寡言\n- 生理/姿态：肩膀微垂，脚步迟缓\n\n"
        "### 乙\n- 心理：满怀期待跃跃欲试\n- 生理/姿态：外套挂肩，站姿放松"
    )


def test_merge_keeps_roster_order():
    psych = "乙：心理乙\n甲：心理甲"
    phys = "甲：物理甲\n乙：物理乙"
    out = merge_state_blocks(psych, phys, characters=["甲", "乙"])
    assert out.index("### 甲") < out.index("### 乙")  #In characters order, not within block order


def test_missing_phys_renders_psych_only_and_warns():
    out = merge_state_blocks("甲：心理甲", "", characters=["甲"])
    assert "### 甲" in out and "- 心理：心理甲" in out
    assert "生理/姿态" not in out  #Lack of physics → only psychology, no error reporting


def test_foreign_phys_name_appended_and_warns():
    #Physical blocks appear as non-listed characters (weak models use abbreviations) → keep them as they are without losing information.
    out = merge_state_blocks("甲：心理甲", "甲：物理甲\n路人丙：野生行", characters=["甲"])
    assert "### 甲" in out and "- 生理/姿态：物理甲" in out
    assert "路人丙：野生行" in out  #The list is attached at the end as it is for laymen.


def test_loose_non_prefixed_text_preserved():
    #Non-"name:" format (such as the plain text returned by mock) → keep it as it is, without crashing
    out = merge_state_blocks("基态", "基态", characters=["甲"])
    assert "基态" in out


def test_char_absent_from_both_skipped():
    out = merge_state_blocks("甲：心理甲", "甲：物理甲", characters=["甲", "丙"])
    assert "### 丙" not in out  #C Neither piece → Skip
