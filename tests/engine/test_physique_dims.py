"""physique_dims guardrail single test: legal key set (= character base part slot) / delta check."""
from __future__ import annotations

from engine.archive.physique_dims import (
    allowed_physique_keys,
    render_physique_prompt,
    validate_physique_delta,
)

_NARRATIVE_WORDS = ("异化", "器官", "纹样")


def test_allowed_keys_are_base_slots():
    lore_physique = {"chest": "…", "waist": "…", "intimate": "…"}
    assert allowed_physique_keys(lore_physique) == {"chest", "waist", "intimate"}


def test_allowed_keys_handles_none_base():
    assert allowed_physique_keys(None) == set()


def test_validate_drops_unknown_keys_and_warns():
    allowed = {"chest", "intimate"}
    #Fields outside the self-created part slot (such as top-level penis) → discard; alienation should be written into the intimate description
    phys = {"chest": "更新", "intimate": "异化A显形", "penis": "自造字段"}
    clean, warns = validate_physique_delta(phys, allowed)
    assert clean == {"chest": "更新", "intimate": "异化A显形"}
    assert len(warns) == 1 and "penis" in warns[0]


def test_validate_preserves_none_for_allowed_key():
    allowed = {"intimate"}
    clean, warns = validate_physique_delta({"intimate": None}, allowed)
    assert clean == {"intimate": None}
    assert warns == []


def test_validate_empty_allowed_is_passthrough():
    phys = {"任意": "值"}
    clean, warns = validate_physique_delta(phys, set())
    assert clean == phys and warns == []


def test_render_lists_base_slots():
    out = render_physique_prompt({"胸部": "A", "腰腹": "B"}, None)
    assert "- 胸部（" in out and ": A" in out
    assert "- 腰腹（" in out and ": B" in out
    assert "禁止新增槽外的键" in out


def test_render_current_overrides_base():
    out = render_physique_prompt({"胸部": "原描述"}, {"胸部": "改后"})
    assert ": 改后" in out
    assert "- 胸部（" in out


def test_render_falls_back_to_base_when_key_missing_in_current():
    out = render_physique_prompt(
        {"胸部": "A", "腰腹": "B"}, {"胸部": "A2"}
    )
    assert "- 胸部（" in out and ": A2" in out
    assert "- 腰腹（" in out and ": B" in out


def test_render_empty_base_returns_empty():
    assert render_physique_prompt({}, None) == ""
    assert render_physique_prompt(None, None) == ""


def test_render_keys_match_allowed():
    """The rendered set of slot keys (after removing the bracket annotation) should be consistent with allowed_physique_keys."""
    import re
    base = {"chest": "A", "intimate": "B"}
    out = render_physique_prompt(base, None)
    listed = set()
    for line in out.splitlines():
        if line.startswith("- "):
            # "- key（annotation）: value" → extract "key"
            m = re.match(r"- (\w+)", line)
            if m:
                listed.add(m.group(1))
    assert listed == allowed_physique_keys(base)
