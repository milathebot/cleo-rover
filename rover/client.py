from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .choreo import RGB_MODES, rgb_payload, run_dance, run_presence_tick

DEFAULT_BASE = "http://127.0.0.1:8099"


def compact_json_text(value: Any, *, max_chars: int = 2200) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= max_chars else text[: max_chars - 3] + "..."


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.S)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("vision response was not a JSON object")
    return value


def hermes_vision_analysis(snapshot: dict[str, Any], *, zone: str, prompt: str | None = None) -> dict[str, Any]:
    base = os.getenv("CLEO_ROVER_HERMES_API_BASE")
    key = os.getenv("CLEO_ROVER_HERMES_API_KEY")
    model = os.getenv("CLEO_ROVER_HERMES_MODEL", "hermes-agent")
    if not base or not key:
        raise SystemExit("Missing CLEO_ROVER_HERMES_API_BASE/CLEO_ROVER_HERMES_API_KEY for vision-label")
    capture = snapshot.get("capture") or {}
    rel_path = capture.get("path")
    if not rel_path:
        raise SystemExit("Snapshot did not return capture.path")
    image_path = Path(str(rel_path)).expanduser()
    if not image_path.is_absolute():
        image_path = Path.cwd() / image_path
    if not image_path.exists():
        raise SystemExit(f"Snapshot image not found: {image_path}")
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    data_url = f"data:image/jpeg;base64,{b64}"
    sensors = snapshot.get("sensors") or {}
    turret = snapshot.get("turret") or {}
    user_text = prompt or (
        "Analyze this rover camera snapshot for safe indoor navigation and first-adventure readiness. "
        "Return JSON only with: summary, labels, objects, hazards, clear_path, adventure_readiness, confidence. "
        "Use coarse labels only. Note cats/people/cables/stairs/liquid/clutter if visible."
    )
    user_text += (
        f"\nZone: {zone}. Snapshot path: {rel_path}. "
        f"Turret bearing: {turret.get('pan_deg')} deg. "
        f"Ultrasonic front distance: {sensors.get('front_distance_cm')} cm. "
        f"Battery: {sensors.get('battery_voltage')} V / {sensors.get('battery_percent')}%."
    )
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You label images for Pip, a small office rover. Be conservative for safety. "
                    "Return valid JSON only. summary must be one short sentence. labels is a short string list. "
                    "objects is a list of {label, position, confidence}. hazards is a string list. "
                    "clear_path is boolean. adventure_readiness is one of: bench_only, observe_only, ready_for_tiny_floor_step."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": data_url, "detail": "low"}},
                ],
            },
        ],
    }
    api_base = base.rstrip("/")
    url = api_base + "/chat/completions" if api_base.endswith("/v1") else api_base + "/v1/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"content-type": "application/json", "authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    content = str(data["choices"][0]["message"]["content"])
    analysis = parse_json_object(content)
    analysis.setdefault("summary", "Scene labeled by Hermes vision.")
    analysis.setdefault("labels", [])
    analysis.setdefault("objects", [])
    analysis.setdefault("confidence", 0.55)
    analysis["zone"] = zone
    analysis["snapshot_path"] = str(rel_path)
    analysis["source"] = "hermes_vision"
    return analysis


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
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--mode", default="presence", choices=["presence", "boot", "safe", "floor", "floor-cautious"])
    sub.add_parser("events")
    sub.add_parser("autonomy")
    sub.add_parser("tick")
    sub.add_parser("map")
    sub.add_parser("map-summary")
    sub.add_parser("situation")
    sub.add_parser("last-seen")
    sub.add_parser("motion-check")
    sub.add_parser("look-around")

    vision_label = sub.add_parser("vision-label")
    vision_label.add_argument("--zone", default="office")
    vision_label.add_argument("--prompt", default=None)
    vision_label.add_argument("--speak", action="store_true")
    vision_label.add_argument("--compact", action="store_true", help="Print compact adventure-ready result")

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

    first_adventure = sub.add_parser("first-adventure")
    first_adventure.add_argument("--zone", default="office")
    first_adventure.add_argument("--allow-movement", action="store_true")
    first_adventure.add_argument("--duration-seconds", type=int, default=30)
    first_adventure.add_argument("--explore-cycles", type=int, default=4)
    first_adventure.add_argument("--skip-speech", action="store_true")
    first_adventure.add_argument("--no-preflight-required", action="store_true")
    first_adventure.add_argument("--verbose", action="store_true")
    first_adventure.add_argument("--notes", default=None)

    hallway_scout = sub.add_parser("hallway-scout")
    hallway_scout.add_argument("--zone", default="hallway-transition")
    hallway_scout.add_argument("--allow-movement", action="store_true")
    hallway_scout.add_argument("--cycles", type=int, default=8)
    hallway_scout.add_argument("--vision-every", type=int, default=3)
    hallway_scout.add_argument("--no-scan-before-move", action="store_true", help="Skip range scan before each forward step; not recommended near doorways")
    hallway_scout.add_argument("--fixed-step", action="store_true", help="Use --step-cm exactly instead of adaptive clearance-based stride")
    hallway_scout.add_argument("--step-cm", type=float, default=4.0, help="Fixed step size, or fallback when adaptive is disabled")
    hallway_scout.add_argument("--min-step-cm", type=float, default=2.0)
    hallway_scout.add_argument("--max-step-cm", type=float, default=24.0)
    hallway_scout.add_argument("--stride-chunk-cm", type=float, default=6.0, help="Max open-loop chunk inside an adaptive stride; sensors are checked between chunks")
    hallway_scout.add_argument("--clear-cm", type=float, default=75.0)
    hallway_scout.add_argument("--blocked-cm", type=float, default=42.0, help="Top of the 'too close to advance' band / bottom of the creep band")
    hallway_scout.add_argument("--emergency-cm", type=float, default=25.0, help="Below this Pip stops and escapes immediately")
    hallway_scout.add_argument("--pause-seconds", type=float, default=1.0)
    hallway_scout.add_argument("--scan-angles", default="-60,-40,-20,0,20,40,60", help="Comma-separated turret pan angles; defaults avoid shell-clipping extremes")
    hallway_scout.add_argument("--speak", action="store_true")
    hallway_scout.add_argument("--verbose", action="store_true")
    hallway_scout.add_argument("--notes", default=None)

    return_to = sub.add_parser("return-to")
    return_to.add_argument("label", nargs="?", default="charger", help="Landmark label to head back toward, e.g. charger")
    return_to.add_argument("--zone", default="office")
    return_to.add_argument("--allow-movement", action="store_true")

    line_follow = sub.add_parser("line-follow")
    line_follow.add_argument("--zone", default="line")
    line_follow.add_argument("--allow-movement", action="store_true")
    line_follow.add_argument("--duration-seconds", type=int, default=30)
    line_follow.add_argument("--max-cycles", type=int, default=40)
    line_follow.add_argument("--base-linear", type=float, default=0.22)
    line_follow.add_argument("--line-on-value", type=int, default=1)

    sub.add_parser("movement-status")
    sub.add_parser("movement-revoke")
    sub.add_parser("supervisor-status")
    sub.add_parser("pip-brain")
    sub.add_parser("pip-soul")
    sub.add_parser("pip-bridge-status")

    pip = sub.add_parser("pip")
    pip.add_argument("text", nargs="*", help="Pip command text: status, wake, sleep, quiet, social, assistant, greet, patrol, observe, stop, or arbitrary question")
    pip.add_argument("--allow-movement", action="store_true")
    pip.add_argument("--source", default="cli")

    body_intent = sub.add_parser("body-intent")
    body_intent.add_argument("intent", choices=["status", "stop", "scan", "look", "say", "mood", "move_step", "rotate_step", "idle"])
    body_intent.add_argument("--mood", default=None)
    body_intent.add_argument("--speech", default=None)
    body_intent.add_argument("--zone", default="unknown")
    body_intent.add_argument("--forward-cm", type=float, default=8.0)
    body_intent.add_argument("--deg", type=float, default=15.0)

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
    listen = sub.add_parser("listen")
    listen.add_argument("--text", default=None, help="Route this transcript instead of capturing (external STT / testing)")
    listen.add_argument("--seconds", type=float, default=4.0)
    sub.add_parser("snapshot")
    sub.add_parser("audio-devices")
    audio_tone = sub.add_parser("audio-tone")
    audio_tone.add_argument("--seconds", type=float, default=0.35)
    audio_tone.add_argument("--hz", type=int, default=880)
    say = sub.add_parser("say")
    say.add_argument("text")

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
    expr.add_argument("mode", choices=["idle", "happy", "sad", "listening", "thinking", "confused", "speaking", "alert", "mad", "focused", "laugh", "charging", "disconnected", "manual", "curious", "watching", "seeking", "sleeping", "shy", "proud", "low_power"])
    expr.add_argument("--text", default=None)
    expr.add_argument("--brightness", type=float, default=0.6)
    sub.add_parser("display-test")

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
    elif args.cmd == "preflight":
        result = request(args.base, "GET", f"/preflight?mode={args.mode}")
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
    elif args.cmd == "vision-label":
        snapshot = request(args.base, "POST", "/vision/snapshot", timeout=45)
        analysis = hermes_vision_analysis(snapshot, zone=args.zone, prompt=args.prompt)
        analysis_result = request(args.base, "POST", "/vision/analysis", analysis, timeout=20)
        speak_result = None
        if args.speak:
            line = f"I see {analysis.get('summary', 'the room')}."
            readiness = analysis.get("adventure_readiness")
            hazards = analysis.get("hazards") or []
            if hazards:
                line += " I noticed possible hazards, so I will stay cautious."
            elif readiness == "ready_for_tiny_floor_step":
                line += " It looks clear enough for one tiny supervised step."
            else:
                line += " I will keep observing safely for now."
            speak_result = request(args.base, "POST", f"/speech/say?text={urllib.parse.quote(line[:220])}", timeout=20)
        compact = {
            "ok": True,
            "zone": args.zone,
            "snapshot_path": (snapshot.get("capture") or {}).get("path"),
            "summary": analysis.get("summary"),
            "labels": analysis.get("labels"),
            "objects": analysis.get("objects"),
            "hazards": analysis.get("hazards"),
            "clear_path": analysis.get("clear_path"),
            "adventure_readiness": analysis.get("adventure_readiness"),
            "confidence": analysis.get("confidence"),
            "spoken": bool(speak_result and speak_result.get("ok")),
        }
        result = compact if args.compact else {"ok": True, "snapshot": snapshot, "analysis": analysis, "analysis_result": analysis_result, "speech": speak_result}
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
    elif args.cmd == "first-adventure":
        timeout = max(45.0, 15.0 + args.duration_seconds + args.explore_cycles * 5.0)
        result = request(
            args.base,
            "POST",
            "/tasks/first-adventure",
            {
                "zone": args.zone,
                "allow_movement": args.allow_movement,
                "duration_seconds": args.duration_seconds,
                "explore_cycles": args.explore_cycles,
                "require_preflight": not args.no_preflight_required,
                "speak": not args.skip_speech,
                "compact": not args.verbose,
                "notes": args.notes,
            },
            timeout=timeout,
        )
    elif args.cmd == "hallway-scout":
        # Speech and camera/range scans make supervised autonomy runs slower than raw movement.
        # Keep the HTTP client alive long enough for ElevenLabs narration instead of timing out
        # while the Pi-side task is still safely stopping/scanning.
        per_cycle = args.pause_seconds + (18.0 if args.speak else 6.0)
        timeout = max(90.0 if args.speak else 45.0, 30.0 + args.cycles * per_cycle)
        result = request(
            args.base,
            "POST",
            "/tasks/hallway-scout",
            {
                "zone": args.zone,
                "allow_movement": args.allow_movement,
                "cycles": args.cycles,
                "vision_every": args.vision_every,
                "scan_before_move": not args.no_scan_before_move,
                "adaptive_step": not args.fixed_step,
                "step_cm": args.step_cm,
                "min_step_cm": args.min_step_cm,
                "max_step_cm": args.max_step_cm,
                "stride_chunk_cm": args.stride_chunk_cm,
                "clear_cm": args.clear_cm,
                "blocked_cm": args.blocked_cm,
                "emergency_cm": args.emergency_cm,
                "pause_seconds": args.pause_seconds,
                "scan_angles": [float(x.strip()) for x in args.scan_angles.split(",") if x.strip()] if args.scan_angles else None,
                "speak": args.speak,
                "compact": not args.verbose,
                "notes": args.notes,
            },
            timeout=timeout,
        )
    elif args.cmd == "autonomy":
        result = request(args.base, "GET", "/autonomy/state")
    elif args.cmd == "tick":
        result = request(args.base, "POST", "/autonomy/tick", {"allow_movement": False, "inject_idle_tick": True})
    elif args.cmd == "return-to":
        path = f"/tasks/return-to?label={urllib.parse.quote(args.label)}&zone={urllib.parse.quote(args.zone)}&allow_movement={str(args.allow_movement).lower()}"
        result = request(args.base, "POST", path, timeout=30.0)
    elif args.cmd == "line-follow":
        timeout = max(30.0, args.duration_seconds + 15.0)
        result = request(args.base, "POST", "/tasks/line-follow", {
            "zone": args.zone,
            "allow_movement": args.allow_movement,
            "duration_seconds": args.duration_seconds,
            "max_cycles": args.max_cycles,
            "base_linear": args.base_linear,
            "line_on_value": args.line_on_value,
        }, timeout=timeout)
    elif args.cmd == "movement-status":
        result = request(args.base, "GET", "/movement/status")
    elif args.cmd == "movement-revoke":
        result = request(args.base, "POST", "/movement/revoke")
    elif args.cmd == "supervisor-status":
        result = request(args.base, "GET", "/supervisor/status")
    elif args.cmd == "pip-brain":
        result = request(args.base, "GET", "/pip/brain")
    elif args.cmd == "pip-soul":
        result = request(args.base, "GET", "/pip/soul")
    elif args.cmd == "pip-bridge-status":
        result = request(args.base, "GET", "/pip/hermes-bridge")
    elif args.cmd == "pip":
        text = " ".join(args.text).strip() or "status"
        result = request(args.base, "POST", "/pip/command", {"text": text, "source": args.source, "allow_movement": args.allow_movement}, timeout=60)
    elif args.cmd == "body-intent":
        params = {"zone": args.zone}
        if args.intent == "move_step":
            params["forward_cm"] = args.forward_cm
        if args.intent == "rotate_step":
            params["deg"] = args.deg
        result = request(args.base, "POST", "/supervisor/intent", {"intent": args.intent, "mood": args.mood, "speech": args.speech, "params": params, "source": "cli"}, timeout=30)
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
    elif args.cmd == "listen":
        path = f"/hearing/listen?seconds={args.seconds}"
        if args.text:
            path += f"&text={urllib.parse.quote(args.text)}"
        result = request(args.base, "POST", path, timeout=max(20.0, args.seconds + 70.0))
    elif args.cmd == "snapshot":
        result = request(args.base, "POST", "/vision/snapshot")
    elif args.cmd == "audio-devices":
        result = request(args.base, "GET", "/audio/devices")
    elif args.cmd == "audio-tone":
        result = request(args.base, "POST", f"/audio/tone?seconds={args.seconds}&hz={args.hz}")
    elif args.cmd == "say":
        result = request(args.base, "POST", f"/speech/say?text={urllib.parse.quote(args.text)}", timeout=15)
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
    elif args.cmd == "display-test":
        expr_result = request(args.base, "POST", "/expression", {"mode": "curious", "text": "pip", "brightness": 0.65})
        sensors_now = request(args.base, "GET", "/sensors")
        result = {"ok": True, "expression": expr_result, "display": sensors_now.get("display"), "note": "Display should show Pip's abstract curious frame if wired and SPI is enabled."}
    elif args.cmd == "turret":
        result = request(args.base, "POST", "/turret", {"pan_deg": args.pan_deg})
    else:  # pragma: no cover
        parser.error("unknown command")

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
