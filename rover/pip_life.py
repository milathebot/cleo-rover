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


def request(base: str, method: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 60) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        method=method,
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Pip's periodic office-life loop")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--interval", type=float, default=300.0, help="Seconds between life ticks")
    parser.add_argument("--allow-movement", action="store_true", help="Allow autonomous movement when Pip mode/battery/zone permit it")
    parser.add_argument("--force-first", action="store_true", help="Force the first tick to patrol/act if mode allows")
    parser.add_argument("--once", action="store_true", help="Run one life tick and exit")
    args = parser.parse_args(argv)

    running = True

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    tick = 0
    while running:
        tick += 1
        payload = {
            "allow_movement": args.allow_movement,
            "force": args.force_first and tick == 1,
            "reason": "pip_life_daemon",
            "compact": True,
        }
        try:
            result = request(args.base, "POST", "/pip/life-tick", payload, timeout=90)
            print(json.dumps({"ok": True, "tick": tick, "decision": result.get("decision"), "battery": result.get("battery"), "actions": result.get("actions")}, sort_keys=True), flush=True)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(json.dumps({"ok": False, "tick": tick, "error": repr(exc)}, sort_keys=True), flush=True)
        if args.once:
            break
        deadline = time.time() + max(10.0, args.interval)
        while running and time.time() < deadline:
            time.sleep(0.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
