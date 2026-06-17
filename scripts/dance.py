#!/usr/bin/env python3
"""Bench-safe Cleo Rover dance helper.

Usage on the Pi after the service is running:
    python scripts/dance.py --lifted
    python scripts/dance.py --lifted --intensity 1.15
    python scripts/dance.py --no-motors
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from typing import Any

from rover.choreo import run_dance

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
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code}: {exc.read().decode(errors='replace')}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Cleo's bench-safe first dance")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--lifted", action="store_true", help="Confirm wheels are lifted / bench safe for motor movement")
    parser.add_argument("--no-motors", action="store_true", help="Run only RGB and turret movements")
    parser.add_argument("--intensity", type=float, default=1.0)
    args = parser.parse_args()
    result = run_dance(
        lambda method, path, payload=None: request(args.base, method, path, payload),
        lifted=args.lifted,
        no_motors=args.no_motors,
        intensity=args.intensity,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
