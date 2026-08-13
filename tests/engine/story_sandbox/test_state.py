from engine.story_sandbox.state import SandboxLiveMode, SandboxStepType, seed_state


def test_event_log_step_type_exists():
    assert SandboxStepType.EVENT_LOG == "event_log"


def test_profile_mutation_step_type_exists():
    assert SandboxStepType.PROFILE_MUTATION == "profile_mutation"


def test_seed_state_includes_empty_character_profile():
    assert seed_state()["character_profile"] == {}


def test_seed_state_includes_empty_recall_cooldown():
    assert seed_state()["recall_cooldown"] == {}


def test_seed_state_includes_empty_active_cast():
    assert seed_state()["active_cast"] == {}


def test_sandbox_live_mode_turn_value():
    assert SandboxLiveMode.TURN == "turn"


def test_sandbox_live_mode_rewrite_value():
    assert SandboxLiveMode.REWRITE == "rewrite"


def test_sandbox_live_mode_has_selection_rewrite_member():
    assert SandboxLiveMode.SELECTION_REWRITE == "selection_rewrite"


def test_seed_state_omits_instruction_this_turn_scratch_field():
    # instruction_this_turn is transient node-to-node scratch, like final_text/baseline_states --
    # never part of the seeded/persisted shape.
    assert "instruction_this_turn" not in seed_state()
