from fastapi.testclient import TestClient

from rover.models import ExpressionCommand, ExpressionMode
from rover.pip_soul import pip_soul_prompt
from rover.renderer import render_expression
from rover.service import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_operator_panel():
    r = client.get("/")
    assert r.status_code == 200
    assert "Cleo Rover Mk1" in r.text
    assert "/expression/preview.png" in r.text


def test_config_endpoint():
    r = client.get("/config")
    assert r.status_code == 200
    data = r.json()
    assert data["display"]["type"] == "waveshare-st7789"
    assert data["motors"]["driver"] == "freenove-pca9685-4wd"
    assert data["motors"]["i2c_address"] == "0x40"
    assert data["turret"]["pan_channel"] == 8
    assert data["turret"]["tilt_channel"] == 9
    assert data["display"]["spi_bus"] == 1
    assert data["display"]["spi_device"] == 0
    assert data["display"]["cs_pin"] == 6
    assert data["display"]["dc_pin"] == 25
    assert data["display"]["reset_pin"] == 5
    assert data["display"].get("backlight_pin") is None
    assert data["sensors"]["ultrasonic_trigger_pin"] == 27
    assert data["safety"]["bench_safe_no_motors"] is True


def test_status_includes_readiness_and_safety():
    r = client.get("/status")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "cleo-rover-mk1"
    assert data["hardware_ready"] is False
    assert data["motors_armed"] is False
    assert data["safety"]["max_drive_duration_ms"] == 2000


def test_hardware_presence_profile_initializes_hardware_without_arming_motors(monkeypatch):
    from rover.config import RoverConfig
    import rover.drivers as drivers

    class DummyHardware:
        def __init__(self, config):
            self.config = config

    monkeypatch.setattr(drivers, "FreenoveHardware", DummyHardware)
    body = drivers.RoverBody(mode="hardware", config=RoverConfig.model_validate({"safety": {"bench_safe_no_motors": True}}))
    assert body.hardware_ready is True
    assert body.motors_armed is False


def test_sensors_include_hardware_map():
    r = client.get("/sensors")
    assert r.status_code == 200
    data = r.json()
    assert data["display"]["size"] == [240, 320]
    assert data["motors"]["driver"] == "freenove-pca9685-4wd"
    assert data["camera"]["driver"] == "rpicam-still"
    assert data["rgb"]["driver"] == "spi-ws2812"
    assert data["rgb"]["count"] == 8
    assert data["freenove_map"]["pca9685"]["i2c_address"] == "0x40"
    assert data["freenove_map"]["motors"]["channels"]["left_upper"] == [1, 0]
    assert data["freenove_map"]["servos"] == {"pan": 8, "tilt": 9}
    assert data["freenove_map"]["line_sensors_bcm"]["center"] == 15
    assert data["turret"]["driver"] == "pca9685"


def test_rgb_endpoint_simulates_off_hardware():
    r = client.post("/rgb", json={"red": 120, "green": 0, "blue": 255, "brightness": 24})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["simulated"] is True
    assert data["rgb"]["blue"] == 255


def test_map_scan_records_range_observations():
    r = client.post("/map/scan", json={"zone": "office", "angles": [-10, 0, 10], "settle_ms": 50})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["zone"] == "office"
    assert len(data["observations"]) == 3
    assert data["observations"][0]["item"]["kind"] == "range_scan"


