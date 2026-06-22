from __future__ import annotations

import argparse
import json
import signal
import sys
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE = "http://127.0.0.1:8099"


def request(base: str, method: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 8) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        method=method,
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def scan_observations(scan_result: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Flatten /map/scan observations into bearing/distance pairs."""
    out: list[dict[str, Any]] = []
    if not scan_result:
        return out
    for obs in scan_result.get("observations") or []:
        payload = ((obs.get("event") or {}).get("payload") or {}) if isinstance(obs, dict) else {}
        bearing = payload.get("bearing_deg")
        distance = payload.get("distance_cm")
        if bearing is None or distance is None:
            continue
        try:
            out.append({"bearing_deg": float(bearing), "distance_cm": float(distance)})
        except (TypeError, ValueError):
            continue
    return out


def choose_escape_turn(scan_result: dict[str, Any] | None, *, minimum_clear_cm: float = 72.0, min_improvement_cm: float = 18.0) -> dict[str, Any] | None:
    """Pick a conservative turn toward the clearest scanned side."""
    observations = scan_observations(scan_result)
    side_observations = [o for o in observations if abs(o["bearing_deg"]) >= 15.0]
    if not side_observations:
        return None
    best = max(side_observations, key=lambda o: (o["distance_cm"], abs(o["bearing_deg"])))
    center_distances = [o["distance_cm"] for o in observations if abs(o["bearing_deg"]) < 12.0]
    center = min(center_distances) if center_distances else 0.0
    if best["distance_cm"] < minimum_clear_cm and best["distance_cm"] < center + min_improvement_cm:
        return None
    deg = 25.0 if best["bearing_deg"] > 0 else -25.0
    return {"deg": deg, "bearing_deg": best["bearing_deg"], "distance_cm": best["distance_cm"]}


def extract_scan_result(supervisor_result: dict[str, Any]) -> dict[str, Any] | None:
    for applied in supervisor_result.get("applied") or []:
        if applied.get("kind") == "scan" and isinstance(applied.get("result"), dict):
            return applied["result"]
    return None


def supervisor_result_summary(supervisor_result: dict[str, Any]) -> dict[str, Any]:
    """Small operator-friendly summary for live brain logs."""
    summary: dict[str, Any] = {}
    for applied in supervisor_result.get("applied") or []:
        kind = applied.get("kind")
        result = applied.get("result") or {}
        if kind == "drive" and isinstance(result, dict):
            summary["drive"] = result.get("command")
        elif kind == "scan" and isinstance(result, dict):
            observations = scan_observations(result)
            if observations:
                best = max(observations, key=lambda o: o["distance_cm"])
                center = [o for o in observations if abs(o["bearing_deg"]) < 5]
                summary["scan"] = {
                    "best_bearing_deg": best["bearing_deg"],
                    "best_distance_cm": best["distance_cm"],
                    "center_distance_cm": center[0]["distance_cm"] if center else None,
                    "samples": len(observations),
                }
    snapshot = supervisor_result.get("snapshot") or {}
    sensors = snapshot.get("sensors") or {}
    range_state = snapshot.get("range_state") or {}
    summary["front_distance_cm"] = sensors.get("front_distance_cm")
    summary["range_state"] = range_state.get("state")
    return summary


def choose_body_intent(snapshot: dict[str, Any], *, zone: str, last_intent: str | None = None, last_scan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Tiny PC/Hermes-side policy: scan often, move rarely, never raw motor duty."""
    flags = set(snapshot.get("safety_flags") or [])
    range_state = (snapshot.get("range_state") or {}).get("state")
    sensors = snapshot.get("sensors") or {}
    status = snapshot.get("status") or {}
    distance = sensors.get("front_distance_cm")
    if flags & {"inconsistent_motor_safety", "sensor_errors"}:
        return {"intent": "stop", "mood": "alert", "speech": "Safety check failed. Stopping.", "params": {}}
    front_close = range_state in {"blocked", "near"} or (distance is not None and float(distance) < 70.0)
    if front_close:
        if last_intent == "rotate_step":
            return {"intent": "scan", "mood": "thinking", "speech": "Checking the new angle.", "params": {"zone": zone, "angles": [-45, -25, 0, 25, 45]}}
        if last_intent == "scan":
            # If the front is already near/blocked, do not sit there waiting
            # forever. A side that is modestly better is enough for a small
            # escape turn, then we re-scan before moving.
            escape = choose_escape_turn(last_scan, minimum_clear_cm=60.0, min_improvement_cm=8.0)
            if escape:
                direction = "right" if escape["deg"] > 0 else "left"
                return {
                    "intent": "rotate_step",
                    "mood": "focused",
                    "speech": f"Path blocked. Turning {direction}.",
                    "params": {"deg": escape["deg"], "reason": "clearest_scan", "bearing_deg": escape["bearing_deg"], "distance_cm": escape["distance_cm"]},
                }
            return {"intent": "mood", "mood": "alert", "speech": "Path still blocked. Waiting.", "params": {}}
        return {"intent": "scan", "mood": "thinking", "speech": "Close obstacle. Scanning.", "params": {"zone": zone, "angles": [-45, -25, 0, 25, 45]}}
    if sensors.get("front_distance_cm") is None:
        return {"intent": "scan", "mood": "thinking", "speech": "Need range before moving.", "params": {"zone": zone, "angles": [-45, -20, 0, 20, 45]}}
    if not status.get("motors_armed"):
        return {"intent": "scan", "mood": "thinking", "speech": "Motors are not armed.", "params": {"zone": zone, "angles": [-35, 0, 35]}}
    if last_intent == "move_step":
        return {"intent": "scan", "mood": "thinking", "speech": "Checking path.", "params": {"zone": zone, "angles": [-35, -15, 0, 15, 35]}}
    if last_intent == "scan" and distance is not None and float(distance) < 90.0:
        escape = choose_escape_turn(last_scan, minimum_clear_cm=90.0)
        if escape:
            direction = "right" if escape["deg"] > 0 else "left"
            return {
                "intent": "rotate_step",
                "mood": "focused",
                "speech": f"Path narrow. Turning {direction}.",
                "params": {"deg": escape["deg"], "reason": "clearest_scan_after_narrow_path", "bearing_deg": escape["bearing_deg"], "distance_cm": escape["distance_cm"]},
            }
        return {"intent": "mood", "mood": "confused", "speech": "I scanned, but the path is not open enough.", "params": {}}
    return {"intent": "move_step", "mood": "focused", "speech": "Tiny step.", "params": {"forward_cm": 3}}


class BrainLoop:
    """PC-side brain loop. The Pi remains the body/reflex safety agent."""

    def __init__(self, base: str, interval: float = 5.0, allow_movement: bool = False, supervised_body: bool = False, zone: str = "unknown") -> None:
        self.base = base
        self.interval = interval
        self.allow_movement = allow_movement
        self.supervised_body = supervised_body
        self.zone = zone
        self.running = True
        self.last_intent: str | None = None

    def stop(self, *_args) -> None:
        self.running = False

    def once(self) -> dict[str, Any]:
        if self.supervised_body:
            snapshot = request(self.base, "GET", "/supervisor/status", timeout=8)
            intent = choose_body_intent(snapshot, zone=self.zone, last_intent=self.last_intent, last_scan=getattr(self, "last_scan", None))
            if not self.allow_movement and intent["intent"] in {"move_step", "rotate_step"}:
                intent = {"intent": "scan", "mood": "thinking", "speech": "Movement is disabled from the PC brain.", "params": {"zone": self.zone, "angles": [-35, 0, 35]}}
            result = request(self.base, "POST", "/supervisor/intent", intent | {"source": "pc_brain"}, timeout=30)
            scan = extract_scan_result(result)
            if scan is not None:
                self.last_scan = scan
            self.last_intent = intent["intent"] if result.get("accepted") else None
            return {"ok": True, "snapshot": snapshot, "intent": intent, "result": result}
        request(self.base, "POST", "/heartbeat", timeout=5)
        status = request(self.base, "GET", "/status", timeout=5)
        tick = request(
            self.base,
            "POST",
            "/autonomy/tick",
            {"allow_movement": self.allow_movement, "inject_idle_tick": True},
            timeout=10,
        )
        return {"ok": True, "status": status, "tick": tick}

    def run_forever(self) -> int:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        print(json.dumps({"ok": True, "event": "brain_loop_started", "base": self.base, "allow_movement": self.allow_movement, "supervised_body": self.supervised_body}))
        while self.running:
            try:
                result = self.once()
                if self.supervised_body:
                    print(json.dumps({
                        "ok": True,
                        "intent": result["intent"],
                        "accepted": result["result"].get("accepted"),
                        "reason": result["result"].get("reason"),
                        "summary": supervisor_result_summary(result["result"]),
                    }))
                else:
                    decision = result["tick"].get("decision", {})
                    print(json.dumps({"ok": True, "behavior": decision.get("behavior"), "reason": decision.get("reason"), "applied": result["tick"].get("applied", [])}))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                print(json.dumps({"ok": False, "error": repr(exc)}), file=sys.stderr)
            time.sleep(self.interval)
        print(json.dumps({"ok": True, "event": "brain_loop_stopped"}))
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cleo Rover PC-side brain loop")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--allow-movement", action="store_true", help="Allow PC brain to request Pi-validated tiny movement")
    parser.add_argument("--supervised-body", action="store_true", help="Use Pi body-agent intent contract instead of legacy autonomy tick")
    parser.add_argument("--zone", default="unknown")
    parser.add_argument("--once", action="store_true", help="Run one brain tick and exit")
    args = parser.parse_args(argv)
    loop = BrainLoop(args.base, args.interval, args.allow_movement, args.supervised_body, args.zone)
    if args.once:
        print(json.dumps(loop.once(), indent=2, sort_keys=True))
        return 0
    return loop.run_forever()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
