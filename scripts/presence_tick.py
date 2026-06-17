#!/usr/bin/env python3
"""Run one non-driving Cleo presence tick.

Usage:
    python scripts/presence_tick.py
    python scripts/presence_tick.py --snapshot
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from typing import Any

from rover.choreo import run_presence_tick

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
    parser = argparse.ArgumentParser(description="Run one non-driving Cleo presence tick")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--no-glance", action="store_true")
    parser.add_argument("--snapshot", action="store_true")
    args = parser.parse_args()
    result = run_presence_tick(
        lambda method, path, payload=None: request(args.base, method, path, payload),
        glance=not args.no_glance,
        snapshot=args.snapshot,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
