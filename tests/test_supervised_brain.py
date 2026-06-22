from rover.brain import choose_body_intent, choose_escape_turn, extract_scan_result, supervisor_result_summary
from rover.models import BodyIntentCommand
from rover.supervisor import intent_to_actions, validate_intent


def blocked_snapshot(distance=56.0):
    return {
        "safety_flags": ["front_near"],
        "range_state": {"state": "near"},
        "sensors": {"front_distance_cm": distance},
        "status": {"motors_armed": True},
    }


def clear_snapshot(distance=120.0):
    return {
        "safety_flags": [],
        "range_state": {"state": "clear"},
        "sensors": {"front_distance_cm": distance},
        "status": {"motors_armed": True},
    }


def scan_result(*pairs):
    return {
        "ok": True,
        "observations": [
            {"event": {"payload": {"bearing_deg": bearing, "distance_cm": distance}}}
            for bearing, distance in pairs
        ],
    }


def test_choose_escape_turn_picks_clear_right_side():
    scan = scan_result((-45, 45), (-25, 62), (0, 55), (25, 110), (45, 95))
    escape = choose_escape_turn(scan)
    assert escape is not None
    assert escape["deg"] == 10.0
    assert escape["bearing_deg"] == 25.0


def test_choose_escape_turn_picks_clear_left_side():
    scan = scan_result((-45, 130), (-25, 88), (0, 50), (25, 65), (45, 62))
    escape = choose_escape_turn(scan)
    assert escape is not None
    assert escape["deg"] == -10.0
    assert escape["bearing_deg"] == -45.0


def test_blocked_after_scan_rotates_toward_clearest_side():
    scan = scan_result((-45, 45), (-25, 62), (0, 55), (25, 110), (45, 95))
    intent = choose_body_intent(blocked_snapshot(), zone="office", last_intent="scan", last_scan=scan)
    assert intent["intent"] == "rotate_step"
    assert intent["params"]["deg"] == 10.0
    assert intent["params"]["reason"] == "clearest_scan"


def test_blocked_after_scan_rotates_toward_modestly_better_side():
    scan = scan_result((-45, 70.3), (-25, 61), (0, 54), (25, 58), (45, 62))
    intent = choose_body_intent(blocked_snapshot(distance=54), zone="office", last_intent="scan", last_scan=scan)
    assert intent["intent"] == "rotate_step"
    assert intent["params"]["deg"] == -10.0
    assert intent["params"]["distance_cm"] == 70.3


def test_blocked_after_rotate_rescans_before_moving():
    intent = choose_body_intent(blocked_snapshot(), zone="office", last_intent="rotate_step")
    assert intent["intent"] == "scan"


def test_narrow_path_after_scan_rotates_toward_clear_side():
    scan = scan_result((-35, 58), (-15, 72), (0, 82), (15, 96), (35, 145))
    intent = choose_body_intent(clear_snapshot(82), zone="office", last_intent="scan", last_scan=scan)
    assert intent["intent"] == "rotate_step"
    assert intent["params"]["deg"] == 10.0
    assert intent["params"]["reason"] == "clearest_scan_after_narrow_path"


def test_narrow_path_without_clear_side_keeps_searching_not_forward():
    scan = scan_result((-35, 58), (-15, 64), (0, 82), (15, 70), (35, 75))
    intent = choose_body_intent(clear_snapshot(82), zone="office", last_intent="scan", last_scan=scan)
    assert intent["intent"] in {"mood", "rotate_step", "scan"}
    assert intent["intent"] != "move_step"


def test_after_confused_mood_under_clearance_does_not_default_to_forward():
    scan = scan_result((-35, 58), (-15, 64), (0, 72), (15, 70), (35, 75))
    intent = choose_body_intent(clear_snapshot(72), zone="office", last_intent="mood", last_scan=scan)
    assert intent["intent"] in {"rotate_step", "scan"}
    assert intent["intent"] != "move_step"


def test_supervised_rotate_uses_floor_calibration():
    actions = intent_to_actions(BodyIntentCommand(intent="rotate_step", mood="focused", params={"deg": 25}))
    drive = next(action for action in actions if action["kind"] == "drive")
    assert drive["command"] == {"linear": 0.0, "turn": 0.45, "duration_ms": 300}


def test_supervised_move_uses_floor_pulse_not_buzz_tick():
    actions = intent_to_actions(BodyIntentCommand(intent="move_step", mood="focused", params={"forward_cm": 3}))
    drive = next(action for action in actions if action["kind"] == "drive")
    assert drive["command"] == {"linear": 0.34, "turn": 0.0, "duration_ms": 220}


def test_supervisor_rejects_forward_under_real_clearance():
    command = BodyIntentCommand(intent="move_step", mood="focused", params={"forward_cm": 3})
    status = {"motors_armed": True, "safety": {"bench_safe_no_motors": False}}
    movement = {"active": True}
    ok, reason = validate_intent(command, status=status, sensors={"front_distance_cm": 72, "front_stop_distance_cm": 18}, movement=movement)
    assert ok is False
    assert "below 120.0cm" in reason


def test_supervisor_allows_forward_with_real_clearance():
    command = BodyIntentCommand(intent="move_step", mood="focused", params={"forward_cm": 3})
    status = {"motors_armed": True, "safety": {"bench_safe_no_motors": False}}
    movement = {"active": True}
    ok, reason = validate_intent(command, status=status, sensors={"front_distance_cm": 134, "front_stop_distance_cm": 18}, movement=movement)
    assert ok is True
    assert reason == "intent accepted"


def test_extract_scan_result_from_supervisor_response():
    scan = scan_result((0, 55))
    result = {"applied": [{"kind": "expression", "result": {}}, {"kind": "scan", "result": scan}]}
    assert extract_scan_result(result) is scan


def test_supervisor_result_summary_includes_drive_and_scan_context():
    scan = scan_result((-15, 300), (0, 200), (15, 120))
    result = {
        "applied": [
            {"kind": "drive", "result": {"command": {"linear": 0.34, "turn": 0, "duration_ms": 220}}},
            {"kind": "scan", "result": scan},
        ],
        "snapshot": {"sensors": {"front_distance_cm": 200}, "range_state": {"state": "clear"}},
    }
    summary = supervisor_result_summary(result)
    assert summary["drive"]["duration_ms"] == 220
    assert summary["scan"]["best_bearing_deg"] == -15.0
    assert summary["front_distance_cm"] == 200
