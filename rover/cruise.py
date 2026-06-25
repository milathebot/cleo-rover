"""Continuous "cruise" motion: the consumer that turns a fresh PolarSnapshot into
smooth, non-stop driving (Pip flows instead of lurching scan->stop->move->scan).

This is the CONSUMER half (producer = ``rover/perception.py``). The pure policy
``steer_to_command`` decides, each tick, a continuous (linear, turn) -- or a stop
-- from the latest world-model, VFH steering, optical-flow looming, and the grant.
``cruise_task`` is the thin loop that calls it and re-issues short drive pulses.

SAFETY MODEL (advisory layer; can only make Pip do LESS):
* The ONLY authorities that stop Pip are Tier-1 (ultrasonic/cliff/bumper reflex,
  watchdog, the bearing guard) plus the cruise stops below; advisory inputs
  (VFH/flow) only slow or steer.
* ``cruise_speed_cap`` is the single source of truth for max speed, derived from a
  braking-distance inequality so Pip can always stop within ``reflex_hard_cm``
  given the forward-ping cadence. The policy never emits more than the cap.
* Forward motion is gated on a FRESH forward cell AND a centred turret; a stale
  snapshot or a dead producer degrades to a stop, never a blind run.

Pure + no numpy; fully unit-tested. ``cruise_task`` is pragma: no cover.
"""

from __future__ import annotations

from dataclasses import dataclass

ACTION_DRIVE = "drive"
ACTION_STOP = "stop"


@dataclass(frozen=True)
class CruiseParams:
    max_linear: float = 0.20  # normalized duty cap (matches today's crawl_linear)
    forward_cone_deg: float = 20.0
    fwd_stale_ms: float = 700.0  # forward cone older than this -> stop
    slowdown_start_cm: float = 60.0  # begin proportional slow-down below this
    reflex_hard_cm: float = 30.0  # the Tier-1 stop distance (for braking math + ramp floor)
    coast_cm: float = 8.0  # measured coast after PWM cut (calibrate on HW)
    margin_cm: float = 4.0
    weave_settle_ms: float = 90.0
    ping_latency_ms: float = 50.0
    react_ms: float = 70.0  # drive_monitor tick + ping latency
    cm_s_per_duty: float = 33.0  # from odometry model (duty -> cm/s)
    duty_deadband: float = 0.08
    max_turn: float = 0.5
    turn_gain: float = 0.012  # chosen bearing deg -> normalized turn
    pan_guard_deg: float = 5.0
    cornered_confirm: int = 2  # consecutive blocked reads before declaring cornered
    flow_ttc_brake_frames: float = 12.0  # below this looming TTC, halve speed
    pulse_ms: int = 200  # short re-issued pulse so the watchdog deadline still bounds it


def grant_permits(grant: dict | None, owner: str) -> bool:
    """True if an active grant lets `owner` drive: the grant must be active and
    either ownerless or owned by `owner`. A foreign owner means cruise yields
    (stops) rather than driving under another task's caps (audit I-3)."""
    if not grant or not grant.get("active"):
        return False
    g_owner = grant.get("owner")
    return g_owner is None or g_owner == owner


def t_forward_s(p: CruiseParams) -> float:
    """Worst-case seconds between two forward-cone pings (one side excursion + return)."""
    return 2.0 * (p.weave_settle_ms + p.ping_latency_ms) / 1000.0


def cruise_speed_cap_cm_s(p: CruiseParams) -> float:
    """Max safe cruise speed (cm/s) from the braking inequality:
    v*(T_forward + T_react) + coast + margin <= reflex_hard_cm."""
    denom = t_forward_s(p) + p.react_ms / 1000.0
    if denom <= 0:
        return 0.0
    return max(0.0, (p.reflex_hard_cm - p.coast_cm - p.margin_cm) / denom)


def linear_for_cm_s(v_cm_s: float, p: CruiseParams) -> float:
    """Invert the odometry speed model: cm/s -> normalized duty."""
    if p.cm_s_per_duty <= 0:
        return 0.0
    return max(0.0, v_cm_s / p.cm_s_per_duty + p.duty_deadband)


def cruise_speed_cap(p: CruiseParams) -> float:
    """Single source of truth for the normalized linear speed cap: the lesser of the
    configured max and the braking-inequality bound."""
    return min(p.max_linear, linear_for_cm_s(cruise_speed_cap_cm_s(p), p))


@dataclass(frozen=True)
class CruiseDecision:
    action: str
    linear: float
    turn: float
    stop: bool
    reason: str
    cornered_streak: int
    cornered: bool = False
    speed_cap: float = 0.0


def _stop(reason: str, streak: int, *, cornered: bool = False, cap: float = 0.0) -> CruiseDecision:
    return CruiseDecision(ACTION_STOP, 0.0, 0.0, True, reason, streak, cornered, cap)


