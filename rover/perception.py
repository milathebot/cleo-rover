"""Continuous perception: a background turret-sweep producer + a fresh polar world-model.

This is the PRODUCER half of Pip's smooth, continuous motion (the consumer is
``rover/cruise.py``). Today motion is stop-and-go: each cycle pans the single
turret sonar across angles, sleeps, recenters, then issues one short crawl pulse.
With one turret-mounted sonar you cannot look forward AND sweep the sides at the
same instant, so the fix is to decouple sensing cadence from motion:

* ``perception_task`` continuously runs a **forward-biased weave** (0deg on every
  other slot) and writes each ping into a shared :class:`PolarSnapshot`.
* The cruise consumer reads the snapshot's freshness, not the live turret angle,
  to decide whether it may move forward -- and the Pi-local bearing guard
  (``drivers.should_panned_forward_stop``) is the hard floor underneath it.

``PolarSnapshot`` + ``weave_schedule`` are PURE and unit-tested; ``perception_task``
is the thin hardware loop (pragma: no cover). No numpy. Advisory only -- nothing
here moves a motor or relaxes a reflex.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def weave_schedule(side_angles: list[float], *, forward_deg: float = 0.0) -> list[float]:
    """Interleave the forward bearing between every side angle.

    e.g. [-20, 20, -45, 45] -> [0, -20, 0, 20, 0, -45, 0, 45]. The 0deg cell is
    therefore refreshed every 2 slots, bounding the time between two forward
    pings (the quantity the braking-distance speed cap depends on).
    """
    out: list[float] = []
    for a in side_angles:
        out.append(forward_deg)
        out.append(float(a))
    return out or [forward_deg]


@dataclass
class Cell:
    dist_cm: float | None
    t_stamp: float
    samples: int = 1


@dataclass
class PolarSnapshot:
    """Latest range per bearing (deg, relative to Pip's heading) with timestamps.

    Single writer (perception_task), many readers (cruise). Under asyncio's
    single thread this needs no lock. Bearings are rounded to integer keys.
    """

    cells: dict[int, Cell] = field(default_factory=dict)

    def update(self, bearing_deg: float, dist_cm: float | None, now: float) -> None:
        self.cells[int(round(bearing_deg))] = Cell(dist_cm=dist_cm, t_stamp=now, samples=1)

    def age_ms(self, bearing_deg: float, now: float) -> float | None:
        cell = self.cells.get(int(round(bearing_deg)))
        return None if cell is None else max(0.0, (now - cell.t_stamp) * 1000.0)

    def fresh(self, bearing_deg: float, max_age_ms: float, now: float) -> bool:
        age = self.age_ms(bearing_deg, now)
        return age is not None and age <= max_age_ms

    def fwd_cone(self, now: float, *, half_deg: float = 20.0, max_age_ms: float = 700.0) -> tuple[float | None, float]:
        """Return (min fresh forward distance, worst forward-cone age in ms).

        min_dist is the closest *fresh* reading within +/- half_deg of straight
        ahead (None if none are fresh). worst_age is the largest age across forward
        cells that exist (inf if no forward cell has ever been seen) -- the cruise
        consumer ramps speed to 0 when this exceeds its staleness limit.
        """
        min_dist: float | None = None
        worst_age = 0.0
        seen_any = False
        for bearing, cell in self.cells.items():
            if abs(bearing) > half_deg:
                continue
            seen_any = True
            age = max(0.0, (now - cell.t_stamp) * 1000.0)
            worst_age = max(worst_age, age)
            if age <= max_age_ms and cell.dist_cm is not None:
                if min_dist is None or cell.dist_cm < min_dist:
                    min_dist = cell.dist_cm
        if not seen_any:
            return None, float("inf")
        return min_dist, worst_age

    def vfh_samples(self, now: float, *, max_age_ms: float = 1500.0) -> list[tuple[float, float | None]]:
        """Fresh (bearing, distance) pairs for vfh.steer. Stale cells are dropped
        (so VFH treats long-unseen bearings as unscanned == blocked)."""
        out: list[tuple[float, float | None]] = []
        for bearing, cell in sorted(self.cells.items()):
            if (now - cell.t_stamp) * 1000.0 <= max_age_ms:
                out.append((float(bearing), cell.dist_cm))
        return out

    def summary(self, now: float) -> dict:
        return {
            "cells": len(self.cells),
            "bearings": sorted(self.cells),
            "fresh_forward": self.fresh(0.0, 700.0, now),
        }


async def perception_task(  # pragma: no cover - thin hardware loop
    body,
    snapshot: PolarSnapshot,
    *,
    side_angles: list[float],
    settle_ms: float,
    clamp_pan,
    now_fn,
    stop_event,
) -> None:
    """Continuously weave the turret + ping, writing into ``snapshot``.

    Thin glue: pan -> settle -> median ping -> snapshot.update, looping the weave.
    ``clamp_pan`` clamps to the turret range; ``now_fn`` returns a monotonic time;
    ``stop_event`` (asyncio.Event) ends the loop. The cruise consumer + the
    Pi-local bearing guard make this safe even mid-slew.
    """
    import asyncio

    from .models import TurretCommand

    schedule = weave_schedule(side_angles)
    i = 0
    while not stop_event.is_set():
        bearing = clamp_pan(schedule[i % len(schedule)])
        await body.set_turret(TurretCommand(pan_deg=bearing))
        await asyncio.sleep(settle_ms / 1000.0)
        dist = body.front_distance_median()
        snapshot.update(bearing, dist, now_fn())
        i += 1
