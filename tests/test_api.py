from fastapi.testclient import TestClient

from rover.models import ExpressionCommand, ExpressionMode
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


def test_drive_rejected_in_no_motor_profile_and_step_requires_permission():
    drive = client.post("/drive", json={"linear": 0.2, "turn": 0, "duration_ms": 100})
    assert drive.status_code == 200
    assert drive.json()["ok"] is False
    assert "bench_safe_no_motors" in drive.json()["reason"]

    step = client.post("/movement/move-step", json={"forward_cm": 8, "require_permission": True})
    assert step.status_code == 200
    assert step.json()["ok"] is False


def test_visual_map_scan_and_look_remember_paths():
    scan = client.post("/map/visual-scan", json={"zone": "office", "angles": [0], "settle_ms": 50, "capture_each_angle": False})
    assert scan.status_code == 200
    assert scan.json()["needs_external_vision"] is True
    assert scan.json()["observations"][0]["event"]["payload"]["needs_external_vision"] is True


def test_expression_and_status():
    r = client.post("/expression", json={"mode": "listening", "text": "yes?", "brightness": 0.4})
    assert r.status_code == 200
    status = client.get("/status").json()
    assert status["expression"]["mode"] == "listening"
    assert status["expression"]["text"] == "yes?"


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
