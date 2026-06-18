from __future__ import annotations

from rover.telegram_agent import parse_rover_command


def test_parse_safe_status_command():
    argv, error = parse_rover_command("/rover status")
    assert error is None
    assert argv == ["cleo-rover", "status"]


def test_parse_parameterized_map_scan():
    argv, error = parse_rover_command("/rover map-scan --zone office --angles=-25,0,25")
    assert error is None
    assert argv == ["cleo-rover", "map-scan", "--zone", "office", "--angles=-25,0,25"]


def test_parse_floor_precheck_and_estop():
    argv, error = parse_rover_command("/rover floor-precheck --zone living-room")
    assert error is None
    assert argv == ["cleo-rover", "floor-precheck", "--zone", "living-room"]

    argv, error = parse_rover_command("/rover estop")
    assert error is None
    assert argv == ["cleo-rover", "safe-mode", "--amber"]


def test_parse_floor_map_dry_run_allowed_but_map_floor_blocked():
    argv, error = parse_rover_command("/rover floor-map-dry-run --zone living-room --steps 2")
    assert error is None
    assert argv == ["cleo-rover", "floor-map-dry-run", "--zone", "living-room", "--steps", "2"]

    argv, error = parse_rover_command("/rover map-floor --zone living-room --allow-movement")
    assert argv is None
    assert error is not None
    assert "Refusing" in error


def test_blocks_movement_commands():
    argv, error = parse_rover_command("/rover drive --linear 1")
    assert argv is None
    assert error is not None
    assert "Refusing" in error


def test_ignores_non_rover_text():
    argv, error = parse_rover_command("hello")
    assert argv is None
    assert error is None


def test_start_and_group_mention_help():
    argv, error = parse_rover_command("/start")
    assert argv is None
    assert error is not None
    argv, error = parse_rover_command("/rover@cleo_rover_bot status")
    assert error is None
    assert argv == ["cleo-rover", "status"]
