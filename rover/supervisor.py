from __future__ import annotations

import time
from typing import Any

from .awareness import range_state_from_samples
from .choreo import rgb_payload
from .models import BodyIntentCommand, DriveCommand, ExpressionCommand, ExpressionMode, TurretCommand

SAFE_INTENTS = {"status", "stop", "scan", "look", "say", "mood", "move_step", "rotate_step", "idle"}
MOOD_TO_EXPRESSION: dict[str, ExpressionMode] = {
    "idle": ExpressionMode.idle,
    "happy": ExpressionMode.happy,
    "sad": ExpressionMode.sad,
    "alert": ExpressionMode.alert,
    "thinking": ExpressionMode.thinking,
    "confused": ExpressionMode.confused,
    "speaking": ExpressionMode.speaking,
    "mad": ExpressionMode.mad,
    "focused": ExpressionMode.focused,
    "laugh": ExpressionMode.laugh,
}
MOOD_TO_RGB: dict[str, dict[str, int]] = {
    "idle": rgb_payload("idle"),
    "happy": {"red": 80, "green": 255, "blue": 180, "brightness": 26},
    "sad": {"red": 20, "green": 40, "blue": 180, "brightness": 16},
    "alert": {"red": 255, "green": 80, "blue": 0, "brightness": 32},
    "thinking": {"red": 130, "green": 40, "blue": 255, "brightness": 22},
    "confused": {"red": 255, "green": 180, "blue": 40, "brightness": 22},
    "speaking": {"red": 255, "green": 70, "blue": 190, "brightness": 24},
    "mad": {"red": 255, "green": 0, "blue": 40, "brightness": 30},
    "focused": {"red": 40, "green": 170, "blue": 255, "brightness": 24},
    "laugh": {"red": 255, "green": 120, "blue": 255, "brightness": 28},
}


def normalize_mood(mood: str | None) -> str:
    value = (mood or "idle").strip().lower().replace(" ", "_")
    return value if value in MOOD_TO_EXPRESSION else "confused"


def mood_expression(mood: str, text: str | None = None, brightness: float = 0.6) -> ExpressionCommand:
    mood = normalize_mood(mood)
    return ExpressionCommand(mode=MOOD_TO_EXPRESSION[mood], text=text or mood, brightness=brightness)


def supervisor_snapshot(*, status: dict[str, Any], sensors: dict[str, Any], movement: dict[str, Any], autonomy: dict[str, Any] | None = None) -> dict[str, Any]:
    range_state = range_state_from_samples([sensors.get("front_distance_cm")], stop_cm=float(sensors.get("front_stop_distance_cm") or 45.0))
    active = bool(movement.get("active"))
    safety_flags = []
    if status.get("motors_armed") and status.get("safety", {}).get("bench_safe_no_motors"):
        safety_flags.append("inconsistent_motor_safety")
    if range_state["state"] in {"blocked", "near"}:
        safety_flags.append(f"front_{range_state['state']}")
    if sensors.get("errors"):
        safety_flags.append("sensor_errors")
    return {
        "ok": not safety_flags,
        "role": "pi_body_agent",
        "mode": "supervised_body",
        "time": time.time(),
        "safety_flags": safety_flags,
        "range_state": range_state,
        "movement_active": active,
        "status": status,
        "sensors": sensors,
        "movement": movement,
        "autonomy": autonomy,
        "contract": {
            "brain_sends": "high-level intents only",
            "pi_may_refuse": True,
            "hard_rule": "local safety and estop beat PC/Hermes commands",
        },
    }


def validate_intent(command: BodyIntentCommand, *, status: dict[str, Any], sensors: dict[str, Any], movement: dict[str, Any]) -> tuple[bool, str]:
    if command.intent not in SAFE_INTENTS:
        return False, f"unknown intent {command.intent!r}"
    if command.intent in {"move_step", "rotate_step"}:
        if not movement.get("active"):
            return False, "movement intent rejected: no active movement grant"
        if not status.get("motors_armed"):
            return False, "movement intent rejected: motors are not armed"
        if status.get("safety", {}).get("bench_safe_no_motors"):
            return False, "movement intent rejected: bench_safe_no_motors=true"
    if command.intent == "move_step":
        distance = sensors.get("front_distance_cm")
        threshold = max(70.0, float(sensors.get("front_stop_distance_cm") or 18.0) + 45.0)
        if distance is None:
            return False, "forward move rejected: front range unknown"
        if float(distance) < threshold:
            return False, f"forward move rejected: front obstacle at {distance}cm below {threshold}cm"
    return True, "intent accepted"


def intent_to_actions(command: BodyIntentCommand) -> list[dict[str, Any]]:
    p = command.params or {}
    mood = normalize_mood(command.mood)
    actions: list[dict[str, Any]] = []
    if command.mood:
        actions.append({"kind": "expression", "command": mood_expression(mood, text=command.speech or mood).model_dump()})
        actions.append({"kind": "rgb", "command": MOOD_TO_RGB[mood]})
    if command.intent == "stop":
        actions.append({"kind": "stop", "command": {}})
    elif command.intent == "scan":
        actions.append({"kind": "scan", "command": {"zone": str(p.get("zone", "unknown")), "angles": p.get("angles", [-35, 0, 35]), "settle_ms": int(p.get("settle_ms", 250)), "snapshot_center": bool(p.get("snapshot_center", False))}})
    elif command.intent == "look":
        actions.append({"kind": "turret", "command": TurretCommand(pan_deg=float(p.get("pan_deg", 0))).model_dump()})
    elif command.intent == "move_step":
        forward_cm = max(-12.0, min(12.0, float(p.get("forward_cm", 8))))
        # Floor testing showed the old 120ms 3cm pulse mostly buzzed. Keep the
        # command tiny, but long enough to overcome static friction.
        linear = 0.34 if forward_cm >= 0 else -0.30
        duration = int(min(360, max(220, abs(forward_cm) * 55)))
        actions.append({"kind": "drive", "command": DriveCommand(linear=linear, turn=0, duration_ms=duration).model_dump()})
    elif command.intent == "rotate_step":
        # Escape turns must be small. A 25deg request at 0.65/550ms spun far
        # too much during floor autonomy, so supervised turns are deliberately
        # gentle and should be followed by another scan.
        deg = max(-35.0, min(35.0, float(p.get("deg", 10))))
        turn = 0.45 if deg >= 0 else -0.45
        duration = int(min(320, max(120, abs(deg) * 12)))
        actions.append({"kind": "drive", "command": DriveCommand(linear=0, turn=turn, duration_ms=duration).model_dump()})
    elif command.intent in {"say", "mood", "idle", "status"}:
        pass
    return actions
