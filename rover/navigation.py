"""Pure doorway/hallway navigation decision logic.

This module is deliberately free of FastAPI, hardware, async, and global state so
it can be exhaustively unit-tested. The async hallway-scout task in
``rover/service.py`` gathers sensor/scan inputs, calls :func:`decide_hallway_action`
for the per-cycle decision, then executes the returned action through the
Pi-local safety primitives.

Design (fixes the "turns randomly ~20cm before a doorway" bug):

* **Scan-center is the source of truth** for forward clearance. The raw,
  turret-mounted ultrasonic reading is only used as a hard-emergency floor, so a
  single off-axis/transient ping can no longer veto a fresh, centered scan.
* **Ordered bands** ``emergency_cm < blocked_cm < clear_cm`` create a real *creep*
  band (``blocked_cm..clear_cm``) for threading an open doorway, instead of the
  old dead-zone that turned away whenever Pip got close.
* **Hysteresis**: a recovery turn needs ``confirm_blocked`` consecutive fresh
  blocked reads (a single bad read holds, it does not turn); ``confirm_clear``
  consecutive clear reads mark the doorway *exited*.
* **Fresh reflex only**: the caller passes whether a *new* reflex event fired
  (see ``RoverBody.consume_reflex_stop``); a retained stale reflex never inflates
  the blocked streak again.
"""

from __future__ import annotations

from dataclasses import dataclass

# Actions the hallway-scout executor knows how to perform.
ACTION_EMERGENCY_ESCAPE = "emergency-escape"
ACTION_SCAN_TURN = "scan-turn"
ACTION_ALIGN_TURN = "align-turn"
ACTION_CREEP = "doorway-creep"
ACTION_ADVANCE = "adaptive-move"
ACTION_HOLD = "hold"

# Minimum off-axis bearing (deg) that counts as a genuine "side opening" rather
# than centered noise, before Pip will turn to line up with it.
SIDE_BEARING_MIN_DEG = 18.0


@dataclass(frozen=True)
class DoorwayBands:
    """Ordered forward-clearance thresholds (cm). emergency < blocked < clear."""

    emergency_cm: float
    blocked_cm: float
    clear_cm: float
    reflex_hard_cm: float

    def __post_init__(self) -> None:
        if not (self.emergency_cm < self.blocked_cm < self.clear_cm):
            raise ValueError(f"DoorwayBands must satisfy emergency_cm < blocked_cm < clear_cm (got {self.emergency_cm}, {self.blocked_cm}, {self.clear_cm})")


@dataclass(frozen=True)
class DoorwayDecision:
    action: str
    reason: str
    phase: str  # approach | creep | align | recover | exit
    decision_front_cm: float | None
    raw_front_cm: float | None
    scan_center_cm: float | None
    best_bearing_deg: float | None
    best_distance_cm: float | None
    blocked_streak: int
    clear_streak: int
    planned_step_cm: float | None = None


def _has_better_side(
    *, decision_front_cm: float | None, best_bearing_deg: float | None, best_distance_cm: float | None, side_gain_cm: float
) -> bool:
    if decision_front_cm is None or best_bearing_deg is None or best_distance_cm is None:
        return False
    return abs(best_bearing_deg) >= SIDE_BEARING_MIN_DEG and best_distance_cm > decision_front_cm + side_gain_cm


