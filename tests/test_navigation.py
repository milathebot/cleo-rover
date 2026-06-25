"""Unit tests for the pure doorway/hallway decision logic (rover/navigation.py).

These are the regression guards for the "turns randomly ~20cm before a doorway"
bug. They assert the band/hysteresis/scan-center behavior directly, with no
hardware, async, or HTTP in the way.
"""

from __future__ import annotations

import pytest

from rover.navigation import (
    ACTION_ADVANCE,
    ACTION_ALIGN_TURN,
    ACTION_CREEP,
    ACTION_EMERGENCY_ESCAPE,
    ACTION_HOLD,
    ACTION_SCAN_TURN,
    DoorwayBands,
    decide_hallway_action,
)

BANDS = DoorwayBands(emergency_cm=25.0, blocked_cm=42.0, clear_cm=75.0, reflex_hard_cm=30.0)


def decide(**overrides):
    kwargs = dict(
        raw_front_cm=100.0,
        scan_center_cm=100.0,
        best_bearing_deg=None,
        best_distance_cm=None,
        fresh_reflex=False,
        blocked_streak=0,
        clear_streak=0,
        bands=BANDS,
        side_gain_cm=25.0,
        confirm_blocked=2,
        confirm_clear=2,
        creep_step_cm=3.0,
    )
    kwargs.update(overrides)
    return decide_hallway_action(**kwargs)


def test_clear_path_advances():
    d = decide(raw_front_cm=120.0, scan_center_cm=120.0)
    assert d.action == ACTION_ADVANCE
    assert d.decision_front_cm == 120.0
    assert d.blocked_streak == 0


def test_scan_center_clear_overrides_noisy_raw_front():
    # The classic D2 bug: a single below-clear raw front used to veto a clear
    # centered scan. Raw 44cm (above the hard floor) must NOT block when the
    # fresh centered scan shows 86cm of open doorway ahead.
    d = decide(raw_front_cm=44.0, scan_center_cm=86.0)
    assert d.action == ACTION_ADVANCE
    assert d.decision_front_cm == 86.0


def test_creep_band_threads_doorway_no_dead_zone():
    # 50cm centered is inside the creep band (42..75). Old code (blocked 55, creep
    # only above blocked+10) would scan-turn here; now Pip creeps straight through.
    d = decide(raw_front_cm=50.0, scan_center_cm=50.0)
    assert d.action == ACTION_CREEP
    assert d.planned_step_cm == 3.0
    assert d.phase == "creep"
    assert d.blocked_streak == 0


def test_blocked_requires_two_fresh_reads_before_turning():
    # First blocked read holds (hysteresis), does not turn.
    first = decide(scan_center_cm=35.0, raw_front_cm=35.0, blocked_streak=0)
    assert first.action == ACTION_HOLD
    assert first.blocked_streak == 1
    # Second consecutive blocked read crosses confirm_blocked -> recovery turn.
    second = decide(scan_center_cm=35.0, raw_front_cm=35.0, blocked_streak=first.blocked_streak)
    assert second.action == ACTION_SCAN_TURN
    assert second.blocked_streak == 2


def test_blocked_with_clearly_better_side_turns_immediately():
    d = decide(scan_center_cm=35.0, raw_front_cm=35.0, blocked_streak=0, best_bearing_deg=40.0, best_distance_cm=120.0)
    assert d.action == ACTION_SCAN_TURN  # better side bypasses the hold


def test_emergency_on_low_decision_distance():
    d = decide(scan_center_cm=18.0, raw_front_cm=18.0)
    assert d.action == ACTION_EMERGENCY_ESCAPE


def test_raw_front_inside_hard_floor_is_emergency_even_if_scan_clear():
    d = decide(raw_front_cm=20.0, scan_center_cm=100.0)
    assert d.action == ACTION_EMERGENCY_ESCAPE


def test_fresh_reflex_forces_emergency_even_when_open():
    d = decide(raw_front_cm=100.0, scan_center_cm=100.0, fresh_reflex=True)
    assert d.action == ACTION_EMERGENCY_ESCAPE
    assert d.blocked_streak == 1


def test_clear_but_much_better_side_aligns():
    d = decide(raw_front_cm=80.0, scan_center_cm=80.0, best_bearing_deg=45.0, best_distance_cm=130.0)
    assert d.action == ACTION_ALIGN_TURN


def test_unknown_range_scans_and_counts_blocked():
    d = decide(raw_front_cm=None, scan_center_cm=None)
    assert d.action == ACTION_SCAN_TURN
    assert d.decision_front_cm is None
    assert d.blocked_streak == 1


def test_consecutive_clear_marks_exit_phase():
    d = decide(scan_center_cm=120.0, clear_streak=1, confirm_clear=2)
    assert d.action == ACTION_ADVANCE
    assert d.clear_streak == 2
    assert d.phase == "exit"


def test_doorway_bands_reject_inverted_order():
    import pytest as _pytest
    from rover.navigation import DoorwayBands
    with _pytest.raises(ValueError):
        DoorwayBands(emergency_cm=60.0, blocked_cm=30.0, clear_cm=35.0, reflex_hard_cm=30.0)


def test_hallway_command_rejects_inverted_bands():
    import pytest as _pytest
    from rover.models import HallwayScoutCommand
    with _pytest.raises(Exception):
        HallwayScoutCommand(emergency_cm=60.0, blocked_cm=30.0, clear_cm=35.0)
    # sane ordering is accepted
    HallwayScoutCommand(emergency_cm=25.0, blocked_cm=42.0, clear_cm=75.0)
