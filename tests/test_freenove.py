from rover.freenove import FREENOVE_WHEEL_CHANNELS, drive_to_wheel_duty
from rover.models import DriveCommand


def test_freenove_channel_map_matches_ordinary_car_board():
    assert FREENOVE_WHEEL_CHANNELS == {
        "left_upper": (1, 0),
        "left_lower": (2, 3),
        "right_upper": (7, 6),
        "right_lower": (5, 4),
    }


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
