from engine.story_sandbox.cast_tracker import ABSENCE_LIMIT, update_active_cast


def test_absence_limit_is_three():
    assert ABSENCE_LIMIT == 3


def test_new_hit_is_added_with_current_turn_index():
    result = update_active_cast({}, {"甲"}, turn_index=0)
    assert result == {"甲": 0}


def test_existing_member_refreshed_on_repeat_hit():
    result = update_active_cast({"甲": 0}, {"甲"}, turn_index=2)
    assert result == {"甲": 2}


def test_member_survives_up_to_two_turns_of_absence():
    # last seen at turn 0; still present through turn 2 (2 - 0 = 2 < ABSENCE_LIMIT=3)
    result = update_active_cast({"甲": 0}, set(), turn_index=2)
    assert result == {"甲": 0}


def test_member_pruned_at_three_turns_of_absence():
    # last seen at turn 0; turn 3 - 0 = 3, not < ABSENCE_LIMIT=3 -> pruned
    result = update_active_cast({"甲": 0}, set(), turn_index=3)
    assert result == {}


def test_unrelated_members_independently_tracked():
    active = {"甲": 0, "乙": 2}
    result = update_active_cast(active, set(), turn_index=3)
    # 甲 (last seen 0, absent 3 turns) pruned; 乙 (last seen 2, absent 1 turn) survives
    assert result == {"乙": 2}


def test_recomputing_with_same_turn_index_is_idempotent():
    """Rewrite path recomputes against the same turn_index as the original write -- must not
    double-count or behave differently on repeat calls."""
    once = update_active_cast({}, {"甲"}, turn_index=1)
    twice = update_active_cast(once, {"甲"}, turn_index=1)
    assert once == twice == {"甲": 1}
