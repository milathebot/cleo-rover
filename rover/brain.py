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


class BrainLoop:
    """PC-side autonomy driver.

    Runs next to Hermes/Cleo and periodically ticks the rover body API. The body
    service still owns safety/reflexes; this loop is the quiet decision rhythm
    that makes the rover feel inhabited.
    """

    def __init__(self, base: str, interval: float = 5.0, allow_movement: bool = False) -> None:
        self.base = base
        self.interval = interval
        self.allow_movement = allow_movement
        self.running = True

    def stop(self, *_args) -> None:
        self.running = False

    def once(self) -> dict[str, Any]:
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
        print(json.dumps({"ok": True, "event": "brain_loop_started", "base": self.base, "allow_movement": self.allow_movement}))
        while self.running:
            try:
                result = self.once()
                decision = result["tick"].get("decision", {})
                print(json.dumps({
                    "ok": True,
                    "behavior": decision.get("behavior"),
                    "reason": decision.get("reason"),
                    "attention_level": decision.get("attention_level"),
                    "applied": result["tick"].get("applied", []),
                }))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                print(json.dumps({"ok": False, "error": repr(exc)}), file=sys.stderr)
            time.sleep(self.interval)
        print(json.dumps({"ok": True, "event": "brain_loop_stopped"}))
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cleo Rover PC-side autonomy brain loop")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--allow-movement", action="store_true", help="Allow autonomy to request tiny movement; body still must have motors armed")
    parser.add_argument("--once", action="store_true", help="Run one autonomy tick and exit")
    args = parser.parse_args(argv)
    loop = BrainLoop(args.base, args.interval, args.allow_movement)
    if args.once:
        print(json.dumps(loop.once(), indent=2, sort_keys=True))
        return 0
    return loop.run_forever()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
