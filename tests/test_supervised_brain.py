from rover.brain import choose_body_intent, choose_escape_turn, extract_scan_result
from rover.models import BodyIntentCommand
from rover.supervisor import intent_to_actions


def blocked_snapshot(distance=56.0):
    return {
        "safety_flags": ["front_near"],
        "range_state": {"state": "near"},
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
    assert escape["deg"] == 25.0
    assert escape["bearing_deg"] == 25.0


def test_choose_escape_turn_picks_clear_left_side():
    scan = scan_result((-45, 130), (-25, 88), (0, 50), (25, 65), (45, 62))
    escape = choose_escape_turn(scan)
    assert escape is not None
    assert escape["deg"] == -25.0
    assert escape["bearing_deg"] == -45.0


def test_blocked_after_scan_rotates_toward_clearest_side():
    scan = scan_result((-45, 45), (-25, 62), (0, 55), (25, 110), (45, 95))
    intent = choose_body_intent(blocked_snapshot(), zone="office", last_intent="scan", last_scan=scan)
    assert intent["intent"] == "rotate_step"
    assert intent["params"]["deg"] == 25.0
    assert intent["params"]["reason"] == "clearest_scan"


def test_blocked_after_rotate_rescans_before_moving():
    intent = choose_body_intent(blocked_snapshot(), zone="office", last_intent="rotate_step")
    assert intent["intent"] == "scan"


def test_supervised_rotate_uses_floor_calibration():
    actions = intent_to_actions(BodyIntentCommand(intent="rotate_step", mood="focused", params={"deg": 25}))
    drive = next(action for action in actions if action["kind"] == "drive")
    assert drive["command"] == {"linear": 0.0, "turn": 0.65, "duration_ms": 550}


def test_extract_scan_result_from_supervisor_response():
    scan = scan_result((0, 55))
    result = {"applied": [{"kind": "expression", "result": {}}, {"kind": "scan", "result": scan}]}
    assert extract_scan_result(result) is scan
