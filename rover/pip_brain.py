from __future__ import annotations

import time
from typing import Any

from .awareness import last_seen_summary, range_state_from_samples
from .mapping import map_summary
from .models import AutonomyState, RoverEvent, RoverEventKind, SpatialMemoryItem

HAZARD_LABEL_WORDS = {"cat", "dog", "pet", "cable", "cord", "stairs", "stair", "liquid", "water", "edge", "feet", "foot", "person"}
MOTION_EVENT_KINDS = {RoverEventKind.manual_control, RoverEventKind.movement_permission, RoverEventKind.map_observation, RoverEventKind.obstacle, RoverEventKind.bump, RoverEventKind.motion}


def _event_summary(event: RoverEvent) -> dict[str, Any]:
    return {
        "kind": event.kind.value,
        "source": event.source,
        "label": event.label,
        "value": event.value,
        "age_seconds": round(time.time() - event.timestamp, 1) if event.timestamp else None,
        "timestamp": event.timestamp,
    }


def _latest(events: list[RoverEvent], *kinds: RoverEventKind) -> RoverEvent | None:
    wanted = set(kinds)
    return next((event for event in events if event.kind in wanted), None)


def _recent_vision(events: list[RoverEvent]) -> dict[str, Any] | None:
    for event in events:
        if event.kind == RoverEventKind.vision_analysis:
            analysis = event.payload or {}
            return {
                "summary": analysis.get("summary"),
                "labels": analysis.get("labels") or [],
                "objects": analysis.get("objects") or [],
                "confidence": analysis.get("confidence"),
                "zone": analysis.get("zone"),
                "snapshot_path": analysis.get("snapshot_path"),
                "age_seconds": round(time.time() - event.timestamp, 1) if event.timestamp else None,
            }
    return None


def _hazards(events: list[RoverEvent], items: list[SpatialMemoryItem], sensors: dict[str, Any], *, stop_cm: float, max_item_age_s: float = 120.0) -> list[dict[str, Any]]:
    hazards: list[dict[str, Any]] = []
    now = time.time()
    front = sensors.get("front_distance_cm")
    if front is not None:
        try:
            front_value = float(front)
            if front_value < stop_cm:
                hazards.append({"kind": "front_blocked", "detail": f"front range {front_value:.1f}cm below stop threshold {stop_cm:.1f}cm", "severity": "high"})
            elif front_value < 55:
                hazards.append({"kind": "front_near", "detail": f"front range {front_value:.1f}cm is close", "severity": "medium"})
        except (TypeError, ValueError):
            pass
    for event in events[:12]:
        if event.kind in {RoverEventKind.bump, RoverEventKind.obstacle}:
            hazards.append({"kind": event.kind.value, "detail": event.label or event.kind.value, "severity": "high", "age_seconds": round(time.time() - event.timestamp, 1) if event.timestamp else None})
    for item in items[:25]:
        label = item.label.lower()
        if item.kind in {"vision_pet", "vision_person", "vision_obstacle"} or any(word in label for word in HAZARD_LABEL_WORDS):
            # Age-gate remembered sightings: a cat seen 100 minutes ago is not a
            # *live* hazard. Only fresh sightings should constrain movement.
            age = (now - item.last_seen_at) if item.last_seen_at else None
            if age is not None and age > max_item_age_s:
                continue
            hazards.append({"kind": item.kind, "detail": item.label, "zone": item.zone, "bearing_deg": item.bearing_deg, "distance_m": item.distance_m, "severity": "medium", "age_seconds": round(age, 1) if age is not None else None})
    # Keep the packet compact and stable.
    return hazards[:8]


def _room_hypothesis(pip_state: dict[str, Any], recent_vision: dict[str, Any] | None, items: list[SpatialMemoryItem]) -> dict[str, Any]:
    zone = str(pip_state.get("current_zone") or "office")
    evidence = ["pip_state.current_zone"]
    confidence = 0.45
    if recent_vision and recent_vision.get("zone"):
        zone = str(recent_vision["zone"])
        evidence.append("latest_vision_analysis.zone")
        confidence = max(confidence, 0.60)
    zones: dict[str, int] = {}
    for item in items[:50]:
        if item.zone:
            zones[item.zone] = zones.get(item.zone, 0) + 1
    if zones:
        best_zone, count = max(zones.items(), key=lambda kv: kv[1])
        if best_zone == zone:
            confidence = max(confidence, min(0.85, 0.55 + count / 40))
            evidence.append("spatial_memory agrees")
        elif count >= 5:
            evidence.append(f"spatial_memory also suggests {best_zone}")
    return {"zone": zone, "confidence": round(confidence, 2), "evidence": evidence}


def _motion_story(events: list[RoverEvent], status: dict[str, Any], movement: dict[str, Any], sensors: dict[str, Any]) -> dict[str, Any]:
    latest_motionish = next((event for event in events if event.kind in MOTION_EVENT_KINDS), None)
    last_drive = status.get("last_drive")
    reflex = (sensors.get("motors") or {}).get("last_reflex_stop")
    active = bool(movement.get("active"))
    if reflex:
        state = "stopped_by_reflex"
    elif active:
        state = "movement_granted_or_running"
    elif last_drive:
        state = "last_drive_known_but_now_stopped"
    elif latest_motionish:
        state = "recent_motion_or_observation_event"
    else:
        state = "no_recent_motion_evidence"
    return {
        "state": state,
        "movement_active": active,
        "last_drive": last_drive,
        "last_motion_event": _event_summary(latest_motionish) if latest_motionish else None,
        "reflex_stop": reflex,
        "honesty_note": "Pip has no wheel encoders yet; forward progress is inferred from commands, range changes, image motion events, and operator/vision observations.",
    }


