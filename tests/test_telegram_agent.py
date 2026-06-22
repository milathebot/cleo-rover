from __future__ import annotations

import re

from rover.telegram_agent import AgentConfig, active_floor_arm, build_floor_map_run, handle_floor_arm, handle_floor_mode, load_saved_offset, parse_rover_command, profile_switch_argv, save_offset


def test_parse_safe_status_command():
    argv, error = parse_rover_command("/rover status")
    assert error is None
    assert argv == ["cleo-rover", "status"]


def test_parse_safe_situation_and_map_summary_commands():
    argv, error = parse_rover_command("/rover situation")
    assert error is None
    assert argv == ["cleo-rover", "situation"]

    argv, error = parse_rover_command("/rover map-summary")
    assert error is None
    assert argv == ["cleo-rover", "map-summary"]

    argv, error = parse_rover_command("/rover doctor")
    assert error is None
    assert argv == ["cleo-rover", "doctor"]

    argv, error = parse_rover_command("/rover preflight --mode floor")
    assert error is None
    assert argv == ["cleo-rover", "preflight", "--mode", "floor"]

    argv, error = parse_rover_command("/rover last-seen")
    assert error is None
    assert argv == ["cleo-rover", "last-seen"]

    argv, error = parse_rover_command("/rover remember-room --zone office")
    assert error is None
    assert argv == ["cleo-rover", "remember-room", "--zone", "office"]


def test_parse_parameterized_map_scan():
    argv, error = parse_rover_command("/rover map-scan --zone office --angles=-25,0,25")
    assert error is None
    assert argv == ["cleo-rover", "map-scan", "--zone", "office", "--angles=-25,0,25"]


def test_parse_pip_safe_commands():
    argv, error = parse_rover_command("/rover pip status")
    assert error is None
    assert argv == ["cleo-rover", "pip", "status"]

    argv, error = parse_rover_command("/rover pip observe")
    assert error is None
    assert argv == ["cleo-rover", "pip", "observe"]


def test_parse_floor_precheck_and_estop():
    argv, error = parse_rover_command("/rover floor-precheck --zone living-room")
    assert error is None
    assert argv == ["cleo-rover", "floor-precheck", "--zone", "living-room"]

    argv, error = parse_rover_command("/rover estop")
    assert error is None
    assert argv == ["cleo-rover", "safe-mode"]


def test_floor_mode_request_and_switch_argv(tmp_path):
    config = AgentConfig(token="t", allowed_user_id=1, workdir=str(tmp_path))
    response = handle_floor_mode("/rover floor-mode request", config)
    assert response is not None
    code_match = re.search(r"confirm (\d{6})", response)
    assert code_match is not None
    assert profile_switch_argv(config, "floor-cautious") == ["sudo", "-n", str(tmp_path / "scripts/set_rover_profile.sh"), "floor-cautious"]

    wrong = handle_floor_mode("/rover floor-mode confirm 000000", config)
    assert wrong is not None and "Wrong" in wrong


def test_floor_arm_request_confirm_and_map_run(tmp_path):
    config = AgentConfig(token="t", allowed_user_id=1, workdir=str(tmp_path))
    response = handle_floor_arm("/rover floor-arm request", config)
    assert response is not None
    code_match = re.search(r"confirm (\d{6})", response)
    assert code_match is not None
    code = code_match.group(1)

    argv, error = build_floor_map_run("/rover floor-map-run --zone living-room --steps 1", config)
    assert argv is None
    assert error is not None and "not armed" in error

    wrong = handle_floor_arm("/rover floor-arm confirm 000000", config)
    assert wrong is not None and "Wrong" in wrong
    confirmed = handle_floor_arm(f"/rover floor-arm confirm {code}", config)
    assert confirmed is not None and "armed" in confirmed
    assert active_floor_arm(config) is not None
    argv, error = build_floor_map_run("/rover floor-map-run --zone living-room --steps 1", config)
    assert error is None
    assert argv == ["cleo-rover", "map-floor", "--allow-movement", "--zone", "living-room", "--steps", "1"]

    cancelled = handle_floor_arm("/rover floor-arm cancel", config)
    assert cancelled is not None and "cancelled" in cancelled
    assert active_floor_arm(config) is None


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