def test_vision_analysis_fuses_with_spatial_memory():
    r = client.post(
        "/vision/analysis",
        json={
            "summary": "A chair near the wall",
            "labels": ["chair", "wall"],
            "confidence": 0.8,
            "zone": "office",
            "snapshot_path": "captures/test.jpg",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    labels = {item["label"] for item in data["items"]}
    assert {"chair", "wall"} <= labels
    assert any(item["kind"] == "vision_obstacle" for item in data["items"])
    assert any(event["kind"] == "obstacle" for event in data["semantic_events"])


def test_map_summary_and_situation_endpoints():
    summary = client.get("/map/summary")
    assert summary.status_code == 200
    assert summary.json()["ok"] is True
    assert "summary" in summary.json()

    situation = client.get("/situation")
    assert situation.status_code == 200
    data = situation.json()
    assert data["ok"] is True
    assert data["risk"] in {"blocked", "clear_or_unknown"}
    assert "map_summary" in data
    assert "range_state" in data


def test_doctor_last_seen_motion_and_prune_endpoints():
    doctor = client.get("/doctor")
    assert doctor.status_code == 200
    assert "system" in doctor.json()

    preflight = client.get("/preflight?mode=presence")
    assert preflight.status_code == 200
    assert preflight.json()["mode"] == "presence"
    assert any(check["name"] == "bench_safe" for check in preflight.json()["checks"])
    assert any(check["name"] == "gpio_pin_conflicts" and check["ok"] for check in preflight.json()["checks"])
    assert any(check["name"] == "display_pin_map" and check["ok"] for check in preflight.json()["checks"])

    last_seen = client.get("/last-seen")
    assert last_seen.status_code == 200
    assert last_seen.json()["ok"] is True

    motion = client.post("/vision/motion")
    assert motion.status_code == 200
    assert motion.json()["ok"] is True

    prune = client.post("/data/prune?keep_days=30&keep_snapshots=500&dry_run=true")
    assert prune.status_code == 200
    assert prune.json()["ok"] is True


def test_no_motor_presence_lookaround_and_remember_room_paths():
    look = client.post("/presence/look-around?zone=office")
    assert look.status_code == 200
    assert look.json()["movement"] == "none"

    remember = client.post("/presence/remember-room?zone=office")
    assert remember.status_code == 200
    assert remember.json()["movement"] == "none"


def test_movement_permission_and_map_floor_are_permissioned():
    grant = client.post("/movement/grant", json={"task": "map-office", "allow_movement": False, "duration_seconds": 60})
    assert grant.status_code == 200
    assert grant.json()["movement"]["active"] is False
    status = client.get("/movement/status").json()
    assert status["active"] is False

    task = client.post("/tasks/map-floor", json={"zone": "office", "allow_movement": False})
    assert task.status_code == 200
    assert task.json()["task"]["active"] is False
    assert "Conservative floor mapping" in task.json()["safety"]
    assert task.json()["plan"][0]["kind"] == "scan"

    revoked = client.post("/movement/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["stopped"] is True


def test_reactive_explore_scan_only_path():
    task = client.post("/tasks/reactive-explore", json={"zone": "office", "allow_movement": False, "duration_seconds": 5, "max_cycles": 2})
    assert task.status_code == 200
    data = task.json()
    assert data["ok"] is True
    assert data["task"]["active"] is False
    assert data["summary"]["counts"]["scan-only"] == 1
    assert any(item["kind"] == "scan-only" for item in data["plan"])
    assert "observations" not in data["plan"][0]
    assert "persistent" in data["safety"]


def test_reactive_explore_keeps_searching_in_corner_instead_of_giving_up(monkeypatch):
    from rover import service

    async def fake_scan(zone, angles):
        assert len(angles) >= 5
        return {"ok": True, "observations": []}, {"samples": [], "best": {"bearing_deg": 45.0, "distance_cm": 56.0}, "center": {"bearing_deg": 0.0, "distance_cm": 40.0}}

    readings = iter([40.0] * 20)
    monkeypatch.setattr(service, "reactive_escape_scan", fake_scan)
    monkeypatch.setattr(service.body, "sensors", lambda: {"front_distance_cm": next(readings, 40.0), "errors": {}, "battery_percent": 50})
    task = client.post(
        "/tasks/reactive-explore",
        json={"zone": "office", "allow_movement": True, "duration_seconds": 10, "max_cycles": 6, "front_clear_cm": 120, "front_stop_cm": 55, "front_emergency_cm": 30},
    )
    assert task.status_code == 200
    plan = task.json()["plan"]
    assert any(item["kind"] == "corner-search" for item in plan)
    assert not any(item["kind"] == "corner-trap" for item in plan)


def test_vision_awareness_endpoint_records_snapshot_event_in_sim():
    task = client.post("/tasks/vision-awareness", json={"zone": "office", "capture": False, "scan": False})
    assert task.status_code == 200
    data = task.json()
    assert data["ok"] is True
    assert data["capture"] is None
    assert data["scan_summary"] is None
    assert "scan" not in data
    assert data["event"]["kind"] == "camera_snapshot"


def test_little_being_loop_observes_and_uses_reactive_layer_without_movement():
    task = client.post("/tasks/little-being-loop", json={"zone": "office", "allow_movement": False, "duration_seconds": 8, "explore_cycles": 1, "capture_vision": False})
    assert task.status_code == 200
    data = task.json()
    assert data["ok"] is True
    assert data["summary"]["movement_allowed"] is False
    assert "reactive" in data["summary"]
    assert "steps" not in data
    assert "reactive explore + watchdog" in data["safety"]


def test_first_adventure_observe_only_wrapper_and_router():
    task = client.post(
        "/tasks/first-adventure",
        json={"zone": "office", "allow_movement": False, "duration_seconds": 8, "explore_cycles": 1, "speak": False},
    )
    assert task.status_code == 200
    data = task.json()
    assert data["ok"] is True
    assert data["started_movement"] is False
    assert data["readiness"]["movement_mode"] == "observe_only"
    assert "preflight" in data
    assert "First adventure always begins" in data["safety"]

    routed = client.post("/pip/command", json={"text": "first adventure", "source": "test", "allow_movement": False})
    assert routed.status_code == 200
    assert routed.json()["handled"] is True
    assert routed.json()["action"] == "first_adventure"


def test_pip_identity_modes_greet_and_interrupts():
    state = client.get("/pip/state")
    assert state.status_code == 200
    assert state.json()["identity"]["name"] == "Pip"
    assert state.json()["identity"]["home_base"] == "office"
    assert state.json()["soul_version"]
    assert "central_brain_digest" in state.json()["capabilities"]

    brain = client.get("/pip/brain")
    assert brain.status_code == 200
    brain_data = brain.json()
    assert brain_data["schema"] == "pip_brain_v1"
    assert brain_data["where_am_i"]["zone"]
    assert "what_happened" in brain_data
    assert "what_is_around_me" in brain_data
    assert "what_i_want" in brain_data
    assert "next_safe_action" in brain_data

    soul = client.get("/pip/soul")
    assert soul.status_code == 200
    assert soul.json()["identity"]["name"] == "Pip"
    assert "never claim" in soul.json()["system_prompt"].lower()
    assert "first person as Pip" in pip_soul_prompt()

    quiet = client.post("/pip/mode", json={"mode": "quiet", "reason": "test"})
    assert quiet.status_code == 200
    assert quiet.json()["state"]["state"]["mode"] == "quiet"

    greet = client.post("/pip/greet")
    assert greet.status_code == 200
    assert greet.json()["line"] == "hi noot."

    rescue = client.post("/pip/rescue-needed?reason=test%20stuck")
    assert rescue.status_code == 200
    assert rescue.json()["interrupt"]["kind"] == "rescue"

    interrupts = client.get("/pip/interrupts?mark_delivered=true")
    assert interrupts.status_code == 200
    assert interrupts.json()["count"] >= 1


def test_pip_life_tick_and_command_router(monkeypatch):
    from rover import service

    client.post("/pip/mode", json={"mode": "social", "reason": "test"})
    tick = client.post("/pip/life-tick", json={"allow_movement": False, "force": False, "reason": "test"})
    assert tick.status_code == 200
    assert tick.json()["decision"] in {"observe", "patrol", "low_power", "resting_low_power", "rescue", "sleep"}

    service.pip_interrupts.clear()
    monkeypatch.setattr(service.body, "sensors", lambda: {"front_distance_cm": 120, "errors": {}, "battery_percent": 20, "battery_voltage": 6.8})
    low = client.post("/pip/life-tick", json={"allow_movement": True, "force": True, "reason": "low battery test"})
    assert low.status_code == 200
    assert low.json()["decision"] == "low_power"
    resting = client.post("/pip/life-tick", json={"allow_movement": True, "force": True, "reason": "low battery repeat"})
    assert resting.status_code == 200
    assert resting.json()["decision"] == "resting_low_power"

    status = client.post("/pip/command", json={"text": "status", "source": "test"})
    assert status.status_code == 200
    assert status.json()["handled"] is True
    assert status.json()["action"] == "state"

    brain = client.post("/pip/command", json={"text": "what are you doing", "source": "test"})
    assert brain.status_code == 200
    assert brain.json()["handled"] is True
    assert brain.json()["action"] == "brain"
    assert brain.json()["brain"]["schema"] == "pip_brain_v1"

    goal = client.post("/pip/command", json={"text": "I want to go to the back yard", "source": "test"})
    assert goal.status_code == 200
    assert goal.json()["handled"] is True
    assert goal.json()["action"] == "destination_goal"
    assert goal.json()["goal"]["destination"] == "the back yard"
    assert goal.json()["goal"]["requires_human_help"] is True
    assert goal.json()["brain"]["what_i_want"]["goal"]["destination"] == "the back yard"

    relay = client.post("/pip/command", json={"text": "what is the weather?", "source": "test"})
    assert relay.status_code == 200
    assert relay.json()["handled"] is False
    assert relay.json()["action"] == "relay_to_hermes"


def test_drive_rejected_in_no_motor_profile_and_step_requires_permission():
    drive = client.post("/drive", json={"linear": 0.2, "turn": 0, "duration_ms": 100})
    assert drive.status_code == 200
    assert drive.json()["ok"] is False
    assert "bench_safe_no_motors" in drive.json()["reason"]

    step = client.post("/movement/move-step", json={"forward_cm": 8, "require_permission": True})
    assert step.status_code == 200
    assert step.json()["ok"] is False

    rotate = client.post("/movement/rotate-step", json={"deg": 25, "require_permission": True})
    assert rotate.status_code == 200
    assert rotate.json()["ok"] is False
    assert rotate.json()["command"] == {"linear": 0.0, "turn": 0.65, "duration_ms": 450}


def test_visual_map_scan_and_look_remember_paths():
    scan = client.post("/map/visual-scan", json={"zone": "office", "angles": [0], "settle_ms": 50, "capture_each_angle": False})
    assert scan.status_code == 200
    assert scan.json()["needs_external_vision"] is True
    assert scan.json()["observations"][0]["event"]["payload"]["needs_external_vision"] is True


def test_expression_and_status():
    r = client.post("/expression", json={"mode": "happy", "text": "yay", "brightness": 0.4})
    assert r.status_code == 200
    status = client.get("/status").json()
    assert status["expression"]["mode"] == "happy"
    assert status["expression"]["text"] == "yay"


def test_supervisor_body_agent_contract():
    status = client.get("/supervisor/status")
    assert status.status_code == 200
    data = status.json()
    assert data["role"] == "pi_body_agent"
    assert data["contract"]["pi_may_refuse"] is True

    mood = client.post("/supervisor/intent", json={"intent": "mood", "mood": "focused", "speech": "thinking", "params": {}})
    assert mood.status_code == 200
    assert mood.json()["accepted"] is True
    assert any(action["kind"] == "expression" for action in mood.json()["applied"])

    move = client.post("/supervisor/intent", json={"intent": "move_step", "mood": "focused", "params": {"forward_cm": 8}})
    assert move.status_code == 200
    assert move.json()["accepted"] is False
    assert "movement" in move.json()["reason"] or "motors" in move.json()["reason"] or "bench_safe" in move.json()["reason"]


def test_audio_endpoints_exist():
    devices = client.get("/audio/devices")
    assert devices.status_code == 200
    assert devices.json()["ok"] is True
    assert "playback" in devices.json()["devices"]

    say = client.post("/speech/say?text=test")
    assert say.status_code == 200
    assert "ok" in say.json()


def test_expression_preview_png():
    client.post("/expression", json={"mode": "thinking", "text": "boot", "brightness": 0.5})
    r = client.get("/expression/preview.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")


def test_renderer_size():
    frame = render_expression(ExpressionCommand(mode=ExpressionMode.idle, text="Cleo", brightness=0.6), t=1.0)
    assert frame.image.size == (240, 320)
    assert frame.png_bytes().startswith(b"\x89PNG")


def test_drive_validation():
    r = client.post("/drive", json={"linear": 2, "turn": 0, "duration_ms": 250})
    assert r.status_code == 422


def test_stop():
    client.post("/drive", json={"linear": 0.2, "turn": 0, "duration_ms": 500})
    r = client.post("/stop")
    assert r.status_code == 200
    assert r.json()["stopped"] is True
