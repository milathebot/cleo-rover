"""VFH+ polar-histogram steering from a single panning-sonar sweep.

This is the reactive *steering* layer (Borenstein/Koren VFH; Ulrich/Borenstein
VFH+). Given one sonar sweep -- a list of ``(bearing_deg, distance_cm)`` samples
relative to Pip's heading -- it picks a steering bearing toward the best gap that
still clears the robot's width, with hysteresis so it does not dither and a cost
function so it commits toward a goal instead of oscillating between equal gaps.

Why this over the old widest-gap band heuristic:

* **Body frame, so drift cannot corrupt it.** It consumes the raw sweep directly;
  no global pose, no map. Open-loop odometry error is irrelevant to one decision.
* **Robot-width compensation.** Each obstacle is angularly enlarged by
  ``gamma = asin(r_safe / d)`` so Pip never aims at a gap narrower than itself.
* **Hysteresis (tau_low/tau_high)** removes the single-threshold oscillation that
  made the old code turn away ~20 cm before a doorway.
* **Cost function (goal / current-heading / previous-choice)** gives commitment,
  so Pip threads a doorway instead of flip-flopping between its two edges.
* **Unscanned bearings are treated as blocked, not free** -- a sparse sweep must
  not lunge into a direction it never looked at.

Pure + side-effect-free: the async explore loop in ``service.py`` gathers the
sweep, calls :func:`steer`, then drives the result through the same Pi-local
safety primitives (grant + armed motors + reflex). VFH is ADVISORY; it can only
choose among already-safe motions, never relax a reflex.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class VFHConfig:
    fov_deg: float = 90.0  # consider steering within +/- this (sonar can't see behind)
    sector_deg: float = 12.0  # angular resolution; honest for a sparse sweep
    a: float = 4.0  # obstacle magnitude scale; m = a*(1 - d/d_max), clamped >= 0
    d_max_cm: float = 180.0  # trust horizon; readings >= this are "open"
    tau_low: float = 1.5  # binary-histogram hysteresis: free below
    tau_high: float = 3.0  # blocked above; between => keep previous (cautious)
    s_max_sectors: int = 6  # an opening wider than this is "wide" (steer to an edge)
    robot_radius_cm: float = 12.0
    safety_cm: float = 12.0  # r_safe = robot_radius + safety
    mu_target: float = 5.0  # cost weight: deviation from goal bearing
    mu_current: float = 2.0  # cost weight: deviation from current heading
    mu_previous: float = 2.0  # cost weight: deviation from previous choice
    coverage_factor: float = 1.5  # a sector is "covered" within sector_deg*this of a sample

    def __post_init__(self) -> None:
        if self.sector_deg <= 0 or self.fov_deg <= 0:
            raise ValueError("sector_deg and fov_deg must be positive")
        # VFH+ requires mu_target > mu_current + mu_previous for goal-seeking.
        if not (self.mu_target > self.mu_current + self.mu_previous):
            raise ValueError("require mu_target > mu_current + mu_previous (VFH+ condition)")


def vfh_config_from(cfg) -> VFHConfig:
    """Build a VFHConfig from a NavConfig-shaped object (duck-typed)."""
    return VFHConfig(
        fov_deg=cfg.vfh_fov_deg,
        sector_deg=cfg.vfh_sector_deg,
        a=cfg.vfh_a,
        d_max_cm=cfg.vfh_d_max_cm,
        tau_low=cfg.vfh_tau_low,
        tau_high=cfg.vfh_tau_high,
        s_max_sectors=cfg.vfh_s_max_sectors,
        robot_radius_cm=cfg.vfh_robot_radius_cm,
        safety_cm=cfg.vfh_safety_cm,
        mu_target=cfg.vfh_mu_target,
        mu_current=cfg.vfh_mu_current,
        mu_previous=cfg.vfh_mu_previous,
    )


@dataclass(frozen=True)
class VFHResult:
    chosen_bearing_deg: float | None  # None => fully blocked, caller should spin/rescan
    blocked: bool
    reason: str
    density: list[float]  # primary polar histogram (per sector)
    binary: list[int]  # 1 = blocked/unknown, 0 = free
    free_runs: list[tuple[float, float]]  # (start_bearing, end_bearing) of free openings
    candidates: list[float] = field(default_factory=list)  # candidate bearings considered


def _n_sectors(cfg: VFHConfig) -> int:
    return max(1, int(round(2.0 * cfg.fov_deg / cfg.sector_deg)))


def _sector_center(cfg: VFHConfig, i: int) -> float:
    return -cfg.fov_deg + (i + 0.5) * cfg.sector_deg


def _sector_of(cfg: VFHConfig, bearing_deg: float, n: int) -> int:
    i = int((float(bearing_deg) + cfg.fov_deg) / cfg.sector_deg)
    return max(0, min(n - 1, i))


def build_histogram(samples: list[tuple[float, float | None]], cfg: VFHConfig) -> tuple[list[float], list[bool]]:
    """Return (density, covered) per sector from a sonar sweep.

    Each obstacle deposits ``a*(1 - d/d_max)`` into every sector within its
    width-enlarged footprint. A sector that no sample looked at is left
    *uncovered* (the caller treats it as blocked).
    """
    n = _n_sectors(cfg)
    density = [0.0] * n
    covered = [False] * n
    r_safe = cfg.robot_radius_cm + cfg.safety_cm
    cover_deg = cfg.sector_deg * cfg.coverage_factor
    for bearing, distance in samples:
        if bearing < -cfg.fov_deg - cfg.sector_deg or bearing > cfg.fov_deg + cfg.sector_deg:
            continue
        # Mark the directly-looked-at sectors as covered (an open reading clears them).
        for i in range(n):
            if abs(_sector_center(cfg, i) - bearing) <= cover_deg:
                covered[i] = True
        if distance is None or distance >= cfg.d_max_cm:
            continue  # open / no echo -> no obstacle magnitude
        d = max(1.0, float(distance))
        m = cfg.a * max(0.0, 1.0 - d / cfg.d_max_cm)
        if m <= 0:
            continue
        ratio = min(1.0, r_safe / d)
        gamma = math.degrees(math.asin(ratio))  # robot-width enlargement half-angle
        lo, hi = bearing - gamma, bearing + gamma
        for i in range(n):
            c = _sector_center(cfg, i)
            if lo <= c <= hi:
                density[i] += m
                covered[i] = True
    return density, covered


def binary_histogram(
    density: list[float], covered: list[bool], cfg: VFHConfig, prev_binary: list[int] | None = None
) -> list[int]:
    """Threshold with hysteresis. Uncovered sectors are blocked (cautious)."""
    n = len(density)
    out = [1] * n
    for i in range(n):
        if not covered[i]:
            out[i] = 1  # never looked there -> do not treat as free
        elif density[i] > cfg.tau_high:
            out[i] = 1
        elif density[i] < cfg.tau_low:
            out[i] = 0
        elif prev_binary is not None and i < len(prev_binary):
            out[i] = prev_binary[i]
        else:
            out[i] = 1  # marginal with no history -> cautious
    return out


def _free_runs(binary: list[int]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i, b in enumerate(binary):
        if b == 0 and start is None:
            start = i
        elif b == 1 and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(binary) - 1))
    return runs


def steer(
    samples: list[tuple[float, float | None]],
    *,
    cfg: VFHConfig | None = None,
    target_bearing_deg: float = 0.0,
    current_bearing_deg: float = 0.0,
    prev_bearing_deg: float = 0.0,
    prev_binary: list[int] | None = None,
) -> VFHResult:
    """Pick a steering bearing toward the best width-clearing gap (VFH+)."""
    cfg = cfg or VFHConfig()
    n = _n_sectors(cfg)
    density, covered = build_histogram(samples, cfg)
    binary = binary_histogram(density, covered, cfg, prev_binary)
    runs = _free_runs(binary)

    free_runs_deg = [
        (round(_sector_center(cfg, r0) - cfg.sector_deg / 2, 1), round(_sector_center(cfg, r1) + cfg.sector_deg / 2, 1))
        for r0, r1 in runs
    ]

    if not runs:
        return VFHResult(None, True, "all sectors blocked or unknown", density, binary, free_runs_deg)

    target_sec = _sector_of(cfg, target_bearing_deg, n)
    current_sec = _sector_of(cfg, current_bearing_deg, n)
    prev_sec = _sector_of(cfg, prev_bearing_deg, n)

    candidates: list[int] = []
    for r0, r1 in runs:
        width = r1 - r0 + 1
        if width > cfg.s_max_sectors:
            candidates.append(r0 + cfg.s_max_sectors // 2)
            candidates.append(r1 - cfg.s_max_sectors // 2)
            if r0 <= target_sec <= r1:
                candidates.append(target_sec)
        else:
            candidates.append((r0 + r1) // 2)
    candidates = sorted({max(0, min(n - 1, c)) for c in candidates})

    def cost(c: int) -> float:
        return (
            cfg.mu_target * abs(c - target_sec)
            + cfg.mu_current * abs(c - current_sec)
            + cfg.mu_previous * abs(c - prev_sec)
        )

    best = min(candidates, key=cost)
    chosen = _sector_center(cfg, best)
    return VFHResult(
        chosen_bearing_deg=round(chosen, 1),
        blocked=False,
        reason=f"steer to {chosen:+.0f}deg gap (of {len(runs)} opening(s))",
        density=density,
        binary=binary,
        free_runs=free_runs_deg,
        candidates=[round(_sector_center(cfg, c), 1) for c in candidates],
    )
