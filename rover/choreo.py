from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

RequestFn = Callable[[str, str, dict[str, Any] | None], dict[str, Any]]

RGB_MODES: dict[str, tuple[int, int, int, int]] = {
    "off": (0, 0, 0, 1),
    "idle": (120, 0, 255, 18),
    "ready": (0, 255, 80, 20),
    "camera": (0, 80, 255, 22),
    "sensors": (0, 255, 80, 20),
    "error": (255, 0, 0, 28),
    "low_battery": (255, 140, 0, 24),
    "dance": (120, 0, 255, 24),
}


def rgb_payload(mode: str) -> dict[str, int]:
    if mode not in RGB_MODES:
        valid = ", ".join(sorted(RGB_MODES))
        raise ValueError(f"unknown RGB mode {mode!r}; valid modes: {valid}")
    red, green, blue, brightness = RGB_MODES[mode]
    return {"red": red, "green": green, "blue": blue, "brightness": brightness}


def set_rgb_mode(request: RequestFn, mode: str) -> dict[str, Any]:
    return request("POST", "/rgb", rgb_payload(mode))


def obstacle_clear(sensors: dict[str, Any], stop_distance_cm: float | None = None) -> tuple[bool, str]:
    distance = sensors.get("front_distance_cm")
    threshold = stop_distance_cm or sensors.get("front_stop_distance_cm") or 18.0
    if distance is None:
        return True, "front distance unavailable; allowing only because the operator requested a lifted bench routine"
    if float(distance) < float(threshold):
        return False, f"front obstacle at {distance}cm is closer than stop threshold {threshold}cm"
    return True, f"front path clear at {distance}cm"


def _post(request: RequestFn, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return request("POST", path, payload)


def _safe_sleep(seconds: float, sleep_fn: Callable[[float], None]) -> None:
    sleep_fn(max(0.0, seconds))


def run_dance(
    request: RequestFn,
    *,
    lifted: bool = True,
    no_motors: bool = False,
    intensity: float = 1.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Run a short, duration-limited Cleo dance.

    This routine assumes a human operator is present. It refuses wheel movement
    when not marked as lifted, and it checks the front ultrasonic reading before
    any drive commands. Every path ends with stop, turret center, and RGB off.
    """

    intensity = max(0.2, min(1.4, float(intensity)))
    actions: list[dict[str, Any]] = []
    sensors = request("GET", "/sensors", None)
    clear, reason = obstacle_clear(sensors)
    if not clear:
        set_rgb_mode(request, "error")
        _post(request, "/stop")
        return {"ok": False, "reason": reason, "actions": actions, "sensors": sensors}
    if not lifted and not no_motors:
        set_rgb_mode(request, "error")
        _post(request, "/stop")
        return {
            "ok": False,
            "reason": "dance motor movement requires --lifted for the first bench-safe routine",
            "actions": actions,
            "sensors": sensors,
        }

    def do(path: str, payload: dict[str, Any] | None = None, pause: float = 0.0) -> None:
        result = _post(request, path, payload)
        actions.append({"path": path, "payload": payload, "result": result})
        if pause:
            _safe_sleep(pause, sleep_fn)

    try:
        do("/stop")
        do("/rgb", rgb_payload("dance"), 0.1)
        do("/turret", {"pan_deg": -35}, 0.35)
        do("/turret", {"pan_deg": 35}, 0.35)
        do("/turret", {"pan_deg": 0}, 0.25)

        if not no_motors:
            turn = min(1.0, 0.95 * intensity)
            finish_turn = min(1.0, 0.8 * intensity)
            forward = min(0.85, 0.58 * intensity)
            reverse = -min(0.75, 0.50 * intensity)
            do("/drive", {"linear": 0.0, "turn": -turn, "duration_ms": 750}, 0.9)
            do("/drive", {"linear": 0.0, "turn": turn, "duration_ms": 750}, 0.9)
            do("/drive", {"linear": forward, "turn": 0.0, "duration_ms": 520}, 0.7)
            do("/drive", {"linear": reverse, "turn": 0.0, "duration_ms": 520}, 0.7)
            do("/drive", {"linear": 0.0, "turn": -finish_turn, "duration_ms": 480}, 0.6)
            do("/drive", {"linear": 0.0, "turn": finish_turn, "duration_ms": 480}, 0.6)

        do("/turret", {"pan_deg": -20}, 0.25)
        do("/turret", {"pan_deg": 20}, 0.25)
        do("/turret", {"pan_deg": 0}, 0.1)
        return {"ok": True, "reason": reason, "actions": actions, "sensors": sensors}
    finally:
        _post(request, "/stop")
        _post(request, "/turret", {"pan_deg": 0})
        _post(request, "/rgb", rgb_payload("off"))


def run_presence_tick(
    request: RequestFn,
    *,
    glance: bool = True,
    snapshot: bool = False,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """One non-driving presence tick: sensors, RGB status, optional glance/snapshot."""

    sensors = request("GET", "/sensors", None)
    status = request("GET", "/status", None)
    actions: list[dict[str, Any]] = []

    battery = sensors.get("battery_percent")
    errors = sensors.get("errors") or {}
    if errors:
        mode = "error"
    elif battery is not None and float(battery) < 20:
        mode = "low_battery"
    elif sensors.get("camera", {}).get("ready"):
        mode = "idle"
    elif sensors.get("adc_ready") or sensors.get("ultrasonic_ready"):
        mode = "sensors"
    else:
        mode = "ready"
    actions.append({"rgb": set_rgb_mode(request, mode), "mode": mode})

    if glance:
        for pan in (-18, 18, 0):
            actions.append({"turret": _post(request, "/turret", {"pan_deg": pan}), "pan_deg": pan})
            _safe_sleep(0.2, sleep_fn)

    capture = None
    if snapshot:
        capture = _post(request, "/vision/snapshot")
        actions.append({"snapshot": capture})

    return {"ok": True, "status": status, "sensors": sensors, "rgb_mode": mode, "capture": capture, "actions": actions}
