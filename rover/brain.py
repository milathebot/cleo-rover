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


def choose_body_intent(snapshot: dict[str, Any], *, zone: str, last_intent: str | None = None) -> dict[str, Any]:
    """Tiny PC/Hermes-side policy: scan often, move rarely, never raw motor duty."""
    flags = set(snapshot.get("safety_flags") or [])
    range_state = (snapshot.get("range_state") or {}).get("state")
    sensors = snapshot.get("sensors") or {}
    status = snapshot.get("status") or {}
    distance = sensors.get("front_distance_cm")
    if flags & {"inconsistent_motor_safety", "sensor_errors"}:
        return {"intent": "stop", "mood": "alert", "speech": "Safety check failed. Stopping.", "params": {}}
    if range_state in {"blocked", "near"} or (distance is not None and float(distance) < 70.0):
        return {"intent": "scan", "mood": "thinking", "speech": "Close obstacle. Scanning.", "params": {"zone": zone, "angles": [-45, -25, 0, 25, 45]}}
    if sensors.get("front_distance_cm") is None:
        return {"intent": "scan", "mood": "thinking", "speech": "Need range before moving.", "params": {"zone": zone, "angles": [-45, -20, 0, 20, 45]}}
    if not status.get("motors_armed"):
        return {"intent": "scan", "mood": "thinking", "speech": "Motors are not armed.", "params": {"zone": zone, "angles": [-35, 0, 35]}}
    if last_intent == "move_step":
        return {"intent": "scan", "mood": "thinking", "speech": "Checking path.", "params": {"zone": zone, "angles": [-35, -15, 0, 15, 35]}}
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
            intent = choose_body_intent(snapshot, zone=self.zone, last_intent=self.last_intent)
            if not self.allow_movement and intent["intent"] in {"move_step", "rotate_step"}:
                intent = {"intent": "scan", "mood": "thinking", "speech": "Movement is disabled from the PC brain.", "params": {"zone": self.zone, "angles": [-35, 0, 35]}}
            result = request(self.base, "POST", "/supervisor/intent", intent | {"source": "pc_brain"}, timeout=30)
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
                    print(json.dumps({"ok": True, "intent": result["intent"], "accepted": result["result"].get("accepted"), "reason": result["result"].get("reason")}))
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
