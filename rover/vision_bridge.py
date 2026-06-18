from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE = "http://127.0.0.1:8099"


def request(base: str, method: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 30) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        method=method,
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def analysis_prompt(snapshot: dict[str, Any], zone: str) -> str:
    capture = snapshot.get("capture") or {}
    sensors = snapshot.get("sensors") or {}
    turret = snapshot.get("turret") or {}
    return f"""Analyze this Cleo Rover camera snapshot for coarse home mapping.

Image path on rover: {capture.get('path')}
Zone: {zone}
Turret bearing: {turret.get('pan_deg')} deg
Ultrasonic front distance: {sensors.get('front_distance_cm')} cm
Battery: {sensors.get('battery_voltage')} V / {sensors.get('battery_percent')}%

Return JSON only with this shape:
{{
  "summary": "one sentence scene description",
  "labels": ["wall", "chair", "door", "cat", "person"],
  "objects": [{{"label": "chair", "position": "left/center/right", "confidence": 0.7}}],
  "confidence": 0.0-1.0,
  "zone": "{zone}",
  "snapshot_path": "{capture.get('path')}",
  "source": "hermes_vision"
}}
"""


def load_analysis(path_or_json: str) -> dict[str, Any]:
    stripped = path_or_json.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return json.loads(stripped)
    candidate = Path(path_or_json).expanduser()
    text = candidate.read_text() if candidate.exists() else path_or_json
    return json.loads(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture a rover snapshot and bridge external/Hermes vision analysis back into spatial memory")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--zone", default="unknown")
    parser.add_argument("--analysis-json", help="JSON string or path containing Hermes vision analysis to POST to /vision/analysis")
    parser.add_argument("--no-snapshot", action="store_true", help="Skip new snapshot; only post --analysis-json")
    args = parser.parse_args(argv)

    snapshot = None if args.no_snapshot else request(args.base, "POST", "/vision/snapshot", timeout=45)
    if args.analysis_json:
        analysis = load_analysis(args.analysis_json)
        analysis.setdefault("zone", args.zone)
        if snapshot and snapshot.get("capture"):
            analysis.setdefault("snapshot_path", snapshot["capture"].get("path"))
        result = request(args.base, "POST", "/vision/analysis", analysis, timeout=20)
        print(json.dumps({"ok": True, "snapshot": snapshot, "analysis_result": result}, indent=2, sort_keys=True))
        return 0

    print(json.dumps({"ok": True, "snapshot": snapshot, "prompt": analysis_prompt(snapshot or {}, args.zone)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
