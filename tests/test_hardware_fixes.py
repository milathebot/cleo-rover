"""Tests for the FNK0043 hardware-audit fixes (pan inversion, cruise ramp skip)."""

from __future__ import annotations

from rover.freenove import WheelDuty, _duty_close, drive_to_wheel_duty, pan_angle_for, pan_pulse_us


def test_pan_pulse_is_inverted_more_right_lower_pulse():
    # The FNK0043 pan channel inverts: a larger (rightward) pan -> a SMALLER pulse.
    # The old bug used the non-inverted form (pulse increased with pan), mirroring it.
    left = pan_pulse_us(-70)
    center = pan_pulse_us(0)
    right = pan_pulse_us(70)
    assert left > center > right
    assert center == 2500 - int((90 + 10) / 0.09)  # exact inverted formula


def test_pan_angle_clamps_to_servo_range():
    assert pan_angle_for(0) == 90
    assert pan_angle_for(200) == 170
    assert pan_angle_for(-200) == 10


def test_duty_close_detects_unchanged_target():
    a = WheelDuty(100, 100, 100, 100)
    assert _duty_close(a, WheelDuty(110, 90, 100, 130)) is True   # within tol=40
    assert _duty_close(a, WheelDuty(100, 100, 100, 300)) is False  # one channel jumps


def test_drive_to_wheel_duty_forward_all_positive():
    duty = drive_to_wheel_duty(__import__("rover.models", fromlist=["DriveCommand"]).DriveCommand(linear=0.5, turn=0.0, duration_ms=200), 0.45)
    assert duty.left_upper > 0 and duty.right_upper > 0
    assert duty.left_upper == duty.left_lower  # both left wheels equal going straight