def decide_hallway_action(
    *,
    raw_front_cm: float | None,
    scan_center_cm: float | None,
    best_bearing_deg: float | None,
    best_distance_cm: float | None,
    fresh_reflex: bool,
    blocked_streak: int,
    clear_streak: int,
    bands: DoorwayBands,
    side_gain_cm: float,
    confirm_blocked: int,
    confirm_clear: int,
    creep_step_cm: float,
    vision_block: bool = False,
) -> DoorwayDecision:
    """Decide one hallway-scout cycle's action. Pure function (no side effects).

    vision_block is an ADVISORY cue from camera perception: when True, any forward
    motion (advance/creep) is downgraded to HOLD. It can only add caution; it
    never relaxes the ultrasonic/cliff/bumper reflexes or turns Pip.
    """

    # Scan-center is primary; raw front is only a fallback when no scan exists.
    decision_front = scan_center_cm if scan_center_cm is not None else raw_front_cm
    better_side = _has_better_side(
        decision_front_cm=decision_front,
        best_bearing_deg=best_bearing_deg,
        best_distance_cm=best_distance_cm,
        side_gain_cm=side_gain_cm,
    )
    raw_hard = raw_front_cm is not None and raw_front_cm < bands.reflex_hard_cm

    def make(action, reason, phase, *, blocked, clear, step=None) -> DoorwayDecision:
        if vision_block and action in (ACTION_ADVANCE, ACTION_CREEP):
            # Camera advisory: do not move forward, but keep safety/turn logic intact.
            action, step = ACTION_HOLD, None
            reason = f"vision: path not clear ahead; holding ({reason})"
        return DoorwayDecision(
            action=action,
            reason=reason,
            phase=phase,
            decision_front_cm=decision_front,
            raw_front_cm=raw_front_cm,
            scan_center_cm=scan_center_cm,
            best_bearing_deg=best_bearing_deg,
            best_distance_cm=best_distance_cm,
            blocked_streak=blocked,
            clear_streak=clear,
            planned_step_cm=step,
        )

    # No usable clearance -> conservative search; counts toward blocked streak.
    if decision_front is None:
        return make(ACTION_SCAN_TURN, "front range unknown; scanning for an opening", "recover", blocked=blocked_streak + 1, clear=0)

    # Emergency: a fresh reflex, a raw reading inside the hard floor, or the
    # decided clearance below the emergency band. Escape immediately.
    if fresh_reflex or raw_hard or decision_front < bands.emergency_cm:
        if fresh_reflex:
            reason = "fresh reflex stop fired"
        elif raw_hard:
            reason = f"raw front {raw_front_cm:.1f}cm below reflex floor {bands.reflex_hard_cm:.1f}cm"
        else:
            reason = f"decision front {decision_front:.1f}cm below emergency {bands.emergency_cm:.1f}cm"
        return make(ACTION_EMERGENCY_ESCAPE, reason, "recover", blocked=blocked_streak + 1, clear=0)

    # Blocked: too close to advance. Hysteresis — need confirm_blocked consecutive
    # fresh blocked reads (or a clearly better side) before committing to a turn;
    # otherwise hold and re-confirm next cycle so one bad read cannot spin Pip.
    if decision_front < bands.blocked_cm:
        streak = blocked_streak + 1
        if streak >= confirm_blocked or better_side:
            reason = (
                f"better opening {best_distance_cm:.1f}cm at {best_bearing_deg:.0f}deg while blocked {decision_front:.1f}cm"
                if better_side
                else f"blocked {decision_front:.1f}cm confirmed (streak {streak})"
            )
            return make(ACTION_SCAN_TURN, reason, "recover", blocked=streak, clear=0)
        return make(ACTION_HOLD, f"first blocked read {decision_front:.1f}cm; confirming before any turn", "creep", blocked=streak, clear=0)

    # Creep band: close but open ahead -> thread the doorway. Turn only for a
    # clearly better side opening; otherwise creep straight. THIS is the fix for
    # the old dead-zone that turned away from open doorways.
    if decision_front < bands.clear_cm:
        if better_side:
            return make(
                ACTION_ALIGN_TURN,
                f"clearer opening {best_distance_cm:.1f}cm at {best_bearing_deg:.0f}deg; lining up",
                "align",
                blocked=blocked_streak,
                clear=0,
            )
        return make(ACTION_CREEP, f"doorway open ahead at {decision_front:.1f}cm; creeping", "creep", blocked=0, clear=0, step=creep_step_cm)

    # Clear: full adaptive stride, unless a much better side exists.
    if better_side:
        return make(
            ACTION_ALIGN_TURN,
            f"path clear but better side {best_distance_cm:.1f}cm at {best_bearing_deg:.0f}deg",
            "approach",
            blocked=blocked_streak,
            clear=0,
        )
    streak_clear = clear_streak + 1
    phase = "exit" if streak_clear >= confirm_clear else "approach"
    return make(ACTION_ADVANCE, f"path clear at {decision_front:.1f}cm", phase, blocked=0, clear=streak_clear)