def _desire_and_next_step(
    *,
    pip_state: dict[str, Any],
    battery: dict[str, Any],
    range_state: dict[str, Any],
    hazards: list[dict[str, Any]],
    movement: dict[str, Any],
    status: dict[str, Any],
    autonomy: AutonomyState,
) -> dict[str, Any]:
    mode = str(pip_state.get("mode") or "social")
    boredom = float(pip_state.get("boredom") or 0.0)
    goal = pip_state.get("exploration_goal") if isinstance(pip_state.get("exploration_goal"), dict) else None
    if mode == "sleep":
        return {"want": "rest", "doing_now": "sleeping", "next_safe_action": "stay still until wake command", "goal": goal}
    if battery.get("recommendation") == "charge_before_movement":
        return {"want": "charge", "doing_now": "protecting battery", "next_safe_action": "ask Noot to park/charge Pip", "goal": goal}
    if hazards:
        return {"want": "safety", "doing_now": "watching hazards", "next_safe_action": "stop, observe, scan, or ask for rescue before moving", "goal": goal}
    if goal:
        destination = str(goal.get("destination") or "somewhere")
        if goal.get("requires_human_help"):
            return {
                "want": f"go_to:{destination}",
                "doing_now": "holding a destination wish",
                "next_safe_action": f"ask Noot for help with access/supervision before trying to go to {destination}",
                "goal": goal,
            }
        return {"want": f"go_to:{destination}", "doing_now": "planning a tiny route", "next_safe_action": "run vision-awareness, then first-adventure only if preflight and movement permission are green", "goal": goal}
    if movement.get("active"):
        return {"want": "complete tiny supervised movement", "doing_now": "following active movement grant", "next_safe_action": "continue Pi-side reactive loop and stop when grant expires", "goal": goal}
    if range_state.get("state") in {"blocked", "near"}:
        return {"want": "find open path", "doing_now": "front path is constrained", "next_safe_action": "scan left/right, rotate in tiny steps, do not crawl forward", "goal": goal}
    if mode == "quiet":
        return {"want": "observe quietly", "doing_now": "quiet presence", "next_safe_action": "vision-awareness or look-around without movement", "goal": goal}
    if not status.get("motors_armed"):
        return {"want": "be ready", "doing_now": "bench/presence mode", "next_safe_action": "observe, speak, and wait for first-adventure/floor-cautious prep", "goal": goal}
    if boredom >= 0.60 or autonomy.curiosity >= 0.68:
        return {"want": "explore", "doing_now": "curious and ready", "next_safe_action": "run first-adventure or life-tick with explicit supervised movement permission", "goal": goal}
    return {"want": "watch and learn", "doing_now": "calm office presence", "next_safe_action": "periodic vision-awareness and map memory updates", "goal": goal}


def build_pip_brain(
    *,
    pip_state: dict[str, Any],
    identity: dict[str, Any],
    battery: dict[str, Any],
    sensors: dict[str, Any],
    status: dict[str, Any],
    movement: dict[str, Any],
    autonomy: AutonomyState,
    recent_events: list[RoverEvent],
    spatial_items: list[SpatialMemoryItem],
    compact: bool = True,
    latest_vision_event: RoverEvent | None = None,
    hazard_max_age_s: float = 120.0,
) -> dict[str, Any]:
    stop_cm = float((status.get("safety") or {}).get("front_stop_distance_cm") or sensors.get("front_stop_distance_cm") or 18.0)
    range_state = range_state_from_samples([sensors.get("front_distance_cm")], stop_cm=stop_cm)
    # Prefer a kind-filtered latest vision event so fresh vision is not evicted by
    # a flood of per-angle scan events (the old latest_vision:null bug).
    recent_vision = _recent_vision([latest_vision_event]) if latest_vision_event is not None else _recent_vision(recent_events)
    hazards = _hazards(recent_events, spatial_items, sensors, stop_cm=stop_cm, max_item_age_s=hazard_max_age_s)
    room = _room_hypothesis(pip_state, recent_vision, spatial_items)
    desire = _desire_and_next_step(
        pip_state=pip_state,
        battery=battery,
        range_state=range_state,
        hazards=hazards,
        movement=movement,
        status=status,
        autonomy=autonomy,
    )
    events = [_event_summary(event) for event in recent_events[:8]]
    surroundings = {
        "range_state": range_state,
        "hazards": hazards,
        "last_seen": last_seen_summary(spatial_items, limit=8),
        "map_summary": map_summary(spatial_items),
        "latest_vision": recent_vision,
    }
    brain = {
        "ok": True,
        "schema": "pip_brain_v1",
        "time": time.time(),
        "identity": {"name": identity.get("name", "Pip"), "home_base": identity.get("home_base", "office")},
        "self": {
            "mode": pip_state.get("mode"),
            "mood": pip_state.get("mood"),
            "awake": pip_state.get("awake"),
            "boredom": pip_state.get("boredom"),
            "autonomy_mood": autonomy.mood,
            "curiosity": autonomy.curiosity,
            "attention": autonomy.attention,
        },
        "where_am_i": room,
        "what_happened": _motion_story(recent_events, status, movement, sensors),
        "what_is_around_me": surroundings,
        "what_i_want": desire,
        "what_i_am_doing_now": desire["doing_now"],
        "next_safe_action": desire["next_safe_action"],
        "recent_events": events,
        "bridge_context_hint": "Send this brain packet plus any new image to Hermes/Cleo for complex planning; use Pi-side reflex/reactive loops for immediate movement safety.",
    }
    if not compact:
        brain["spatial_items"] = [item.model_dump() for item in spatial_items[:50]]
        brain["status"] = status
        brain["sensors"] = sensors
        brain["movement"] = movement
        brain["battery"] = battery
    return brain
