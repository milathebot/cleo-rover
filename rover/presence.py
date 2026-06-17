from __future__ import annotations

import argparse
import json
import signal
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from .choreo import run_presence_tick, set_rgb_mode

DEFAULT_BASE = "http://127.0.0.1:8099"


def request(base: str, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        method=method,
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def loop(args: argparse.Namespace) -> int:
    stop = False

    def handle_signal(signum: int, frame: object) -> None:  # noqa: ARG001
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    request_fn = lambda method, path, payload=None: request(args.base, method, path, payload)
    tick = 0
    last_snapshot_at = 0.0
    print("presence loop starting", flush=True)
    while not stop:
        now = time.time()
        take_snapshot = args.snapshot_every > 0 and (now - last_snapshot_at) >= args.snapshot_every
        if take_snapshot:
            last_snapshot_at = now
        try:
            result = run_presence_tick(
                request_fn,
                glance=not args.no_glance and tick % max(1, args.glance_every) == 0,
                snapshot=take_snapshot,
            )
            print(json.dumps({"ok": True, "tick": tick, "rgb_mode": result.get("rgb_mode"), "snapshot": bool(take_snapshot)}), flush=True)
        except Exception as exc:  # keep a presence daemon alive through transient service/camera hiccups
            print(json.dumps({"ok": False, "tick": tick, "error": repr(exc)}), flush=True)
            try:
                set_rgb_mode(request_fn, "error")
            except Exception:
                pass
        tick += 1
        deadline = time.time() + args.interval
        while not stop and time.time() < deadline:
            time.sleep(min(0.25, deadline - time.time()))

    try:
        request_fn("POST", "/stop", None)
        request_fn("POST", "/turret", {"pan_deg": 0})
        set_rgb_mode(request_fn, "off")
    except Exception:
        pass
    print("presence loop stopped", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Non-driving Cleo Rover presence loop")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--interval", type=float, default=8.0)
    parser.add_argument("--snapshot-every", type=float, default=0.0, help="Seconds between camera snapshots; 0 disables")
    parser.add_argument("--glance-every", type=int, default=3, help="Run a tiny turret glance every N ticks")
    parser.add_argument("--no-glance", action="store_true")
    args = parser.parse_args(argv)
    if args.interval < 2:
        raise SystemExit("--interval must be >= 2 seconds")
    return loop(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
