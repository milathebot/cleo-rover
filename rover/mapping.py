from __future__ import annotations

import re
import time
from typing import Any

from .models import SpatialMemoryItem


def slugify(value: str, fallback: str = "item") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or fallback


def distance_cm_to_m(distance_cm: float | None) -> float | None:
    if distance_cm is None:
        return None
    return round(float(distance_cm) / 100.0, 3)


def scan_item(zone: str, bearing_deg: float, distance_cm: float | None, payload: dict[str, Any] | None = None) -> SpatialMemoryItem:
    now = time.time()
    distance_label = "unknown" if distance_cm is None else f"{distance_cm:.1f}cm"
    safe_zone = slugify(zone, "floor")
    bearing_key = str(round(float(bearing_deg), 1)).replace("-", "m").replace(".", "p")
    return SpatialMemoryItem(
        id=f"scan-{safe_zone}-{bearing_key}",
        label=f"{zone} scan {bearing_deg:+.1f} deg",
        kind="range_scan",
        zone=zone,
        bearing_deg=bearing_deg,
        distance_m=distance_cm_to_m(distance_cm),
        confidence=0.55 if distance_cm is None else 0.75,
        notes=f"Ultrasonic range sample: {distance_label}",
        first_seen_at=now,
        last_seen_at=now,
        payload=payload or {},
    )


def observation_items(
    *,
    zone: str,
    bearing_deg: float | None,
    distance_cm: float | None,
    analysis: dict[str, Any],
) -> list[SpatialMemoryItem]:
    """Convert external vision labels/objects plus range data into spatial memories.

    This deliberately does not pretend to do SLAM. It records coarse sightings:
    what was seen, approximate bearing from turret pan, and the current ultrasonic
    distance along that bearing when available.
    """

    now = time.time()
    items: list[SpatialMemoryItem] = []
    labels = [str(label) for label in analysis.get("labels", []) if str(label).strip()]
    for obj in analysis.get("objects", []) or []:
        if isinstance(obj, dict) and obj.get("label"):
            labels.append(str(obj["label"]))
    if not labels and analysis.get("summary"):
        labels.append("scene")

    seen: set[str] = set()
    for label in labels[:12]:
        key = slugify(label, "object")
        if key in seen:
            continue
        seen.add(key)
        items.append(
            SpatialMemoryItem(
                id=f"vision-{slugify(zone, 'floor')}-{key}",
                label=label,
                kind="vision_observation",
                zone=zone,
                bearing_deg=bearing_deg,
                distance_m=distance_cm_to_m(distance_cm),
                confidence=float(analysis.get("confidence", 0.55) or 0.55),
                notes=str(analysis.get("summary") or "External vision observation")[:240],
                first_seen_at=now,
                last_seen_at=now,
                payload={"analysis": analysis, "distance_cm": distance_cm},
            )
        )
    return items
