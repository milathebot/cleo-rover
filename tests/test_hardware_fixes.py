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


def test_turret_pan_slews_instead_of_snapping():
    # A hard wide-angle jump slams the servo and vibrates the pan-mount screws loose;
    # the pan should ease to target in multiple steps, landing exactly on target.
    from rover.config import RoverConfig
    from rover.freenove import FreenoveHardware, pan_pulse_us
    from rover.models import TurretCommand

    calls: list = []

    class FakePWM:
        def set_servo_pulse_us(self, channel: int, us: int) -> None:
            calls.append((channel, us))

    body = object.__new__(FreenoveHardware)
    cfg = RoverConfig()
    cfg.turret.pan_trim_deg = 0.0
    cfg.turret.pan_slew_deg = 12.0
    cfg.turret.pan_slew_settle_ms = 0.0  # no real sleeps in the test
    body.config = cfg
    body.pwm = FakePWM()
    body.last_pan_deg = 0.0
    ch = cfg.turret.pan_channel

    body.set_turret(TurretCommand(pan_deg=70))      # wide span -> eased steps
    assert len(calls) > 1
    assert calls[-1] == (ch, pan_pulse_us(70))      # lands exactly on target
    assert body.last_pan_deg == 70

    calls.clear()
    body.set_turret(TurretCommand(pan_deg=75))      # span 5 <= step -> single write
    assert calls == [(ch, pan_pulse_us(75))]

    calls.clear()
    cfg.turret.pan_slew_deg = 0.0                    # disabled -> snap (old behavior)
    body.set_turret(TurretCommand(pan_deg=-70))
    assert calls == [(ch, pan_pulse_us(-70))]


def test_pan_trim_offsets_physical_pulse_only():
    # pan_trim_deg shifts the physical servo pulse so logical 0deg points dead ahead,
    # without changing the reported/logical pan_deg the safety layers reason about.
    from rover.config import RoverConfig
    from rover.freenove import FreenoveHardware
    from rover.models import TurretCommand

    captured: dict[int, int] = {}

    class FakePWM:
        def set_servo_pulse_us(self, channel: int, us: int) -> None:
            captured[channel] = us

    body = object.__new__(FreenoveHardware)  # bypass hardware __init__
    cfg = RoverConfig()
    cfg.turret.pan_trim_deg = -16.0
    body.config = cfg
    body.pwm = FakePWM()

    ch = cfg.turret.pan_channel
    body.set_turret(TurretCommand(pan_deg=0))
    assert captured[ch] == pan_pulse_us(-16)   # logical 0 -> physical -16
    body.set_turret(TurretCommand(pan_deg=20))
    assert captured[ch] == pan_pulse_us(4)     # 20 + (-16)

    cfg.turret.pan_trim_deg = 0.0              # no trim => identity
    body.set_turret(TurretCommand(pan_deg=0))
    assert captured[ch] == pan_pulse_us(0)


def test_inplace_turn_boosted_to_floor_but_arc_steering_untouched():
    from rover.models import DriveCommand
    # a weak in-place turn is floored to min_inplace_turn so the 4WD actually rotates
    weak = drive_to_wheel_duty(DriveCommand(linear=0.0, turn=0.16, duration_ms=180), 0.45, min_inplace_turn=1.0)
    full = drive_to_wheel_duty(DriveCommand(linear=0.0, turn=1.0, duration_ms=180), 0.45)
    assert weak.left_upper == full.left_upper and weak.right_upper == full.right_upper
    assert weak.left_upper > 0 and weak.right_upper < 0          # opposite -> rotation in place
    # arc steering WHILE MOVING is not boosted (stays a gentle differential)
    arc = drive_to_wheel_duty(DriveCommand(linear=0.4, turn=0.16, duration_ms=180), 0.45, min_inplace_turn=1.0)
    assert arc.left_upper != full.left_upper and arc.left_upper > arc.right_upper > 0
    # floor disabled (0.0) keeps the old behavior
    raw = drive_to_wheel_duty(DriveCommand(linear=0.0, turn=0.16, duration_ms=180), 0.45)
    assert raw.left_upper < full.left_upper


def test_resolve_front_range_holds_through_dropouts():
    # The forward reflex must reuse a recent good range through brief HC-SR04 dropouts
    # under motor noise, and only fail CLOSED when blind longer than the hold window.
    from rover.drivers import resolve_front_range

    # valid read -> passes through, refreshes cache
    r, blind, lg, at = resolve_front_range(120.0, None, 0.0, 10.0, 0.25)
    assert r == 120.0 and blind is False and lg == 120.0 and at == 10.0

    # transient None within hold window -> reuse last good, not blind
    r, blind, lg, at = resolve_front_range(None, 120.0, 10.0, 10.1, 0.25)
    assert r == 120.0 and blind is False

    # None past the hold window -> blind / fail closed
    r, blind, lg, at = resolve_front_range(None, 120.0, 10.0, 10.5, 0.25)
    assert r is None and blind is True

    # never had a good read -> blind
    r, blind, lg, at = resolve_front_range(None, None, 0.0, 5.0, 0.25)
    assert blind is True
