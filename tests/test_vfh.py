"""Tests for VFH+ polar-histogram steering."""

from __future__ import annotations

import pytest

from rover.vfh import VFHConfig, binary_histogram, build_histogram, steer


def _open_sweep(d=None):
    return [(float(b), d) for b in range(-80, 81, 10)]


def test_config_enforces_vfh_plus_cost_condition():
    with pytest.raises(ValueError):
        VFHConfig(mu_target=3.0, mu_current=2.0, mu_previous=2.0)  # 3 !> 4


def test_open_room_steers_toward_goal():
    r = steer(_open_sweep(None), target_bearing_deg=0.0)
    assert not r.blocked
    assert abs(r.chosen_bearing_deg) <= 12  # straight at the goal


def test_open_room_biased_to_offset_goal():
    r = steer(_open_sweep(None), target_bearing_deg=40.0)
    assert not r.blocked
    assert r.chosen_bearing_deg > 12  # leans toward the goal side


def test_wall_dead_ahead_turns_to_a_side():
    # Close obstacle in the centre, open on the wings.
    sweep = []
    for b in range(-80, 81, 10):
        d = 35.0 if abs(b) <= 20 else None
        sweep.append((float(b), d))
    r = steer(sweep, target_bearing_deg=0.0)
    assert not r.blocked
    assert abs(r.chosen_bearing_deg) > 20  # steered out of the blocked centre


def test_fully_blocked_returns_none():
    sweep = [(float(b), 30.0) for b in range(-80, 81, 10)]
    r = steer(sweep)
    assert r.blocked
    assert r.chosen_bearing_deg is None


def test_unscanned_directions_are_treated_as_blocked():
    # Only looked straight ahead (open). Sectors off to the sides were never
    # sampled, so they must not be offered as free gaps.
    r = steer([(0.0, None)], cfg=VFHConfig(), target_bearing_deg=70.0)
    # The only covered+free region is near 0; chosen must be near centre, not 70.
    assert r.chosen_bearing_deg is None or abs(r.chosen_bearing_deg) <= 24


def test_narrow_gap_between_two_obstacles_is_centered():
    # Obstacles only at the far wings (and far enough that width-enlargement
    # leaves a real lane through the middle).
    sweep = []
    for b in range(-80, 81, 10):
        d = 60.0 if abs(b) >= 70 else None
        sweep.append((float(b), d))
    r = steer(sweep, target_bearing_deg=0.0)
    assert not r.blocked
    assert abs(r.chosen_bearing_deg) <= 24


def test_build_histogram_marks_close_obstacle_dense():
    cfg = VFHConfig()
    density, covered = build_histogram([(0.0, 30.0)], cfg)
    # The straight-ahead sector should be both covered and dense (above tau_high).
    mid = len(density) // 2
    assert covered[mid]
    assert max(density) > cfg.tau_high


def test_binary_hysteresis_keeps_previous_in_marginal_band():
    cfg = VFHConfig(tau_low=1.0, tau_high=3.0)
    # Density exactly in the marginal band for one sector.
    density = [2.0]
    covered = [True]
    assert binary_histogram(density, covered, cfg, prev_binary=[0]) == [0]
    assert binary_histogram(density, covered, cfg, prev_binary=[1]) == [1]
    assert binary_histogram(density, covered, cfg, prev_binary=None) == [1]  # cautious


def test_commitment_prefers_previous_choice_among_equal_gaps():
    # Two symmetric open lanes; previous choice on the right should win the tie.
    sweep = []
    for b in range(-80, 81, 10):
        d = 30.0 if abs(b) < 15 else None  # block dead centre, open both sides
        sweep.append((float(b), d))
    left = steer(sweep, target_bearing_deg=0.0, prev_bearing_deg=-60.0)
    right = steer(sweep, target_bearing_deg=0.0, prev_bearing_deg=60.0)
    assert left.chosen_bearing_deg < 0
    assert right.chosen_bearing_deg > 0
