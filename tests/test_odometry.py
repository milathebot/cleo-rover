"""Tests for the open-loop motion model and honest distance estimation."""

from __future__ import annotations

import pytest

from rover.odometry import MotionModel, PoseEstimate, estimate_chunk_distance_cm, motion_model_from
from rover.config import OdometryConfig

MODEL = MotionModel()


def test_duration_for_cm_is_clamped_and_monotonic():
    d1 = MODEL.duration_ms_for_cm(2, 0.38)
    d2 = MODEL.duration_ms_for_cm(8, 0.38)
    assert MODEL.min_pulse_ms <= d1 <= d2 <= MODEL.max_pulse_ms


def test_below_deadband_duty_does_not_move():
    assert MODEL.speed_cm_s(0.05) == 0.0
    # No speed -> minimum pulse, and zero estimated distance.
    assert MODEL.distance_cm_for(0.05, 500) == 0.0


def test_single_pulse_under_travel_is_reported_honestly():
    # A 24cm request needs far more than the 850ms safety cap, so a single capped
    # pulse only covers a fraction of it. The model must say so (this is the
    # honesty fix for "doesn't go as far as it should").
    needed = MODEL.duration_ms_for_cm(24, 0.38)
    assert needed > 850  # one pulse cannot deliver 24cm safely
    capped_distance = MODEL.distance_cm_for(0.38, 850)
    assert 4.0 < capped_distance < 12.0  # honest: ~8cm, not 24cm


def test_estimate_chunk_blends_range_delta_with_model():
    est = estimate_chunk_distance_cm(model=MODEL, duty=0.38, duration_ms=380, front_before_cm=100.0, front_after_cm=94.0)
    assert est["range_delta_cm"] == 6.0
    assert est["source"] == "ultrasonic_delta+model"
    assert est["stalled"] is False
    assert est["estimated_cm"] > 0


def test_estimate_chunk_detects_stall():
    est = estimate_chunk_distance_cm(model=MODEL, duty=0.38, duration_ms=400, front_before_cm=50.0, front_after_cm=50.0)
    assert est["stalled"] is True


def test_estimate_chunk_open_space_uses_model_only():
    # No surface within usable range -> cannot measure delta, fall back to model,
    # and an open space must NOT be read as a stall.
    est = estimate_chunk_distance_cm(model=MODEL, duty=0.38, duration_ms=400, front_before_cm=300.0, front_after_cm=300.0)
    assert est["source"] == "model_only"
    assert est["stalled"] is False
    est_none = estimate_chunk_distance_cm(model=MODEL, duty=0.38, duration_ms=400, front_before_cm=None, front_after_cm=None)
    assert est_none["source"] == "model_only"
    assert est_none["stalled"] is False


def test_pose_estimate_accumulates_uncertainty_and_wraps_heading():
    pose = PoseEstimate()
    pose.integrate_forward(MODEL, 50.0)
    assert pose.x_cm == pytest.approx(50.0)
    assert pose.distance_sigma_cm > 0
    pose.integrate_turn(MODEL, 200.0)  # should wrap into [-180, 180]
    assert -180.0 <= pose.heading_deg <= 180.0
    assert pose.heading_sigma_deg > 0
    pose.reset()
    assert (pose.x_cm, pose.y_cm, pose.distance_sigma_cm, pose.heading_sigma_deg) == (0.0, 0.0, 0.0, 0.0)


def test_motion_model_from_config_roundtrips():
    model = motion_model_from(OdometryConfig())
    assert isinstance(model, MotionModel)
    assert model.cm_s_per_duty == OdometryConfig().cm_s_per_duty
