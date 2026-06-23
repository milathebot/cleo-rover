from rover.config import RoverConfig
from rover.drivers import should_reflex_stop
from rover.freenove import FREENOVE_DEFAULT_SERVO_CHANNELS, FREENOVE_WHEEL_CHANNELS, FreenoveHardware, WheelDuty, drive_to_wheel_duty, freenove_hardware_map
from rover.models import DriveCommand


def test_freenove_channel_map_matches_ordinary_car_board():
    assert FREENOVE_WHEEL_CHANNELS == {
        "left_upper": (1, 0),
        "left_lower": (2, 3),
        "right_upper": (7, 6),
        "right_lower": (5, 4),
    }


def test_freenove_servo_channels_default_to_verified_pan_tilt_channels():
    assert FREENOVE_DEFAULT_SERVO_CHANNELS == {"pan": 8, "tilt": 9}
    hardware_map = freenove_hardware_map(RoverConfig())
    assert hardware_map["servos"] == {"pan": 8, "tilt": 9}


def test_drive_to_wheel_duty_forward_is_conservative_positive():
    duty = drive_to_wheel_duty(DriveCommand(linear=1.0, turn=0.0, duration_ms=100), max_duty_cycle=0.35)
    assert duty.left_upper == 1433
    assert duty.left_lower == 1433
    assert duty.right_upper == 1433
    assert duty.right_lower == 1433


def test_drive_to_wheel_duty_turn_right_splits_sides():
    duty = drive_to_wheel_duty(DriveCommand(linear=0.0, turn=1.0, duration_ms=100), max_duty_cycle=0.35)
    assert duty.left_upper > 0
    assert duty.left_lower > 0
    assert duty.right_upper < 0
    assert duty.right_lower < 0


def test_reflex_stop_only_applies_to_forward_close_obstacles():
    forward = DriveCommand(linear=0.34, turn=0.0, duration_ms=220)
    reverse = DriveCommand(linear=-0.30, turn=0.0, duration_ms=220)

    stop, reason = should_reflex_stop(forward, {"front_distance_cm": 19.5}, threshold_cm=20.0)
    assert stop is True
    assert reason is not None
    assert "19.5cm" in reason

    assert should_reflex_stop(forward, {"front_distance_cm": 20.5}, threshold_cm=20.0) == (False, None)
    assert should_reflex_stop(reverse, {"front_distance_cm": 10.0}, threshold_cm=20.0) == (False, None)
    assert should_reflex_stop(forward, {"front_distance_cm": None}, threshold_cm=20.0) == (False, None)


def test_freenove_ramp_blends_from_last_duty(monkeypatch):
    applied = []
    hardware = FreenoveHardware.__new__(FreenoveHardware)
    hardware.last_wheel_duty = WheelDuty(0, 0, 0, 0)

    def fake_apply(duty):
        applied.append(duty)
        hardware.last_wheel_duty = duty

    monkeypatch.setattr("rover.freenove.time.sleep", lambda _seconds: None)
    hardware._apply_wheel_duty = fake_apply
    target = WheelDuty(100, 100, -100, -100)
    result = hardware._ramp_to(target, ramp_ms=50, steps=4)

    assert result == target
    assert applied[0] == WheelDuty(25, 25, -25, -25)
    assert applied[-1] == target