def steer_to_command(
    *,
    chosen_bearing_deg: float | None,
    blocked: bool,
    fwd_min_cm: float | None,
    fwd_worst_age_ms: float,
    grant_active: bool,
    pan_deg: float,
    params: CruiseParams,
    cornered_streak: int = 0,
    flow_ttc_frames: float | None = None,
    flow_stalled: bool = False,
) -> CruiseDecision:
    """Decide one continuous cruise step (pure). Returns a drive or a stop.

    ``chosen_bearing_deg``/``blocked`` come from ``vfh.steer`` on the snapshot.
    ``fwd_min_cm``/``fwd_worst_age_ms`` from ``PolarSnapshot.fwd_cone``.
    """
    cap = cruise_speed_cap(params)

    # --- hard gates: only ever make Pip do less -------------------------------
    if not grant_active:
        return _stop("no movement grant", 0, cap=cap)
    if abs(float(pan_deg)) > params.pan_guard_deg:
        # Defense in depth above the Tier-1 bearing guard.
        return _stop(f"turret panned {pan_deg:.0f}deg; not looking ahead", cornered_streak, cap=cap)
    if fwd_worst_age_ms > params.fwd_stale_ms:
        return _stop("forward range stale; waiting for a fresh ping", cornered_streak, cap=cap)

    # --- cornered (no open gap), with hysteresis ------------------------------
    if blocked or chosen_bearing_deg is None:
        streak = cornered_streak + 1
        if streak >= params.cornered_confirm:
            return _stop("cornered: no open gap; rescan/turn in place", streak, cornered=True, cap=cap)
        return _stop("blocked (confirming before declaring cornered)", streak, cap=cap)

    # --- continuous drive: speed ramps, never freezes -------------------------
    v = cap
    if fwd_min_cm is not None and fwd_min_cm < params.slowdown_start_cm:
        span = max(1.0, params.slowdown_start_cm - params.reflex_hard_cm)
        frac = (fwd_min_cm - params.reflex_hard_cm) / span
        v = cap * max(0.0, min(1.0, frac))  # 0 at the reflex floor, full by slowdown_start
    if flow_stalled:
        v = min(v, cap * 0.3)
    if flow_ttc_frames is not None and flow_ttc_frames < params.flow_ttc_brake_frames:
        v *= 0.5
    v = max(0.0, min(cap, v))

    turn = max(-params.max_turn, min(params.max_turn, float(chosen_bearing_deg) * params.turn_gain))
    reason = f"cruise v={v:.2f} turn={turn:+.2f} toward {chosen_bearing_deg:+.0f}deg (cap {cap:.2f})"
    return CruiseDecision(ACTION_DRIVE, round(v, 3), round(turn, 3), False, reason, 0, False, cap)


def cruise_params_from(nav, odometry, safety) -> CruiseParams:
    """Build CruiseParams from NavConfig + OdometryConfig + SafetyConfig (duck-typed)."""
    return CruiseParams(
        max_linear=nav.cruise_max_linear,
        forward_cone_deg=nav.forward_cone_deg,
        fwd_stale_ms=nav.fwd_stale_ms,
        slowdown_start_cm=nav.slowdown_start_cm,
        reflex_hard_cm=max(float(safety.reflex_hard_cm), float(safety.front_stop_distance_cm)),
        coast_cm=nav.cruise_coast_cm,
        margin_cm=nav.cruise_margin_cm,
        weave_settle_ms=nav.weave_settle_ms,
        ping_latency_ms=nav.ping_latency_ms,
        react_ms=nav.cruise_react_ms,
        cm_s_per_duty=odometry.cm_s_per_duty,
        duty_deadband=odometry.duty_deadband,
        max_turn=nav.cruise_max_turn,
        pan_guard_deg=float(safety.forward_cone_guard_deg),
        cornered_confirm=nav.cruise_cornered_confirm,
        pulse_ms=nav.cruise_pulse_ms,
    )


async def cruise_task(  # pragma: no cover - thin hardware loop
    body,
    snapshot,
    *,
    vfh_cfg,
    params: CruiseParams,
    grant_active_fn,
    guarded_drive,
    now_fn,
    stop_event,
    flow_fn=None,
    tick_ms: float = 100.0,
):
    """Continuous drive loop: snapshot -> vfh.steer -> steer_to_command -> short pulse.

    Re-issues a short pulse each tick (bounded by the watchdog deadline). On a
    'cornered' decision it stops + turns in place for a fresh sweep. Tier-1 +
    the bearing guard remain the authoritative stops underneath every pulse.
    """
    import asyncio

    from . import vfh as vfh_mod
    from .models import DriveCommand

    cornered_streak = 0
    while not stop_event.is_set():
        now = now_fn()
        samples = snapshot.vfh_samples(now)
        steer = vfh_mod.steer(samples, cfg=vfh_cfg, target_bearing_deg=0.0)
        fwd_min, fwd_age = snapshot.fwd_cone(now, half_deg=params.forward_cone_deg, max_age_ms=params.fwd_stale_ms)
        ttc, stalled = (None, False)
        if flow_fn is not None:
            fs = flow_fn()
            if fs is not None:
                ttc, stalled = fs.ttc_frames, fs.stalled
        decision = steer_to_command(
            chosen_bearing_deg=steer.chosen_bearing_deg,
            blocked=steer.blocked,
            fwd_min_cm=fwd_min,
            fwd_worst_age_ms=fwd_age,
            grant_active=grant_active_fn(),
            pan_deg=getattr(body.state.turret, "pan_deg", 0.0),
            params=params,
            cornered_streak=cornered_streak,
            flow_ttc_frames=ttc,
            flow_stalled=stalled,
        )
        cornered_streak = decision.cornered_streak
        if decision.stop:
            await body.stop()
            if decision.cornered:
                # Turn in place to look for a new opening (no forward motion).
                await guarded_drive(DriveCommand(linear=0.0, turn=params.max_turn, duration_ms=params.pulse_ms), require_permission=True)
        else:
            await guarded_drive(DriveCommand(linear=decision.linear, turn=decision.turn, duration_ms=params.pulse_ms), require_permission=True)
        await asyncio.sleep(tick_ms / 1000.0)
