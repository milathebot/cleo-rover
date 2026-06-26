"""Open-loop motion model and dead-reckoning for an encoder-less, IMU-less rover.

There are no wheel encoders and no IMU on this chassis, so every distance/heading
number here is a CALIBRATED GUESS, not a measurement. The point of this module is
to:

* be the single source of truth for converting cm <-> motor-pulse duration (the
  old code had three different magic constants: *95ms in move_step, *55ms in the
  supervisor intent, *20ms in rotate_step), and
* report distance *honestly* with growing uncertainty, so planners stop trusting
  ``travelled_cm`` as if it were ground truth.

Calibrate the coefficients on hardware with a tape measure and a UMBmark-style
square test; the defaults are tuned to reproduce the repo's existing move_step
feel (0.38 duty ~ 95 ms/cm) so behavior is unchanged until you measure better.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class MotionModel:
    """Maps PWM duty + time to approximate forward distance and yaw.

    forward speed:  v_cm_s(duty) = cm_s_per_duty * max(0, |duty| - duty_deadband)
    yaw rate:       w_deg_s(turn) = deg_s_per_turn_duty * max(0, |turn| - turn_deadband)
    """

    cm_s_per_duty: float = 33.0
    duty_deadband: float = 0.08
    deg_s_per_turn_duty: float = 200.0
    turn_deadband: float = 0.10
    dead_time_ms: float = 60.0  # command latency / ramp before motion starts
    min_pulse_ms: float = 60.0
    max_pulse_ms: float = 2000.0
    # Fraction of travelled distance/turn taken as 1-sigma uncertainty (no encoders).
    distance_sigma_frac: float = 0.30
    heading_sigma_frac: float = 0.45

    # --- forward translation -------------------------------------------------
    def speed_cm_s(self, duty: float) -> float:
        return self.cm_s_per_duty * max(0.0, abs(duty) - self.duty_deadband)

    def duration_ms_for_cm(self, cm: float, duty: float) -> float:
        speed = self.speed_cm_s(duty)
        if speed <= 0:
            return self.min_pulse_ms
        ms = abs(cm) / speed * 1000.0 + self.dead_time_ms
        return float(min(self.max_pulse_ms, max(self.min_pulse_ms, ms)))

    def distance_cm_for(self, duty: float, duration_ms: float) -> float:
        moving_ms = max(0.0, float(duration_ms) - self.dead_time_ms)
        return self.speed_cm_s(duty) * moving_ms / 1000.0

    # --- in-place / tank yaw -------------------------------------------------
    def turn_rate_deg_s(self, turn_duty: float) -> float:
        return self.deg_s_per_turn_duty * max(0.0, abs(turn_duty) - self.turn_deadband)

    def duration_ms_for_deg(self, deg: float, turn_duty: float) -> float:
        rate = self.turn_rate_deg_s(turn_duty)
        if rate <= 0:
            return self.min_pulse_ms
        ms = abs(deg) / rate * 1000.0 + self.dead_time_ms
        return float(min(self.max_pulse_ms, max(self.min_pulse_ms, ms)))

    def degrees_for(self, turn_duty: float, duration_ms: float) -> float:
        moving_ms = max(0.0, float(duration_ms) - self.dead_time_ms)
        return self.turn_rate_deg_s(turn_duty) * moving_ms / 1000.0


def calibrate_cm_s_per_duty(*, measured_cm: float, duty: float, duration_ms: float, duty_deadband: float = 0.08, dead_time_ms: float = 60.0) -> float:
    """Invert distance_cm_for: from a measured tape distance for a known forward
    pulse, solve the true cm_s_per_duty. The fix for the ~2x open-loop under-count
    (no encoders) -- drive once, measure, persist."""
    moving_ms = max(1.0, float(duration_ms) - float(dead_time_ms))
    eff_duty = max(1e-6, abs(float(duty)) - float(duty_deadband))
    return float(abs(measured_cm)) / (eff_duty * moving_ms / 1000.0)


def calibrate_deg_s_per_turn_duty(*, measured_deg: float, turn_duty: float, duration_ms: float, turn_deadband: float = 0.10, dead_time_ms: float = 60.0) -> float:
    """Invert degrees_for: from a measured rotation for a known turn pulse, solve
    the true deg_s_per_turn_duty."""
    moving_ms = max(1.0, float(duration_ms) - float(dead_time_ms))
    eff_turn = max(1e-6, abs(float(turn_duty)) - float(turn_deadband))
    return float(abs(measured_deg)) / (eff_turn * moving_ms / 1000.0)


def motion_model_from(cfg) -> MotionModel:
    """Build a MotionModel from an OdometryConfig-shaped object (duck-typed)."""
    return MotionModel(
        cm_s_per_duty=cfg.cm_s_per_duty,
        duty_deadband=cfg.duty_deadband,
        deg_s_per_turn_duty=cfg.deg_s_per_turn_duty,
        turn_deadband=cfg.turn_deadband,
        dead_time_ms=cfg.dead_time_ms,
        distance_sigma_frac=cfg.distance_sigma_frac,
        heading_sigma_frac=cfg.heading_sigma_frac,
    )


@dataclass
class PoseEstimate:
    """Crude dead-reckoned pose with explicit uncertainty (cm, cm, deg).

    Resettable when a reliable feature is seen (a remembered landmark, a line
    crossing). Never treat this as ground truth — read distance_sigma_cm too.
    """

    x_cm: float = 0.0
    y_cm: float = 0.0
    heading_deg: float = 0.0
    distance_sigma_cm: float = 0.0
    heading_sigma_deg: float = 0.0

    def integrate_forward(self, model: MotionModel, distance_cm: float) -> None:
        rad = math.radians(self.heading_deg)
        self.x_cm += distance_cm * math.cos(rad)
        self.y_cm += distance_cm * math.sin(rad)
        self.distance_sigma_cm = math.hypot(self.distance_sigma_cm, abs(distance_cm) * model.distance_sigma_frac)

    def integrate_turn(self, model: MotionModel, delta_deg: float) -> None:
        self.heading_deg = (self.heading_deg + delta_deg + 180.0) % 360.0 - 180.0
        self.heading_sigma_deg = math.hypot(self.heading_sigma_deg, abs(delta_deg) * model.heading_sigma_frac)

    def reset(self, *, x_cm: float = 0.0, y_cm: float = 0.0, heading_deg: float | None = None) -> None:
        self.x_cm = x_cm
        self.y_cm = y_cm
        if heading_deg is not None:
            self.heading_deg = heading_deg
        self.distance_sigma_cm = 0.0
        self.heading_sigma_deg = 0.0


def estimate_chunk_distance_cm(
    *,
    model: MotionModel,
    duty: float,
    duration_ms: float,
    front_before_cm: float | None,
    front_after_cm: float | None,
    max_range_cm: float = 250.0,
) -> dict:
    """Best-effort estimate of how far a forward chunk actually moved.

    Combines the open-loop model with an ultrasonic range-delta against whatever
    is ahead. The range delta is only trusted when there is a surface in usable
    range and it got closer; otherwise we fall back to the model. Also reports a
    stall flag (commanded forward, a near surface ahead, but range did not drop).
    """
    model_cm = model.distance_cm_for(duty, duration_ms)
    have_surface = (
        front_before_cm is not None and front_after_cm is not None and front_before_cm < max_range_cm
    )
    delta_cm = (front_before_cm - front_after_cm) if have_surface else None
    stalled = bool(have_surface and duty > 0 and delta_cm is not None and delta_cm < 0.5)
    if delta_cm is not None and delta_cm > 0:
        # Blend measured delta with the model (delta is only valid head-on; weight it).
        estimated_cm = round(0.6 * delta_cm + 0.4 * model_cm, 1)
        source = "ultrasonic_delta+model"
    else:
        estimated_cm = round(model_cm, 1)
        source = "model_only"
    return {
        "estimated_cm": estimated_cm,
        "model_cm": round(model_cm, 1),
        "range_delta_cm": round(delta_cm, 1) if delta_cm is not None else None,
        "source": source,
        "stalled": stalled,
        "note": "open-loop estimate, no encoders; treat as a guess",
    }
