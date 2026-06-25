"""A small, robot-centric, rolling log-odds occupancy grid for a single panning sonar.

Why this exists (and why it is shaped the way it is):

* We have NO encoders and NO IMU, so dead-reckoned pose drift is unbounded and
  grows with distance. A *global* metric map would smear walls and actively
  mislead within a few metres. The research-backed answer for this hardware is a
  small **rolling, robot-centric** grid (~4 m) that recenters as Pip moves and a
  **tight log-odds clamp** so stale cells decay quickly once contradicted. We do
  not attempt scan matching (one sonar is far too sparse) or a persistent global
  map. (Thrun, *Probabilistic Robotics* ch.9; ROS Nav2 rolling costmap.)
* The sonar beam is a wide (~25-30 deg) cone with frequent specular dropouts, so
  the inverse sensor model marks **FREE across the full cone** but **OCCUPIED only
  in a narrow core** around the measured range, and a max-range/timeout reading
  only ever clears free space (never paints an obstacle).

Everything here is pure Python (no numpy dependency) and side-effect-free apart
from the grid's own state, so it is exhaustively unit-testable on a dev host. The
grid is 41x41 @ 10 cm by default (~4 m) -> ~1700 cells; an inverse-sensor update
touches only the cone's cells, so a full sweep is well under a millisecond even
in pure Python (the ~2 s servo sweep dominates wall-clock by ~1000x).

The grid is ADVISORY. It informs *where to go* (frontiers, free space); it never
relaxes the Pi-local reflex/cliff/bumper stops, which stay authoritative.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Cell classification for planning/consumers.
CELL_UNKNOWN = "unknown"
CELL_FREE = "free"
CELL_OCCUPIED = "occupied"


@dataclass(frozen=True)
class GridConfig:
    """Tunables for the rolling occupancy grid + sonar inverse sensor model."""

    cell_cm: float = 10.0
    size_cells: int = 41  # odd, so the robot sits on the centre cell
    # Log-odds increments. Asymmetric (|l_occ| > |l_free|) so the map trusts
    # obstacles more than free space -- the right bias for a sonar that drops out
    # a lot. One confident on-axis ping (l_occ=0.9) already tips a cell to
    # "occupied" (p~0.71), so a single sweep is immediately useful for steering;
    # free space accrues fast because every ray in the sweep clears its cone.
    l_occ: float = 0.90
    l_free: float = -0.50
    # Tight clamp: a drifty robot should forget stale cells fast. ~4 consistent
    # pings saturate a cell; ~8 contradicting pings clear it. Widen for a more
    # permanent map (only sensible with good odometry, which we don't have).
    l_clamp: float = 3.5
    # Planning thresholds (log-odds). Between free_threshold..occ_threshold the
    # cell is reported "unknown".
    occ_threshold: float = 0.85  # p ~ 0.70
    free_threshold: float = -0.40
    unknown_band: float = 0.20
    # Sonar inverse sensor model.
    beta_free_deg: float = 28.0  # full cone: mark FREE across this width
    beta_occ_deg: float = 12.0  # narrow core: mark OCCUPIED only this near axis
    alpha_cm: float = 12.0  # occupied-shell thickness (~ 1 cell)
    z_min_cm: float = 3.0
    z_max_cm: float = 300.0  # readings >= this are "open / no echo" -> free only
    # Recenter when the robot drifts more than this many cells from grid centre.
    recenter_margin_cells: int = 6

    def __post_init__(self) -> None:
        if self.size_cells < 5 or self.size_cells % 2 == 0:
            raise ValueError(f"size_cells must be odd and >=5 (got {self.size_cells})")
        if not (self.l_free < 0 < self.l_occ):
            raise ValueError("require l_free < 0 < l_occ")
        if self.beta_occ_deg > self.beta_free_deg:
            raise ValueError("beta_occ_deg must be <= beta_free_deg")


def grid_config_from(cfg) -> GridConfig:
    """Build a GridConfig from a NavConfig-shaped object (duck-typed)."""
    return GridConfig(
        cell_cm=cfg.grid_cell_cm,
        size_cells=cfg.grid_size_cells,
        l_occ=cfg.grid_l_occ,
        l_free=cfg.grid_l_free,
        l_clamp=cfg.grid_l_clamp,
        occ_threshold=cfg.grid_occ_threshold,
        free_threshold=cfg.grid_free_threshold,
        beta_free_deg=cfg.grid_beta_free_deg,
        beta_occ_deg=cfg.grid_beta_occ_deg,
        alpha_cm=cfg.grid_alpha_cm,
        z_max_cm=cfg.grid_z_max_cm,
    )


def _wrap_deg(deg: float) -> float:
    """Wrap to (-180, 180]."""
    return (float(deg) + 180.0) % 360.0 - 180.0


@dataclass
class OccupancyGrid:
    """Robot-centric rolling log-odds grid.

    Coordinates: the grid is axis-aligned to a *local* frame fixed at the last
    reset. The robot has a continuous pose ``(x_cm, y_cm, heading_deg)`` in that
    frame (0 deg = +x). Cell (col, row) centres map to local coords via the grid
    origin, which is shifted in whole cells when the robot wanders too far from
    centre (so the array stays small and recent observations stay near the
    middle). Drift still accrues, but the tight clamp makes the map self-heal.
    """

    config: GridConfig = field(default_factory=GridConfig)
    x_cm: float = 0.0
    y_cm: float = 0.0
    heading_deg: float = 0.0
    # Local-frame coordinate of the grid's (0,0) cell centre. Starts so the robot
    # is on the centre cell.
    origin_x_cm: float = 0.0
    origin_y_cm: float = 0.0
    _log: list[float] = field(default_factory=list)
    updates: int = 0

    def __post_init__(self) -> None:
        n = self.config.size_cells
        if not self._log:
            self._log = [0.0] * (n * n)
        # Place the robot exactly on the centre-cell *centre* at construction, so
        # the cone geometry of a straight-ahead ray is clean (no half-cell skew).
        half = (n // 2 + 0.5) * self.config.cell_cm
        self.origin_x_cm = self.x_cm - half
        self.origin_y_cm = self.y_cm - half

    # --- indexing helpers ---------------------------------------------------
    def _idx(self, col: int, row: int) -> int:
        return row * self.config.size_cells + col

    def in_bounds(self, col: int, row: int) -> bool:
        n = self.config.size_cells
        return 0 <= col < n and 0 <= row < n

    def cell_of(self, x_cm: float, y_cm: float) -> tuple[int, int]:
        col = int((x_cm - self.origin_x_cm) / self.config.cell_cm)
        row = int((y_cm - self.origin_y_cm) / self.config.cell_cm)
        return col, row

    def cell_center(self, col: int, row: int) -> tuple[float, float]:
        cx = self.origin_x_cm + (col + 0.5) * self.config.cell_cm
        cy = self.origin_y_cm + (row + 0.5) * self.config.cell_cm
        return cx, cy

    def log_odds(self, col: int, row: int) -> float:
        if not self.in_bounds(col, row):
            return 0.0
        return self._log[self._idx(col, row)]

    def probability(self, col: int, row: int) -> float:
        l = self.log_odds(col, row)
        return 1.0 - 1.0 / (1.0 + math.exp(l))

    def classify(self, col: int, row: int) -> str:
        l = self.log_odds(col, row)
        if l >= self.config.occ_threshold:
            return CELL_OCCUPIED
        if l <= self.config.free_threshold:
            return CELL_FREE
        return CELL_UNKNOWN

    # --- pose integration (dead reckoning) ----------------------------------
    def integrate_forward(self, distance_cm: float) -> None:
        rad = math.radians(self.heading_deg)
        self.x_cm += distance_cm * math.cos(rad)
        self.y_cm += distance_cm * math.sin(rad)
        self._maybe_recenter()

    def integrate_turn(self, delta_deg: float) -> None:
        self.heading_deg = _wrap_deg(self.heading_deg + delta_deg)

    def _maybe_recenter(self) -> None:
        """Shift the grid in whole cells when the robot drifts off-centre.

        Uses ``list``-level rolling: newly exposed cells are reset to unknown
        (0.0). Keeps the robot near the middle so the active area stays mapped.
        """
        col, row = self.cell_of(self.x_cm, self.y_cm)
        n = self.config.size_cells
        center = n // 2
        dcol = col - center
        drow = row - center
        margin = self.config.recenter_margin_cells
        if abs(dcol) < margin and abs(drow) < margin:
            return
        self._shift(dcol, drow)
        self.origin_x_cm += dcol * self.config.cell_cm
        self.origin_y_cm += drow * self.config.cell_cm

    def _shift(self, dcol: int, drow: int) -> None:
        n = self.config.size_cells
        new = [0.0] * (n * n)
        for row in range(n):
            src_row = row + drow
            if not (0 <= src_row < n):
                continue
            for col in range(n):
                src_col = col + dcol
                if 0 <= src_col < n:
                    new[row * n + col] = self._log[src_row * n + src_col]
        self._log = new

    # --- sonar inverse sensor model -----------------------------------------
    def update_ray(self, bearing_deg: float, distance_cm: float | None) -> int:
        """Apply one sonar reading (bearing RELATIVE TO ROBOT heading).

        Returns the number of cells touched. ``distance_cm`` None or >= z_max is
        treated as "open / no echo": free is cleared along the cone, but no
        occupied shell is painted (never invent an obstacle from a dropout).
        """
        cfg = self.config
        world_bearing = self.heading_deg + float(bearing_deg)
        max_echo = cfg.z_max_cm
        if distance_cm is None or distance_cm >= cfg.z_max_cm:
            z = cfg.z_max_cm
            has_hit = False
        elif distance_cm < cfg.z_min_cm:
            return 0  # implausibly close; ignore (turret clipping / noise)
        else:
            z = float(distance_cm)
            has_hit = True

        # Bounding box of the cone in cells (out to z + alpha).
        reach = min(z + cfg.alpha_cm, max_echo)
        sx, sy = self.x_cm, self.y_cm
        scol, srow = self.cell_of(sx, sy)
        span = int(reach / cfg.cell_cm) + 2
        n = cfg.size_cells
        half_free = cfg.beta_free_deg / 2.0
        half_occ = cfg.beta_occ_deg / 2.0
        touched = 0
        for row in range(max(0, srow - span), min(n, srow + span + 1)):
            for col in range(max(0, scol - span), min(n, scol + span + 1)):
                cx, cy = self.cell_center(col, row)
                dx, dy = cx - sx, cy - sy
                r = math.hypot(dx, dy)
                if r < 1e-6 or r > reach:
                    continue
                ang = abs(_wrap_deg(math.degrees(math.atan2(dy, dx)) - world_bearing))
                if ang > half_free:
                    continue
                if has_hit and abs(r - z) <= cfg.alpha_cm / 2.0 and ang <= half_occ:
                    # Occupied shell near the measured range, narrow core only.
                    # Weight by off-axis angle (a la VFH c^2 certainty).
                    w = math.cos(math.radians(ang))
                    self._bump(col, row, cfg.l_occ * max(0.2, w))
                    touched += 1
                elif r < z - cfg.alpha_cm / 2.0:
                    # Between sensor and the hit -> free.
                    self._bump(col, row, cfg.l_free)
                    touched += 1
        self.updates += 1
        return touched

    def update_from_sweep(self, samples: list[tuple[float, float | None]]) -> int:
        """Apply a full sweep: list of (bearing_deg_relative, distance_cm)."""
        return sum(self.update_ray(b, d) for b, d in samples)

    def _bump(self, col: int, row: int, delta: float) -> None:
        i = self._idx(col, row)
        v = self._log[i] + delta
        clamp = self.config.l_clamp
        self._log[i] = clamp if v > clamp else -clamp if v < -clamp else v

    # --- frontier detection (Yamauchi) --------------------------------------
    def frontier_cells(self) -> list[tuple[int, int]]:
        """Free cells adjacent to at least one unknown cell (the explore boundary)."""
        n = self.config.size_cells
        out: list[tuple[int, int]] = []
        for row in range(n):
            for col in range(n):
                if self.classify(col, row) != CELL_FREE:
                    continue
                for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nc, nr = col + dc, row + dr
                    if self.in_bounds(nc, nr) and self.classify(nc, nr) == CELL_UNKNOWN:
                        out.append((col, row))
                        break
        return out

    def frontiers(self, *, min_cluster: int = 4) -> list[dict]:
        """Cluster frontier cells and return centroids as bearings/distances.

        Bearings are RELATIVE TO ROBOT heading (so a consumer can steer directly),
        ranked nearest-first (least drift exposure per trip, per the research).
        """
        cells = set(self.frontier_cells())
        clusters: list[list[tuple[int, int]]] = []
        seen: set[tuple[int, int]] = set()
        for cell in cells:
            if cell in seen:
                continue
            stack = [cell]
            comp: list[tuple[int, int]] = []
            while stack:
                cur = stack.pop()
                if cur in seen:
                    continue
                seen.add(cur)
                comp.append(cur)
                c0, r0 = cur
                for dc in (-1, 0, 1):
                    for dr in (-1, 0, 1):
                        nb = (c0 + dc, r0 + dr)
                        if nb in cells and nb not in seen:
                            stack.append(nb)
            if len(comp) >= min_cluster:
                clusters.append(comp)

        out: list[dict] = []
        for comp in clusters:
            mcol = sum(c for c, _ in comp) / len(comp)
            mrow = sum(r for _, r in comp) / len(comp)
            cx = self.origin_x_cm + (mcol + 0.5) * self.config.cell_cm
            cy = self.origin_y_cm + (mrow + 0.5) * self.config.cell_cm
            dx, dy = cx - self.x_cm, cy - self.y_cm
            dist = math.hypot(dx, dy)
            rel_bearing = _wrap_deg(math.degrees(math.atan2(dy, dx)) - self.heading_deg)
            out.append(
                {
                    "size": len(comp),
                    "distance_cm": round(dist, 1),
                    "bearing_deg": round(rel_bearing, 1),
                    "centroid_local_cm": [round(cx, 1), round(cy, 1)],
                }
            )
        out.sort(key=lambda f: f["distance_cm"])
        return out

    # --- summaries ----------------------------------------------------------
    def stats(self) -> dict:
        n = self.config.size_cells
        free = occ = unknown = 0
        for row in range(n):
            for col in range(n):
                cls = self.classify(col, row)
                if cls == CELL_FREE:
                    free += 1
                elif cls == CELL_OCCUPIED:
                    occ += 1
                else:
                    unknown += 1
        total = n * n
        return {
            "size_cells": n,
            "cell_cm": self.config.cell_cm,
            "extent_cm": round(n * self.config.cell_cm, 1),
            "free": free,
            "occupied": occ,
            "unknown": unknown,
            "explored_frac": round((free + occ) / total, 3),
            "pose": {"x_cm": round(self.x_cm, 1), "y_cm": round(self.y_cm, 1), "heading_deg": round(self.heading_deg, 1)},
            "updates": self.updates,
        }

    def ascii_map(self, *, max_size: int = 21) -> str:
        """Tiny ASCII rendering for telemetry/debugging. '#'=occ '.'=free ' '=unknown, 'R'=robot."""
        n = self.config.size_cells
        step = max(1, n // max_size)
        rcol, rrow = self.cell_of(self.x_cm, self.y_cm)
        lines = []
        for row in range(n - 1, -1, -step):
            chars = []
            for col in range(0, n, step):
                if abs(col - rcol) < step and abs(row - rrow) < step:
                    chars.append("R")
                    continue
                cls = self.classify(col, row)
                chars.append("#" if cls == CELL_OCCUPIED else "." if cls == CELL_FREE else " ")
            lines.append("".join(chars))
        return "\n".join(lines)
