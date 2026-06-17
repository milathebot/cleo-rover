from __future__ import annotations

from typing import Any

from rover.choreo import obstacle_clear, rgb_payload, run_dance, run_presence_tick


def test_rgb_payload_modes():
    assert rgb_payload("dance") == {"red": 120, "green": 0, "blue": 255, "brightness": 24}
    assert rgb_payload("off")["brightness"] == 1


def test_obstacle_clear_refuses_close_object():
    ok, reason = obstacle_clear({"front_distance_cm": 10, "front_stop_distance_cm": 18})
    assert ok is False
    assert "closer" in reason


def test_dance_requires_lifted_for_motors():
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        calls.append((method, path, payload))
        if path == "/sensors":
            return {"front_distance_cm": 40, "front_stop_distance_cm": 18}
        return {"ok": True}

    result = run_dance(request, lifted=False, sleep_fn=lambda _: None)
    assert result["ok"] is False
    assert result["reason"].startswith("dance motor movement requires")
    assert ("POST", "/stop", None) in calls
    assert not any(path == "/drive" for _, path, _ in calls)


def test_dance_no_motors_runs_turret_and_cleanup():
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        calls.append((method, path, payload))
        if path == "/sensors":
            return {"front_distance_cm": 40, "front_stop_distance_cm": 18}
        return {"ok": True}

    result = run_dance(request, no_motors=True, sleep_fn=lambda _: None)
    assert result["ok"] is True
    assert any(path == "/turret" for _, path, _ in calls)
    assert not any(path == "/drive" for _, path, _ in calls)
    assert calls[-3:] == [
        ("POST", "/stop", None),
        ("POST", "/turret", {"pan_deg": 0}),
        ("POST", "/rgb", {"red": 0, "green": 0, "blue": 0, "brightness": 1}),
    ]


def test_presence_tick_sets_idle_when_camera_ready():
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        calls.append((method, path, payload))
        if path == "/sensors":
            return {"camera": {"ready": True}, "battery_percent": 73, "errors": {}}
        if path == "/status":
            return {"mode": "hardware", "stopped": True}
        return {"ok": True}

    result = run_presence_tick(request, sleep_fn=lambda _: None)
    assert result["ok"] is True
    assert result["rgb_mode"] == "idle"
    assert ("POST", "/rgb", {"red": 120, "green": 0, "blue": 255, "brightness": 18}) in calls
    assert any(path == "/turret" for _, path, _ in calls)
