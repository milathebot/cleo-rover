from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

from .choreo import RGB_MODES, rgb_payload, run_dance, run_presence_tick

DEFAULT_BASE = "http://127.0.0.1:8099"


def request(base: str, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        method=method,
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
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
    sub.add_parser("events")
    sub.add_parser("autonomy")
    sub.add_parser("tick")

    event = sub.add_parser("event")
    event.add_argument("kind", choices=["sound", "speech", "wake_word", "motion", "camera_snapshot", "button", "bump", "obstacle", "battery", "network", "manual_control", "idle_tick"])
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
    elif args.cmd == "events":
        result = request(args.base, "GET", "/events/recent")
    elif args.cmd == "autonomy":
        result = request(args.base, "GET", "/autonomy/state")
    elif args.cmd == "tick":
        result = request(args.base, "POST", "/autonomy/tick", {"allow_movement": False, "inject_idle_tick": True})
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
