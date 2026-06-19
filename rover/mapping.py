from __future__ import annotations

import re
import time
from collections import Counter, defaultdict
from typing import Any

from .models import RoverEvent, RoverEventKind, SpatialMemoryItem

PERSON_LABELS = {"person", "human", "people", "man", "woman", "noot"}
PET_LABELS = {"pet", "cat", "dog", "mila", "pengu"}
OBSTACLE_LABELS = {"obstacle", "cable", "cord", "chair", "table", "box", "wall", "door", "furniture"}
AREA_LABELS = {"room", "office", "living room", "hallway", "doorway", "desk", "window", "cat tree"}


def slugify(value: str, fallback: str = "item") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or fallback


def distance_cm_to_m(distance_cm: float | None) -> float | None:
    if distance_cm is None:
        return None
    return round(float(distance_cm) / 100.0, 3)


def classify_label(label: str) -> str:
    normalized = str(label).strip().lower()
    if normalized in PERSON_LABELS:
        return "person"
    if normalized in PET_LABELS:
        return "pet"
    if normalized in OBSTACLE_LABELS:
        return "obstacle"
    if normalized in AREA_LABELS:
        return "area"
    return "object"


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


def _analysis_labels(analysis: dict[str, Any]) -> list[str]:
    labels = [str(label) for label in analysis.get("labels", []) if str(label).strip()]
    for obj in analysis.get("objects", []) or []:
        if isinstance(obj, dict) and obj.get("label"):
            labels.append(str(obj["label"]))
    if not labels and analysis.get("summary"):
        labels.append("scene")
    return labels


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
    labels = _analysis_labels(analysis)
    objects_by_label: dict[str, dict[str, Any]] = {}
    for obj in analysis.get("objects", []) or []:
        if isinstance(obj, dict) and obj.get("label"):
            objects_by_label.setdefault(str(obj["label"]), obj)

    seen: set[str] = set()
    for label in labels[:12]:
        key = slugify(label, "object")
        if key in seen:
            continue
        seen.add(key)
        category = classify_label(label)
        obj_payload = objects_by_label.get(label, {})
        items.append(
            SpatialMemoryItem(
                id=f"vision-{slugify(zone, 'floor')}-{category}-{key}",
                label=label,
                kind=f"vision_{category}",
                zone=zone,
                bearing_deg=bearing_deg,
                distance_m=distance_cm_to_m(distance_cm),
                confidence=float(analysis.get("confidence", 0.55) or 0.55),
                notes=str(analysis.get("summary") or "External vision observation")[:240],
                first_seen_at=now,
                last_seen_at=now,
                payload={"analysis": analysis, "object": obj_payload, "category": category, "distance_cm": distance_cm},
            )
        )
    return items


def semantic_events_from_analysis(analysis: dict[str, Any], *, distance_cm: float | None, bearing_deg: float | None) -> list[RoverEvent]:
    labels = _analysis_labels(analysis)
    categories = {classify_label(label) for label in labels}
    payload = {"labels": sorted(set(labels)), "analysis": analysis, "distance_cm": distance_cm, "bearing_deg": bearing_deg}
    events: list[RoverEvent] = []
    if "obstacle" in categories:
        events.append(RoverEvent(kind=RoverEventKind.obstacle, source="vision", label="vision obstacle", value=distance_cm, payload=payload))
    if "person" in categories:
        events.append(RoverEvent(kind=RoverEventKind.motion, source="vision", label="person seen", value=distance_cm, payload=payload | {"semantic": "person"}))
    if "pet" in categories:
        events.append(RoverEvent(kind=RoverEventKind.motion, source="vision", label="pet seen", value=distance_cm, payload=payload | {"semantic": "pet"}))
    return events


def map_summary(items: list[SpatialMemoryItem]) -> dict[str, Any]:
    by_zone: dict[str, Counter[str]] = defaultdict(Counter)
    by_kind: Counter[str] = Counter()
    nearest: dict[str, Any] | None = None
    for item in items:
        zone = item.zone or "unknown"
        by_zone[zone][item.kind] += 1
        by_kind[item.kind] += 1
        if item.distance_m is not None and (nearest is None or item.distance_m < nearest["distance_m"]):
            nearest = {
                "id": item.id,
                "label": item.label,
                "kind": item.kind,
                "zone": item.zone,
                "bearing_deg": item.bearing_deg,
                "distance_m": item.distance_m,
                "confidence": item.confidence,
            }
    return {
        "total_items": len(items),
        "kinds": dict(by_kind),
        "zones": {zone: dict(counts) for zone, counts in by_zone.items()},
        "nearest": nearest,
    }
