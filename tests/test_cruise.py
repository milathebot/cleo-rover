"""Tests for the continuous-cruise speed cap + pure steering policy."""

from __future__ import annotations

from rover.cruise import (
    ACTION_DRIVE,
    ACTION_STOP,
    CruiseParams,
    cruise_speed_cap,
    cruise_speed_cap_cm_s,
    steer_to_command,
    t_forward_s,
)

P = CruiseParams()


def test_speed_cap_respects_braking_inequality():
    # v*(T_forward + T_react) + coast + margin <= reflex_hard_cm must hold.
    v_cm_s = cruise_speed_cap_cm_s(P)
    lhs = v_cm_s * (t_forward_s(P) + P.react_ms / 1000.0) + P.coast_cm + P.margin_cm
    assert lhs <= P.reflex_hard_cm + 1e-6


def test_speed_cap_never_exceeds_configured_max():
    cap = cruise_speed_cap(P)
    assert cap <= P.max_linear + 1e-9
    # A very generous braking budget still clamps to max_linear.
    roomy = CruiseParams(reflex_hard_cm=200.0, coast_cm=0.0, margin_cm=0.0, max_linear=0.20)
    assert cruise_speed_cap(roomy) == 0.20


def test_tighter_reflex_floor_lowers_cap():
    tight = CruiseParams(reflex_hard_cm=15.0)
    roomy = CruiseParams(reflex_hard_cm=40.0)
    assert cruise_speed_cap_cm_s(tight) < cruise_speed_cap_cm_s(roomy)


def _drive(**kw):
    base = dict(
        chosen_bearing_deg=0.0, blocked=False, fwd_min_cm=150.0, fwd_worst_age_ms=100.0,
        grant_active=True, pan_deg=0.0, params=P, cornered_streak=0,
    )
    base.update(kw)
    return steer_to_command(**base)


def test_clear_path_drives_at_cap():
    d = _drive()
    assert d.action == ACTION_DRIVE
    assert d.linear == round(cruise_speed_cap(P), 3)
    assert d.stop is False


def test_no_grant_stops():
    assert _drive(grant_active=False).stop is True


def test_panned_turret_stops_even_if_clear():
    d = _drive(pan_deg=40.0, fwd_min_cm=300.0)
    assert d.stop is True
    assert "panned" in d.reason


def test_stale_forward_stops():
    d = _drive(fwd_worst_age_ms=5000.0)
    assert d.stop is True
    assert "stale" in d.reason


def test_cornered_needs_confirmation_then_stops():
    d1 = _drive(blocked=True, chosen_bearing_deg=None, cornered_streak=0)
    assert d1.stop is True and d1.cornered is False  # first blocked read: confirming
    d2 = _drive(blocked=True, chosen_bearing_deg=None, cornered_streak=1)
    assert d2.stop is True and d2.cornered is True   # confirmed -> cornered


def test_speed_ramps_down_near_obstacle():
    far = _drive(fwd_min_cm=150.0).linear
    near = _drive(fwd_min_cm=40.0).linear  # between reflex floor (30) and slowdown (60)
    at_floor = _drive(fwd_min_cm=30.0).linear
    assert near < far
    assert at_floor == 0.0


def test_never_emits_above_cap():
    cap = cruise_speed_cap(P)
    for fwd in (35.0, 50.0, 80.0, 200.0):
        assert _drive(fwd_min_cm=fwd).linear <= cap + 1e-9


def test_flow_looming_halves_speed():
    base = _drive(fwd_min_cm=150.0).linear
    loom = _drive(fwd_min_cm=150.0, flow_ttc_frames=5.0).linear
    assert loom < base


def test_turn_follows_chosen_bearing_and_clamps():
    left = _drive(chosen_bearing_deg=60.0)
    right = _drive(chosen_bearing_deg=-60.0)
    assert left.turn > 0 and right.turn < 0
    assert abs(left.turn) <= P.max_turn + 1e-9
