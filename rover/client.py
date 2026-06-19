from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

from .choreo import RGB_MODES, rgb_payload, run_dance, run_presence_tick

DEFAULT_BASE = "http://127.0.0.1:8099"


def request(base: str, method: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 5) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        method=method,
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise SystemExit(f"HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"Connection failed: {e}") from e


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cleo Rover operator CLI")
    parser.add_argument("--base", default=DEFAULT_BASE, help="Rover base URL")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("health")
    sub.add_parser("status")
    sub.add_parser("stop")
    sub.add_parser("sensors")
    sub.add_parser("doctor")
    sub.add_parser("events")
    sub.add_parser("autonomy")
    sub.add_parser("tick")
    sub.add_parser("map")
    sub.add_parser("map-summary")
    sub.add_parser("situation")
    sub.add_parser("last-seen")
    sub.add_parser("motion-check")
    sub.add_parser("look-around")

    prune_data = sub.add_parser("prune-data")
    prune_data.add_argument("--keep-days", type=int, default=30)
    prune_data.add_argument("--keep-snapshots", type=int, default=500)
    prune_data.add_argument("--dry-run", action="store_true")

    remember_room = sub.add_parser("remember-room")
    remember_room.add_argument("--zone", default="room")
    floor_precheck = sub.add_parser("floor-precheck")
    floor_precheck.add_argument("--zone", default="floor")
    floor_precheck.add_argument("--angles", default="-30,0,30")

    floor_map_dry_run = sub.add_parser("floor-map-dry-run")
    floor_map_dry_run.add_argument("--zone", default="floor")
    floor_map_dry_run.add_argument("--steps", type=int, default=3)
    sub.add_parser("movement-status")
    sub.add_parser("movement-revoke")

    map_scan = sub.add_parser("map-scan")
    map_scan.add_argument("--zone", default="unknown")
    map_scan.add_argument("--angles", default="-45,-25,0,25,45", help="Comma-separated turret pan angles")
    map_scan.add_argument("--settle-ms", type=int, default=250)
    map_scan.add_argument("--snapshot-center", action="store_true")

    visual_map_scan = sub.add_parser("visual-map-scan")
    visual_map_scan.add_argument("--zone", default="unknown")
    visual_map_scan.add_argument("--angles", default="-45,-25,0,25,45", help="Comma-separated turret pan angles")
    visual_map_scan.add_argument("--settle-ms", type=int, default=300)
    visual_map_scan.add_argument("--no-capture-each-angle", action="store_true")

    movement_grant = sub.add_parser("movement-grant")
    movement_grant.add_argument("task")
    movement_grant.add_argument("--allow-movement", action="store_true")
    movement_grant.add_argument("--duration-seconds", type=int, default=300)
    movement_grant.add_argument("--max-linear", type=float, default=0.35)
    movement_grant.add_argument("--max-turn", type=float, default=0.7)
    movement_grant.add_argument("--notes", default=None)

    map_floor = sub.add_parser("map-floor")
    map_floor.add_argument("--zone", default="floor")
    map_floor.add_argument("--allow-movement", action="store_true")
    map_floor.add_argument("--steps", type=int, default=3)
    map_floor.add_argument("--notes", default=None)

    move_step = sub.add_parser("move-step")
    move_step.add_argument("--forward-cm", type=float, default=10.0)
    move_step.add_argument("--no-permission-required", action="store_true")

    rotate_step = sub.add_parser("rotate-step")
    rotate_step.add_argument("--deg", type=float, default=15.0)
    rotate_step.add_argument("--no-permission-required", action="store_true")

    look_remember = sub.add_parser("look-remember")
    look_remember.add_argument("--zone", default="unknown")
    look_remember.add_argument("--pan", type=float, default=0.0)
    look_remember.add_argument("--analysis-json", default=None, help="Optional JSON string to post to /vision/analysis after snapshot")

    event = sub.add_parser("event")
    event.add_argument("kind", choices=["sound", "speech", "wake_word", "motion", "camera_snapshot", "button", "bump", "obstacle", "battery", "network", "manual_control", "idle_tick", "vision_analysis", "map_observation", "movement_permission"])
    event.add_argument("--source", default="cli")
    event.add_argument("--label", default=None)
    event.add_argument("--value", type=float, default=None)

    sub.add_parser("hear")
    sub.add_parser("snapshot")

    rgb = sub.add_parser("rgb")
    rgb.add_argument("--red", type=int, default=0)
    rgb.add_argument("--green", type=int, default=0)
    rgb.add_argument("--blue", type=int, default=0)
    rgb.add_argument("--brightness", type=int, default=24)

    rgb_mode = sub.add_parser("rgb-mode")
    rgb_mode.add_argument("mode", choices=sorted(RGB_MODES))

    dance = sub.add_parser("dance")
    dance.add_argument("--lifted", action="store_true", help="Confirm wheels are lifted / bench safe for motor movement")
    dance.add_argument("--no-motors", action="store_true", help="Run only RGB and turret movements")
    dance.add_argument("--intensity", type=float, default=1.0, help="Motor intensity multiplier, clamped to 0.2..1.4")

    presence = sub.add_parser("presence-tick")
    presence.add_argument("--no-glance", action="store_true")
    presence.add_argument("--snapshot", action="store_true")
    presence.add_argument("--cleanup", action="store_true", help="Turn RGB off and center turret after this one-shot tick")

    safe_mode = sub.add_parser("safe-mode")
    safe_mode.add_argument("--amber", action="store_true", help="Leave amber safety LEDs on instead of turning LEDs off")

    drive = sub.add_parser("drive")
    drive.add_argument("--linear", type=float, default=0.0)
    drive.add_argument("--turn", type=float, default=0.0)
    drive.add_argument("--duration-ms", type=int, default=250)

    expr = sub.add_parser("expression")
    expr.add_argument("mode", choices=["idle", "listening", "thinking", "speaking", "alert", "charging", "disconnected", "manual", "curious", "watching", "seeking", "sleeping", "shy", "proud", "low_power"])
    expr.add_argument("--text", default=None)
    expr.add_argument("--brightness", type=float, default=0.6)

    turret = sub.add_parser("turret")
    turret.add_argument("--pan-deg", type=float, default=0.0)

    args = parser.parse_args(argv)

    if args.cmd == "health":
        result = request(args.base, "GET", "/health")
    elif args.cmd == "status":
        result = request(args.base, "GET", "/status")
    elif args.cmd == "sensors":
        result = request(args.base, "GET", "/sensors")
    elif args.cmd == "doctor":
        result = request(args.base, "GET", "/doctor")
    elif args.cmd == "events":
        result = request(args.base, "GET", "/events/recent")
    elif args.cmd == "map":
        result = request(args.base, "GET", "/map")
    elif args.cmd == "map-summary":
        result = request(args.base, "GET", "/map/summary")
    elif args.cmd == "situation":
        result = request(args.base, "GET", "/situation")
    elif args.cmd == "last-seen":
        result = request(args.base, "GET", "/last-seen")
    elif args.cmd == "motion-check":
        result = request(args.base, "POST", "/vision/motion", timeout=30)
    elif args.cmd == "look-around":
        result = request(args.base, "POST", "/presence/look-around", timeout=20)
    elif args.cmd == "remember-room":
        result = request(args.base, "POST", f"/presence/remember-room?zone={args.zone}", timeout=45)
    elif args.cmd == "prune-data":
        result = request(args.base, "POST", f"/data/prune?keep_days={args.keep_days}&keep_snapshots={args.keep_snapshots}&dry_run={str(args.dry_run).lower()}", timeout=60)
    elif args.cmd == "floor-precheck":
        angles = [float(part.strip()) for part in args.angles.split(",") if part.strip()]
        safe = request(args.base, "POST", "/stop")
        status_now = request(args.base, "GET", "/status")
        sensors_now = request(args.base, "GET", "/sensors")
        movement = request(args.base, "GET", "/movement/status")
        scan = request(args.base, "POST", "/map/scan", {"zone": args.zone, "angles": angles, "settle_ms": 250, "snapshot_center": False}, timeout=max(10.0, 3.0 + len(angles) * 2.0))
        front = sensors_now.get("front_distance_cm")
        clear = front is None or float(front) >= max(45.0, float(sensors_now.get("front_stop_distance_cm") or 18.0) + 20.0)
        result = {
            "ok": True,
            "zone": args.zone,
            "safe_stop": safe,
            "status": status_now,
            "sensors": sensors_now,
            "movement": movement,
            "scan": scan,
            "floor_ready_without_motor_test": bool(status_now.get("hardware_ready") and sensors_now.get("ultrasonic_ready") and sensors_now.get("camera", {}).get("ready")),
            "front_clear_for_tiny_step": clear,
            "note": "Precheck does not arm motors. Telegram floor driving remains blocked until explicit movement safety is enabled separately.",
        }
    elif args.cmd == "floor-map-dry-run":
        result = request(args.base, "POST", "/tasks/map-floor", {"zone": args.zone, "allow_movement": False, "steps": args.steps, "notes": "Telegram dry-run floor map"}, timeout=max(30.0, 10.0 + args.steps * 8.0))
    elif args.cmd == "autonomy":
        result = request(args.base, "GET", "/autonomy/state")
    elif args.cmd == "tick":
        result = request(args.base, "POST", "/autonomy/tick", {"allow_movement": False, "inject_idle_tick": True})
    elif args.cmd == "movement-status":
        result = request(args.base, "GET", "/movement/status")
    elif args.cmd == "movement-revoke":
        result = request(args.base, "POST", "/movement/revoke")
    elif args.cmd == "movement-grant":
        result = request(args.base, "POST", "/movement/grant", {
            "task": args.task,
            "allow_movement": args.allow_movement,
            "duration_seconds": args.duration_seconds,
            "max_linear": args.max_linear,
            "max_turn": args.max_turn,
            "notes": args.notes,
        })
    elif args.cmd == "map-floor":
        timeout = max(30.0, 10.0 + args.steps * 12.0)
        result = request(args.base, "POST", "/tasks/map-floor", {"zone": args.zone, "allow_movement": args.allow_movement, "steps": args.steps, "notes": args.notes}, timeout=timeout)
    elif args.cmd == "map-scan":
        angles = [float(part.strip()) for part in args.angles.split(",") if part.strip()]
        timeout = max(10.0, 3.0 + len(angles) * (args.settle_ms / 1000 + 1.5))
        result = request(args.base, "POST", "/map/scan", {"zone": args.zone, "angles": angles, "settle_ms": args.settle_ms, "snapshot_center": args.snapshot_center}, timeout=timeout)
    elif args.cmd == "visual-map-scan":
        angles = [float(part.strip()) for part in args.angles.split(",") if part.strip()]
        timeout = max(30.0, 5.0 + len(angles) * (args.settle_ms / 1000 + 4.0))
        result = request(args.base, "POST", "/map/visual-scan", {"zone": args.zone, "angles": angles, "settle_ms": args.settle_ms, "capture_each_angle": not args.no_capture_each_angle}, timeout=timeout)
    elif args.cmd == "move-step":
        result = request(args.base, "POST", "/movement/move-step", {"forward_cm": args.forward_cm, "require_permission": not args.no_permission_required})
    elif args.cmd == "rotate-step":
        result = request(args.base, "POST", "/movement/rotate-step", {"deg": args.deg, "require_permission": not args.no_permission_required})
    elif args.cmd == "look-remember":
        request(args.base, "POST", "/turret", {"pan_deg": args.pan})
        snapshot = request(args.base, "POST", "/vision/snapshot", timeout=45)
        analysis_result = None
        if args.analysis_json:
            analysis = json.loads(args.analysis_json)
            analysis.setdefault("zone", args.zone)
            if snapshot.get("capture"):
                analysis.setdefault("snapshot_path", snapshot["capture"].get("path"))
            analysis_result = request(args.base, "POST", "/vision/analysis", analysis, timeout=20)
        result = {"ok": True, "zone": args.zone, "pan_deg": args.pan, "snapshot": snapshot, "analysis_result": analysis_result, "needs_external_vision": analysis_result is None}
    elif args.cmd == "event":
        result = request(args.base, "POST", "/events", {"kind": args.kind, "source": args.source, "label": args.label, "value": args.value})
    elif args.cmd == "hear":
        result = request(args.base, "POST", "/hearing/simulate")
    elif args.cmd == "snapshot":
        result = request(args.base, "POST", "/vision/snapshot")
    elif args.cmd == "rgb":
        result = request(args.base, "POST", "/rgb", {"red": args.red, "green": args.green, "blue": args.blue, "brightness": args.brightness})
    elif args.cmd == "rgb-mode":
        result = request(args.base, "POST", "/rgb", rgb_payload(args.mode))
    elif args.cmd == "dance":
        result = run_dance(lambda method, path, payload=None: request(args.base, method, path, payload), lifted=args.lifted, no_motors=args.no_motors, intensity=args.intensity)
    elif args.cmd == "presence-tick":
        result = run_presence_tick(lambda method, path, payload=None: request(args.base, method, path, payload), glance=not args.no_glance, snapshot=args.snapshot)
        if args.cleanup:
            request(args.base, "POST", "/turret", {"pan_deg": 0})
            cleanup_rgb = request(args.base, "POST", "/rgb", rgb_payload("off"))
            result["cleanup"] = {"turret": {"pan_deg": 0}, "rgb": cleanup_rgb}
    elif args.cmd == "safe-mode":
        request(args.base, "POST", "/stop")
        request(args.base, "POST", "/turret", {"pan_deg": 0})
        rgb = rgb_payload("low_battery" if args.amber else "off")
        rgb_result = request(args.base, "POST", "/rgb", rgb)
        status = request(args.base, "GET", "/status")
        result = {
            "ok": True,
            "stopped": True,
            "turret": {"pan_deg": 0},
            "rgb": rgb_result,
            "status": status,
            "note": "For unattended powered-on presence, run the service with config/rover.hardware.presence.json so motors_armed stays false.",
        }
    elif args.cmd == "stop":
        result = request(args.base, "POST", "/stop")
    elif args.cmd == "drive":
        result = request(args.base, "POST", "/drive", {"linear": args.linear, "turn": args.turn, "duration_ms": args.duration_ms})
    elif args.cmd == "expression":
        result = request(args.base, "POST", "/expression", {"mode": args.mode, "text": args.text, "brightness": args.brightness})
    elif args.cmd == "turret":
        result = request(args.base, "POST", "/turret", {"pan_deg": args.pan_deg})
    else:  # pragma: no cover
        parser.error("unknown command")

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
