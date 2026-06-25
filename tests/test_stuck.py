"""Tests for the stuck-detection escalation ladder."""

from __future__ import annotations

from rover.stuck import escalation_action, stuck_level


def test_stuck_levels_from_worst_signal():
    assert stuck_level(blocked_streak=0) == 0
    assert stuck_level(blocked_streak=2) == 1
    assert stuck_level(blocked_streak=4) == 2
    assert stuck_level(stall_count=6) == 3
    assert stuck_level(blocked_streak=8) == 4
    # Worst-of: any one signal escalates.
    assert stuck_level(blocked_streak=1, stall_count=8, no_progress_cycles=0) == 4


def test_escalation_actions():
    assert escalation_action(0) == "continue"
    assert escalation_action(3) == "reverse"
    assert escalation_action(4) == "give_up_rescue"
    assert escalation_action(99) == "give_up_rescue"
