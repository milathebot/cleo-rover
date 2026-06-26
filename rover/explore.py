"""Pure helpers for exploration + topological memory use.

No SLAM (no encoders/IMU). This is coarse, honest topological reasoning over the
SQLite spatial memory: confidence DECAYS with age (an old sighting is weaker than
a fresh one), navigation can CONSULT memory before moving (prefer open bearings,
deprioritize remembered close obstacles), and Pip can ORIENT back toward a
remembered landmark (e.g. the charger). All side-effect-free for easy testing.
"""

from __future__ import annotations

import math
from typing import Any

# How much each kind of sighting makes a place worth revisiting. People/pets are
# the draw; obstacles make a place mildly less appealing. Tuned, not sacred.
_INTEREST_WEIGHTS = {
    "vision_pet": 1.0,
    "vision_person": 0.7,
    "vision_object": 0.25,
    "vision_area": 0.1,
    "vision_obstacle": -0.2,
}


def place_interest(items: list[Any], *, now: float, half_life_s: float = 43200.0) -> dict[str, float]:
    """Score each ZONE by how interesting it is to revisit, from age-decayed
    sightings (recent cat/person sightings raise it). Pure; drives memory-aware
    roaming so Pip drifts back toward where life happens instead of wandering blind.
    half_life defaults to 12h so yesterday's cat still counts a little today."""
    scores: dict[str, float] = {}
    for item in items:
        zone = getattr(item, "zone", None)
        if not zone:
            continue
        weight = _INTEREST_WEIGHTS.get(getattr(item, "kind", "") or "", 0.0)
        if weight == 0.0:
            continue
        last_seen = getattr(item, "last_seen_at", None)
        age = max(0.0, now - float(last_seen)) if last_seen else 0.0
        scores[zone] = scores.get(zone, 0.0) + weight * math.exp(-age / max(1.0, half_life_s))
    return scores


def decay_confidence(confidence: float, age_seconds: float | None, *, half_life_s: float = 1800.0) -> float:
    """Exponentially decay a confidence by age. Fresh => unchanged; old => weaker."""
    if age_seconds is None or age_seconds <= 0:
        return round(float(confidence), 3)
    return round(float(confidence) * (0.5 ** (age_seconds / max(1.0, half_life_s))), 3)


def memory_bias(items: list[Any], *, now: float, blocked_distance_cm: float = 45.0, open_distance_cm: float = 120.0, min_confidence: float = 0.2) -> dict[str, Any]:
    """Summarize spatial memory into bearings to avoid (close) vs prefer (open).

    Confidence is age-decayed before use, so stale memories barely influence the
    decision. Returns bearing lists plus annotated detail for telemetry.
    """
    avoid: list[dict[str, Any]] = []
    prefer: list[dict[str, Any]] = []
    for item in items:
        bearing = getattr(item, "bearing_deg", None)
        distance_m = getattr(item, "distance_m", None)
        if bearing is None or distance_m is None:
            continue
        last_seen = getattr(item, "last_seen_at", None)
        age = (now - last_seen) if last_seen else None
        conf = decay_confidence(getattr(item, "confidence", 0.5), age)
        if conf < min_confidence:
            continue
        distance_cm = float(distance_m) * 100.0
        entry = {"bearing_deg": float(bearing), "distance_cm": round(distance_cm, 1), "label": getattr(item, "label", ""), "confidence": conf}
        if distance_cm < blocked_distance_cm:
            avoid.append(entry)
        elif distance_cm > open_distance_cm:
            prefer.append(entry)
    return {
        "avoid_bearings": [e["bearing_deg"] for e in avoid],
        "prefer_bearings": [e["bearing_deg"] for e in prefer],
        "avoid": avoid[:8],
        "prefer": prefer[:8],
    }


def prioritize_scan_angles(base_angles: list[float], bias: dict[str, Any], *, near_deg: float = 15.0) -> list[float]:
    """Reorder scan angles to look at preferred bearings first, avoided ones last.

    Order only — the same angles are always sampled, so this cannot skip a real
    obstacle; it just makes Pip glance toward known-open space sooner.
    """
    prefer = [round(float(b)) for b in bias.get("prefer_bearings", [])]
    avoid = [round(float(b)) for b in bias.get("avoid_bearings", [])]

    def score(angle: float) -> int:
        rounded = round(float(angle))
        if any(abs(rounded - p) <= near_deg for p in prefer):
            return 0
        if any(abs(rounded - a) <= near_deg for a in avoid):
            return 2
        return 1

    return sorted(base_angles, key=score)


def least_recently_visited_first(base_angles: list[float], items: list[Any], *, now: float, near_deg: float = 15.0) -> list[float]:
    """Order scan angles so the least-recently-observed bearings come first.

    Drives systematic coverage instead of re-treading the same lane: a bearing
    never seen (no nearby remembered scan) sorts first, then oldest. Order only --
    all angles are still sampled, so this cannot skip an obstacle.
    """
    def staleness(angle: float) -> float:
        ages = [
            now - float(it.last_seen_at)
            for it in items
            if getattr(it, "bearing_deg", None) is not None
            and getattr(it, "last_seen_at", None)
            and abs(round(float(it.bearing_deg)) - round(float(angle))) <= near_deg
        ]
        return max(ages) if ages else float("inf")

    return sorted(base_angles, key=staleness, reverse=True)


def nearest_landmark(items: list[Any], *, label: str | None = None, kind: str | None = None) -> Any | None:
    """Closest remembered landmark matching label/kind that has a known distance."""
    candidates = [
        item
        for item in items
        if getattr(item, "distance_m", None) is not None
        and (label is None or label.lower() in str(getattr(item, "label", "")).lower())
        and (kind is None or getattr(item, "kind", None) == kind)
    ]
    return min(candidates, key=lambda item: item.distance_m) if candidates else None


def bearing_to_turn(bearing_deg: float, *, gain: float = 0.5, max_turn_deg: float = 25.0) -> float:
    """Convert a target bearing into a bounded open-loop turn toward it."""
    return max(-max_turn_deg, min(max_turn_deg, float(bearing_deg) * gain))


def choose_frontier_bearing(frontiers: list[dict], *, max_abs_bearing: float = 120.0) -> float | None:
    """Pick a frontier to head toward: the nearest one within a steerable bearing
    window (frontiers come ranked nearest-first). Turns aimless patrol into directed
    exploration of the unknown. Returns the relative bearing, or None if none fit."""
    for frontier in frontiers:
        bearing = frontier.get("bearing_deg")
        if bearing is None:
            continue
        if abs(float(bearing)) <= float(max_abs_bearing):
            return float(bearing)
    return None
