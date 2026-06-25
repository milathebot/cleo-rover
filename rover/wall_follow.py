"""PD wall-following with corner handling for a panning-sonar rover.

Wall-following is Pip's most *reliable* systematic-coverage behaviour because it
references a physical feature (the wall) instead of dead-reckoned coordinates,
which drift without encoders/IMU. Left- (or right-) hand wall-following with
corner handling traces a room's perimeter and -- for a simply-connected room --
returns to where it started, giving deterministic boundary coverage with no
global pose at all (the maze "wall rule").

Pure + side-effect-free. The async loop parks the panning sonar to the side for a
perpendicular reading (and occasionally forward for inside-corner detection),
calls :func:`wall_follow_step`, and drives the result through the Pi-local safety
primitives. Like all nav layers here it is ADVISORY -- the reflex/cliff/bumper
stops stay authoritative and can override any command below.

Turn convention: ``turn > 0`` steers LEFT (counter-clockwise), ``turn < 0`` steers
RIGHT, matching the rest of the body service. ``side`` selects which wall to hug.
"""

from __future__ import annotations

from dataclasses import dataclass

ACTION_FOLLOW = "follow"
ACTION_INSIDE_CORNER = "inside_corner"
ACTION_OUTSIDE_CORNER = "outside_corner"
ACTION_SEARCH = "search_wall"


@dataclass(frozen=True)
class WallFollowConfig:
    setpoint_cm: float = 25.0  # desired perpendicular distance to the wall
    kp: float = 2.0  # proportional gain (turn per cm of error)
    kd: float = 8.0  # derivative gain (damping; sonar is slow+noisy, so kd dominant)
    turn_gain: float = 0.02  # maps PD output (cm) -> normalized turn command
    deadband_cm: float = 3.0  # within this of setpoint, go straight (no buzzing)
    max_turn: float = 0.5
    base_linear: float = 0.18  # modest: the slow sonar must keep up
    inside_corner_front_cm: float = 35.0  # front ping below this => wall ahead (inside corner)
    outside_corner_jump_cm: float = 40.0  # side beyond setpoint+this => wall ended (outside corner)
    lost_wall_cm: float = 150.0  # side beyond this (or None) => no wall to follow

    def __post_init__(self) -> None:
        if self.setpoint_cm <= 0 or self.max_turn <= 0:
            raise ValueError("setpoint_cm and max_turn must be positive")


def wall_follow_config_from(cfg) -> WallFollowConfig:
    """Build a WallFollowConfig from a NavConfig-shaped object (duck-typed)."""
    return WallFollowConfig(
        setpoint_cm=cfg.wall_setpoint_cm,
        kp=cfg.wall_kp,
        kd=cfg.wall_kd,
        deadband_cm=cfg.wall_deadband_cm,
        max_turn=cfg.wall_max_turn,
        base_linear=cfg.wall_base_linear,
        inside_corner_front_cm=cfg.wall_inside_corner_front_cm,
        outside_corner_jump_cm=cfg.wall_outside_corner_jump_cm,
    )


@dataclass(frozen=True)
class WallFollowDecision:
    action: str
    linear: float
    turn: float
    error_cm: float | None  # side - setpoint (positive = too far from wall); None if no wall
    reason: str


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def wall_follow_step(
    *,
    side_cm: float | None,
    front_cm: float | None,
    prev_error_cm: float | None,
    side: str = "left",
    cfg: WallFollowConfig | None = None,
) -> WallFollowDecision:
    """One wall-following control step.

    ``side_cm``  = perpendicular distance to the followed wall (None = no echo).
    ``front_cm`` = forward distance (for inside-corner detection; None = unknown).
    ``prev_error_cm`` = last cycle's error, for the derivative term (None = 0).
    """
    cfg = cfg or WallFollowConfig()
    wall_sign = 1.0 if side == "left" else -1.0  # +1 => turning toward a LEFT wall is +turn

    # 1) Inside corner: a wall ahead. Stop, pivot AWAY from the followed wall
    #    until the front clears. Highest priority of the nav actions.
    if front_cm is not None and front_cm < cfg.inside_corner_front_cm:
        return WallFollowDecision(
            action=ACTION_INSIDE_CORNER,
            linear=0.0,
            turn=-wall_sign * cfg.max_turn,
            error_cm=(None if side_cm is None else round(side_cm - cfg.setpoint_cm, 1)),
            reason=f"wall ahead {front_cm:.0f}cm < {cfg.inside_corner_front_cm:.0f}cm; pivoting away from {side} wall",
        )

    # 2) Wall lost / outside corner: the side opened up (end of a wall). Round it:
    #    creep forward and curve gently toward where the wall was, to re-acquire.
    if side_cm is None or side_cm > cfg.setpoint_cm + cfg.outside_corner_jump_cm:
        lost = side_cm is None or side_cm > cfg.lost_wall_cm
        return WallFollowDecision(
            action=ACTION_SEARCH if lost else ACTION_OUTSIDE_CORNER,
            linear=cfg.base_linear * (0.6 if lost else 0.8),
            turn=wall_sign * cfg.max_turn * 0.6,  # curve toward the wall side
            error_cm=None,
            reason=("no wall reading; searching toward " + side) if lost else f"wall ended (side {side_cm:.0f}cm); rounding outside corner",
        )

    # 3) Normal PD following on the perpendicular error.
    error = side_cm - cfg.setpoint_cm  # >0 too far from wall, <0 too close
    prev = 0.0 if prev_error_cm is None else prev_error_cm
    de = error - prev
    if abs(error) <= cfg.deadband_cm:
        return WallFollowDecision(
            action=ACTION_FOLLOW, linear=cfg.base_linear, turn=0.0, error_cm=round(error, 1),
            reason=f"on setpoint ({side_cm:.0f}cm ~= {cfg.setpoint_cm:.0f}cm)",
        )
    raw = cfg.kp * error + cfg.kd * de  # PD output in cm-ish units
    # error>0 (too far) -> steer TOWARD the wall (+wall_sign); error<0 -> away.
    turn = _clamp(wall_sign * raw * cfg.turn_gain, -cfg.max_turn, cfg.max_turn)
    return WallFollowDecision(
        action=ACTION_FOLLOW,
        linear=cfg.base_linear,
        turn=round(turn, 3),
        error_cm=round(error, 1),
        reason=f"PD correcting {error:+.0f}cm toward {side} wall",
    )
