"""prompt requires ↔ hook.injects contract lint."""
from engine.validator.agent_package_check import (
    check_injects_contract,
    collect_injects_violations,
    parse_prompt_requires,
)
from utils.paths import AGENTS_DIR


def test_parse_requires_extracts_comment_block():
    md = (
        "# 台词锚定师\n"
        "<!-- requires: state.psychology, phase, dialogue_scaffolding -->\n"
        "## 输入\n..."
    )
    assert parse_prompt_requires(md) == [
        "state.psychology",
        "phase",
        "dialogue_scaffolding",
    ]


def test_parse_requires_absent_returns_empty():
    assert parse_prompt_requires("# 无 requires 的 prompt\n正文") == []


def test_check_contract_ok_when_subset():
    errs = check_injects_contract(
        agent="dialogue_anchor",
        injects=[
            "name",
            "phase",
            "state.psychology",
            "state.physiology",
            "dialogue_scaffolding",
        ],
        requires=["state.psychology", "phase"],
    )
    assert errs == []


def test_check_contract_flags_missing_injection():
    errs = check_injects_contract(
        agent="dialogue_anchor",
        injects=["name", "phase"],
        requires=["state.psychology"],
    )
    assert errs and "state.psychology" in errs[0]


def test_check_contract_empty_requires_always_ok():
    errs = check_injects_contract(agent="x", injects=[], requires=[])
    assert errs == []


def test_real_agents_no_contract_violation():
    assert collect_injects_violations(AGENTS_DIR) == [], (
        "存在 prompt↔hook 注入契约违规"
    )
