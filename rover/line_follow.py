"""Pure line-following controller for the 3-sensor IR module.

Indoor companion use, not line-racing: a gentle PD (Kd small, Ki=0 — with only 3
digital sensors there are just a handful of states, so heavy control is pointless)
on a weighted left/center/right error, with explicit line-loss handling.

This module is pure/side-effect-free; the async task in rover/service.py reads the
sensors, calls decide_line_follow(), and drives through the Pi-local safety
primitives. The cliff (downward IR) and ultrasonic/bumper reflexes always
pre-empt line following — safety is never traded for staying on a line.
"""

from __future__ import annotations

SENSOR_WEIGHTS = {"left": -1.0, "center": 0.0, "right": 1.0}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def line_error(line: dict, on_value: int) -> tuple[float | None, int]:
    """Weighted position error from the sensors currently over the line.

    Returns (error in [-1, 1], count). error<0 => line is to the left (steer left),
    error>0 => line is to the right. (None, 0) means the line was lost.
    """
    if not isinstance(line, dict) or not line:
        return None, 0
    on = [name for name, value in line.items() if int(value) == int(on_value)]
    if not on:
        return None, 0
    error = sum(SENSOR_WEIGHTS.get(name, 0.0) for name in on) / len(on)
    return error, len(on)


def decide_line_follow(
    line: dict,
    *,
    on_value: int = 1,
    kp: float = 0.45,
    kd: float = 0.15,
    prev_error: float = 0.0,
    base_linear: float = 0.22,
    max_turn: float = 0.6,
) -> dict:
    """One PD line-follow step. Pure: returns {lost, linear, turn, error, on_count}."""
    error, count = line_error(line, on_value)
    if error is None:
        return {"lost": True, "linear": 0.0, "turn": 0.0, "error": None, "on_count": 0}
    turn = _clamp(kp * error + kd * (error - prev_error), -max_turn, max_turn)
    # Ease off forward speed when correcting hard so Pip does not overshoot a bend.
    linear = base_linear * (1.0 - 0.5 * min(1.0, abs(error)))
    return {"lost": False, "linear": round(linear, 3), "turn": round(turn, 3), "error": error, "on_count": count}


def search_turn(prev_error: float, magnitude: float = 0.3) -> float:
    """When the line is lost, sweep toward the side it was last seen."""
    return magnitude if prev_error >= 0 else -magnitude
