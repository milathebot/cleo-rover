from __future__ import annotations

import asyncio
import os
import time

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse

from .autonomy import AutonomyEngine, EventStore
from .awareness import capture_motion_pair, doctor_report, last_seen_summary, prune_capture_dir, range_state_from_samples
from .config import load_config
from .drivers import RoverBody
from .hub import fetch_hub_snapshot
from .mapping import map_summary, observation_items, scan_item, semantic_events_from_analysis
from .models import AutonomyTickCommand, BehaviorDecision, BodyIntentCommand, DriveCommand, ExpressionCommand, MapFloorTaskCommand, MapScanCommand, MoveStepCommand, MovementPermissionCommand, RGBCommand, RotateStepCommand, RoverEvent, RoverEventKind, RoverStatus, SpatialMemoryItem, TurretCommand, VisionAnalysisCommand, VisualMapScanCommand
from .peripherals import audio_devices, camera_tool, capture_camera_snapshot, play_tone, speak_text
from .supervisor import intent_to_actions, supervisor_snapshot, validate_intent
from .persistence import RoverStore
from .renderer import render_expression
from .safety_sim import scenarios
from .ui import operator_panel_html

ROVER_MODE = os.getenv("CLEO_ROVER_MODE", "sim")
CONFIG = load_config()
body = RoverBody(mode=ROVER_MODE, config=CONFIG)
events = EventStore()
store = RoverStore(CONFIG.life_loop.data_path)
autonomy = AutonomyEngine(CONFIG.life_loop, state=store.load_state(), cooldowns=store.load_cooldowns())
movement_grant: dict | None = None

app = FastAPI(title="Cleo Rover Mk1 Body Service", version="0.1.0")


def body_status_dict() -> dict:
    ready = body.readiness()
    status = {
        "mode": body.mode,
        "motors_armed": ready["motors_armed"],
        "hardware_ready": ready["hardware_ready"],
        "display_ready": ready["display_ready"],
        "stopped": body.state.stopped,
    }
    hub = fetch_hub_snapshot(CONFIG.life_loop.cleo_hub_url)
    status["hub"] = hub.__dict__
    return status


def active_movement_grant() -> dict | None:
    if movement_grant is None:
        return None
    if not movement_grant.get("active") or float(movement_grant.get("expires_at", 0)) <= time.time():
        return None
    return movement_grant


def sensor_safety_event(sensors_now: dict, *, source: str) -> RoverEvent | None:
    distance = sensors_now.get("front_distance_cm")
    if distance is None:
        return None
    try:
        distance_value = float(distance)
    except (TypeError, ValueError):
        return None
    threshold = float(sensors_now.get("front_stop_distance_cm") or CONFIG.safety.front_stop_distance_cm)
    if distance_value >= threshold:
        return None
    return RoverEvent(
        kind=RoverEventKind.obstacle,
        source=source,
        label=f"front obstacle {distance_value:.1f}cm",
        value=distance_value,
        payload={"sensors": sensors_now, "threshold_cm": threshold},
    )


def remember_event(event: RoverEvent) -> RoverEvent:
    saved = store.add_event(event)
    events.add(saved)
    autonomy.update_from_event(saved)
    store.save_state(autonomy.state)
    return saved


def drive_safety(command: DriveCommand, *, require_permission: bool = False) -> tuple[bool, str, DriveCommand]:
    if CONFIG.safety.bench_safe_no_motors:
        return False, "drive rejected: current profile has bench_safe_no_motors=true", command
    if not body.motors_armed:
        return False, "drive rejected: motors are not armed", command
    grant = active_movement_grant()
    if require_permission and grant is None:
        return False, "drive rejected: movement permission grant is required", command
    if grant:
        command = command.model_copy(update={
            "linear": max(-float(grant.get("max_linear", 0.35)), min(float(grant.get("max_linear", 0.35)), command.linear)),
            "turn": max(-float(grant.get("max_turn", 0.7)), min(float(grant.get("max_turn", 0.7)), command.turn)),
        })
    sensors_now = body.sensors()
    distance = sensors_now.get("front_distance_cm")
    if command.linear > 0 and distance is not None and float(distance) < CONFIG.safety.front_stop_distance_cm:
        return False, f"drive rejected: obstacle at {distance}cm is closer than stop threshold {CONFIG.safety.front_stop_distance_cm}cm", command
    return True, "drive allowed", command


async def guarded_drive(command: DriveCommand, *, require_permission: bool = False) -> dict:
    ok, reason, safe_command = drive_safety(command, require_permission=require_permission)
    if not ok:
        await body.stop()
        return {"ok": False, "stopped": True, "reason": reason, "command": command.model_dump()}
    await body.drive(safe_command)
    return {"ok": True, "stopped": body.state.stopped, "reason": reason, "command": safe_command.model_dump(), "movement": active_movement_grant()}


async def apply_decision(decision: BehaviorDecision) -> dict:
    applied = []
    if decision.stop:
        await body.stop()
        applied.append("stop")
    if decision.expression:
        await body.set_expression(decision.expression)
        applied.append("expression")
    if decision.turret:
        await body.set_turret(decision.turret)
        applied.append("turret")
    if decision.drive:
        drive_result = await guarded_drive(decision.drive, require_permission=True)
        applied.append("drive" if drive_result.get("ok") else "drive_rejected")
    # Speech is intentionally a command payload only until speaker playback is wired.
    if decision.speech:
        applied.append("speech_stub")
    store.save_state(autonomy.state)
    store.save_cooldowns(autonomy.last_behavior_at)
    return {"ok": True, "decision": decision.model_dump(), "applied": applied, "state": autonomy.state.model_dump()}


@app.get("/", response_class=HTMLResponse)
def operator_panel() -> str:
    return operator_panel_html()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "mode": body.mode, "name": CONFIG.name, "profile": CONFIG.profile}


@app.get("/status", response_model=RoverStatus)
def status() -> RoverStatus:
    ready = body.readiness()
    sensor_snapshot = body.sensors()
    return RoverStatus(
        mode=body.mode,
        name=CONFIG.name,
        profile=CONFIG.profile,
        online=True,
        stopped=body.state.stopped,
        expression=body.state.expression,
        last_drive=body.state.last_drive,
        turret=body.state.turret,
        battery_percent=sensor_snapshot.get("battery_percent"),
        battery_voltage=sensor_snapshot.get("battery_voltage"),
        camera_ready=body.camera_ready(),
        mic_ready=CONFIG.audio.mic == "usb",
        speaker_ready=bool(CONFIG.audio.speaker_amp),
        display_ready=ready["display_ready"],
        motors_armed=ready["motors_armed"],
        hardware_ready=ready["hardware_ready"],
        safety=CONFIG.safety.model_dump(),
    )


@app.get("/config")
def config() -> dict:
    return CONFIG.public_summary()


@app.post("/drive")
async def drive(command: DriveCommand) -> dict:
    return await guarded_drive(command, require_permission=False)


@app.post("/stop")
async def stop() -> dict:
    await body.stop()
    return {"ok": True, "stopped": True}


@app.post("/expression")
async def expression(command: ExpressionCommand) -> dict:
    await body.set_expression(command)
    return {"ok": True, "expression": command.model_dump()}


@app.get("/expression/preview.png")
def expression_preview() -> Response:
    frame = render_expression(body.state.expression)
    return Response(content=frame.png_bytes(), media_type="image/png")


@app.post("/turret")
async def turret(command: TurretCommand) -> dict:
    await body.set_turret(command)
    return {"ok": True, "turret": command.model_dump()}


@app.post("/rgb")
def rgb(command: RGBCommand) -> dict:
    return body.set_rgb(command)


@app.get("/audio/devices")
def audio_device_report() -> dict:
    return {"ok": True, "devices": audio_devices()}


@app.post("/audio/tone")
def audio_tone(seconds: float = 0.35, hz: int = 880) -> dict:
    return play_tone(seconds=seconds, hz=hz)


@app.post("/speech/say")
def speech_say(text: str) -> dict:
    return speak_text(text)


@app.get("/sensors")
def sensors() -> dict:
    return body.sensors()


@app.get("/doctor")
def doctor() -> dict:
    sensors_now = body.sensors()
    return doctor_report(
        data_path=CONFIG.life_loop.data_path,
        capture_dir=CONFIG.camera.capture_dir,
        status=status().model_dump(),
        sensors=sensors_now,
    )


@app.get("/preflight")
def preflight(mode: str = "presence") -> dict:
    sensors_now = body.sensors()
    status_now = status().model_dump()
    doctor_now = doctor_report(
        data_path=CONFIG.life_loop.data_path,
        capture_dir=CONFIG.camera.capture_dir,
        status=status_now,
        sensors=sensors_now,
    )
    checks = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    add("service_online", status_now.get("online") is True, "API returned status")
    add("profile_known", bool(status_now.get("profile")), f"profile={status_now.get('profile')}")
    add("doctor_clean", doctor_now.get("ok") is True, "; ".join(doctor_now.get("warnings") or ["no warnings"]))
    add("sensors_shape", isinstance(sensors_now, dict) and "errors" in sensors_now, "sensor snapshot returned")

    if mode in {"presence", "boot", "safe"}:
        add("no_motor_profile", status_now.get("motors_armed") is False, "motors must be unarmed for presence/boot")
        add("bench_safe", status_now.get("safety", {}).get("bench_safe_no_motors") is True, "bench_safe_no_motors should be true")
    elif mode in {"floor", "floor-cautious"}:
        add("floor_profile", status_now.get("profile") == "hardware-floor-cautious", "floor tests require hardware-floor-cautious profile")
        add("motor_profile_armed", status_now.get("motors_armed") is True, "floor profile should arm motors only after explicit mode switch")
        front_distance = sensors_now.get("front_distance_cm")
        front_clear = front_distance is None or float(front_distance) >= max(45.0, CONFIG.safety.front_stop_distance_cm + 20)
        add("ultrasonic_ready", bool(sensors_now.get("ultrasonic_ready")), "front range needed before floor movement")
        add("front_clear", front_clear, "front must be clear for tiny floor step")
    else:
        add("mode_valid", False, "mode must be presence, boot, safe, floor, or floor-cautious")

    ok = all(check["ok"] for check in checks)
    return {
        "ok": ok,
        "mode": mode,
        "checks": checks,
        "status": status_now,
        "sensors": sensors_now,
        "doctor": doctor_now,
        "next_step": "safe to continue this mode" if ok else "fix failed checks before continuing",
    }


@app.post("/data/prune")
def prune_data(keep_days: int = 30, keep_snapshots: int = 500, dry_run: bool = False) -> dict:
    event_result = store.prune_events(keep_days=keep_days, dry_run=dry_run)
    capture_result = prune_capture_dir(CONFIG.camera.capture_dir, keep=keep_snapshots, dry_run=dry_run)
    return {"ok": True, "events": event_result, "captures": capture_result}


@app.get("/last-seen")
def last_seen(limit: int = 20) -> dict:
    return {"ok": True, "items": last_seen_summary(store.list_spatial(500), limit=limit)}


@app.post("/events")
def post_event(event: RoverEvent) -> dict:
    saved = store.add_event(event)
    events.add(saved)
    autonomy.update_from_event(saved)
    store.save_state(autonomy.state)
    return {"ok": True, "event": saved.model_dump(), "state": autonomy.state.model_dump()}


@app.get("/events/recent")
def recent_events(limit: int = 25) -> dict:
    merged = store.recent_events(limit=max(1, min(limit, 100)))
    return {"ok": True, "events": [event.model_dump() for event in merged]}


@app.post("/heartbeat")
def heartbeat() -> dict:
    event = store.add_event(RoverEvent(kind=RoverEventKind.network, source="heartbeat", payload={"connected": True}))
    events.add(event)
    autonomy.update_from_event(event)
    return {"ok": True, "time": event.timestamp, "state": autonomy.state.model_dump()}


@app.post("/hearing/simulate")
def simulate_hearing(event: RoverEvent | None = None) -> dict:
    event = event or RoverEvent(kind=RoverEventKind.sound, source="sim_mic", label="sound spike", value=0.65)
    if event.kind not in {RoverEventKind.sound, RoverEventKind.speech, RoverEventKind.wake_word}:
        event = event.model_copy(update={"kind": RoverEventKind.sound})
    saved = store.add_event(event)
    events.add(saved)
    autonomy.update_from_event(saved)
    return {"ok": True, "event": saved.model_dump(), "state": autonomy.state.model_dump()}


@app.post("/vision/snapshot")
def vision_snapshot(event: RoverEvent | None = None) -> dict:
    capture = None
    if body.mode == "hardware":
        capture = capture_camera_snapshot(CONFIG.camera.capture_dir, width=CONFIG.camera.width, height=CONFIG.camera.height)
        sensors_now = body.sensors()
        payload = {"simulated": False, "capture": capture, "sensors": sensors_now, "turret": body.state.turret.model_dump()}
        label = "snapshot" if capture.get("ok") else "snapshot failed"
        event = RoverEvent(kind=RoverEventKind.camera_snapshot, source="camera", label=label, payload=payload)
    else:
        event = event or RoverEvent(kind=RoverEventKind.camera_snapshot, source="sim_camera", label="snapshot", payload={"simulated": True})
    if event.kind not in {RoverEventKind.camera_snapshot, RoverEventKind.motion}:
        event = event.model_copy(update={"kind": RoverEventKind.camera_snapshot})
    saved = store.add_event(event)
    events.add(saved)
    autonomy.update_from_event(saved)
    return {
        "ok": bool(capture.get("ok", True)) if capture is not None else True,
        "event": saved.model_dump(),
        "capture": capture,
        "sensors": saved.payload.get("sensors"),
        "turret": saved.payload.get("turret"),
        "analysis_stub": {
            "person_seen": bool(saved.payload.get("person_seen", False)),
            "motion_seen": saved.kind == RoverEventKind.motion or bool(saved.payload.get("motion_seen", False)),
            "needs_external_vision": True,
        },
        "state": autonomy.state.model_dump(),
    }


@app.post("/vision/motion")
def vision_motion(delay_seconds: float = 0.6) -> dict:
    if body.mode != "hardware":
        return {"ok": True, "simulated": True, "motion": {"motion_detected": False, "mean_delta": 0.0}}
    tool = camera_tool()
    if not tool:
        return {"ok": False, "error": "no rpicam-still/libcamera-still command found"}
    command = [tool, "-o", "{output}", "--width", "640", "--height", "480", "--timeout", "500", "--nopreview"]
    result = capture_motion_pair(command, CONFIG.camera.capture_dir, delay_seconds=delay_seconds)
    if result.get("ok") and result.get("motion", {}).get("motion_detected"):
        remember_event(RoverEvent(kind=RoverEventKind.motion, source="local_motion", label="frame difference motion", payload=result))
    return result


@app.post("/vision/analysis")
def vision_analysis(command: VisionAnalysisCommand) -> dict:
    sensors_now = body.sensors()
    distance_cm = sensors_now.get("front_distance_cm")
    bearing = body.state.turret.pan_deg
    payload = command.model_dump()
    payload.update({"sensors": sensors_now, "bearing_deg": bearing})
    saved = store.add_event(RoverEvent(kind=RoverEventKind.vision_analysis, source=command.source, label="vision analysis", payload=payload))
    events.add(saved)
    autonomy.update_from_event(saved)
    items = observation_items(zone=command.zone, bearing_deg=bearing, distance_cm=distance_cm, analysis=command.model_dump())
    stored = [store.upsert_spatial(item) for item in items]
    semantic_events = [remember_event(event) for event in semantic_events_from_analysis(command.model_dump(), distance_cm=distance_cm, bearing_deg=bearing)]
    return {"ok": True, "event": saved.model_dump(), "semantic_events": [event.model_dump() for event in semantic_events], "items": [item.model_dump() for item in stored], "sensors": sensors_now}


@app.get("/autonomy/state")
def autonomy_state() -> dict:
    return {
        "ok": True,
        "state": autonomy.state.model_dump(),
        "cooldowns": autonomy.last_behavior_at,
        "hub": body_status_dict().get("hub"),
        "recent_events": [event.model_dump() for event in store.recent_events(10)],
    }


@app.get("/autonomy/dashboard", response_class=HTMLResponse)
def autonomy_dashboard() -> str:
    state = autonomy.state
    recent = store.recent_events(8)
    spatial = store.list_spatial(8)
    rows = "".join(f"<li><b>{e.kind.value}</b> {e.label or ''} <small>{e.source}</small></li>" for e in recent)
    places = "".join(f"<li><b>{m.label}</b> {m.kind} {m.zone or ''} conf={m.confidence:.2f}</li>" for m in spatial)
    return f"""<!doctype html><html><head><title>Cleo Rover Autonomy</title>
    <style>body{{background:#080712;color:#f4efff;font-family:system-ui;margin:24px}}section{{border:1px solid #47347a;border-radius:18px;padding:16px;margin:12px 0;background:#121026}}code{{color:#8ff}}</style></head>
    <body><h1>Cleo Rover Autonomy</h1><section><h2>State</h2><p>Mood: <code>{state.mood}</code> Attention: <code>{state.attention:.2f}</code> Curiosity: <code>{state.curiosity:.2f}</code> Energy: <code>{state.energy:.2f}</code> DND: <code>{state.do_not_disturb}</code></p><p>Intent: <code>{state.current_intent}</code> Last behavior: <code>{state.last_behavior}</code></p></section><section><h2>Recent events</h2><ul>{rows}</ul></section><section><h2>Spatial memory</h2><ul>{places}</ul></section></body></html>"""


@app.get("/cleo-hub")
def cleo_hub_snapshot() -> dict:
    return {"ok": True, "hub": body_status_dict().get("hub")}


@app.post("/map/remember")
def remember_spatial(item: SpatialMemoryItem) -> dict:
    saved = store.upsert_spatial(item)
    return {"ok": True, "item": saved.model_dump()}


@app.get("/map")
def map_memory(limit: int = 100) -> dict:
    return {"ok": True, "items": [item.model_dump() for item in store.list_spatial(limit)]}


@app.get("/map/summary")
def map_memory_summary(limit: int = 500) -> dict:
    items = store.list_spatial(limit)
    return {"ok": True, "summary": map_summary(items), "items": [item.model_dump() for item in items[:25]]}


@app.get("/situation")
def situation() -> dict:
    sensors_now = body.sensors()
    obstacle = sensor_safety_event(sensors_now, source="situation")
    items = store.list_spatial(100)
    range_state = range_state_from_samples([sensors_now.get("front_distance_cm")], stop_cm=CONFIG.safety.front_stop_distance_cm)
    risk = "blocked" if obstacle or range_state["state"] == "blocked" else "clear_or_unknown"
    return {
        "ok": True,
        "risk": risk,
        "range_state": range_state,
        "obstacle": obstacle.model_dump() if obstacle else None,
        "status": status().model_dump(),
        "sensors": sensors_now,
        "movement": movement_status(),
        "map_summary": map_summary(items),
        "last_seen": last_seen_summary(items, limit=10),
        "recent_events": [event.model_dump() for event in store.recent_events(8)],
    }


@app.post("/map/scan")
async def map_scan(command: MapScanCommand) -> dict:
    observations = []
    for angle in command.angles:
        clamped = max(CONFIG.turret.pan_min_deg, min(CONFIG.turret.pan_max_deg, float(angle)))
        await body.set_turret(TurretCommand(pan_deg=clamped))
        await asyncio.sleep(command.settle_ms / 1000)
        sensors_now = body.sensors()
        distance_cm = sensors_now.get("front_distance_cm")
        item = scan_item(command.zone, clamped, distance_cm, payload={"sensors": sensors_now})
        saved_item = store.upsert_spatial(item)
        event = store.add_event(
            RoverEvent(
                kind=RoverEventKind.map_observation,
                source="map_scan",
                label=f"{command.zone} {clamped:+.1f} deg",
                value=distance_cm,
                payload={"zone": command.zone, "bearing_deg": clamped, "distance_cm": distance_cm, "sensors": sensors_now},
            )
        )
        events.add(event)
        observations.append({"event": event.model_dump(), "item": saved_item.model_dump()})
    await body.set_turret(TurretCommand(pan_deg=0))
    capture = None
    if command.snapshot_center:
        capture = capture_camera_snapshot(CONFIG.camera.capture_dir, width=CONFIG.camera.width, height=CONFIG.camera.height) if body.mode == "hardware" else None
    return {"ok": True, "zone": command.zone, "observations": observations, "capture": capture}


@app.post("/map/visual-scan")
async def visual_map_scan(command: VisualMapScanCommand) -> dict:
    observations = []
    for angle in command.angles:
        clamped = max(CONFIG.turret.pan_min_deg, min(CONFIG.turret.pan_max_deg, float(angle)))
        await body.set_turret(TurretCommand(pan_deg=clamped))
        await asyncio.sleep(command.settle_ms / 1000)
        sensors_now = body.sensors()
        distance_cm = sensors_now.get("front_distance_cm")
        capture = capture_camera_snapshot(CONFIG.camera.capture_dir, width=CONFIG.camera.width, height=CONFIG.camera.height) if body.mode == "hardware" and command.capture_each_angle else None
        item = scan_item(command.zone, clamped, distance_cm, payload={"sensors": sensors_now, "capture": capture})
        saved_item = store.upsert_spatial(item)
        event = store.add_event(
            RoverEvent(
                kind=RoverEventKind.map_observation,
                source="visual_map_scan",
                label=f"{command.zone} visual {clamped:+.1f} deg",
                value=distance_cm,
                payload={"zone": command.zone, "bearing_deg": clamped, "distance_cm": distance_cm, "sensors": sensors_now, "capture": capture, "needs_external_vision": True},
            )
        )
        events.add(event)
        observations.append({"event": event.model_dump(), "item": saved_item.model_dump(), "capture": capture})
    await body.set_turret(TurretCommand(pan_deg=0))
    return {"ok": True, "zone": command.zone, "observations": observations, "needs_external_vision": True}


@app.post("/presence/look-around")
async def presence_look_around(zone: str = "presence") -> dict:
    result = await map_scan(MapScanCommand(zone=zone, angles=[-35, -18, 0, 18, 35], settle_ms=350, snapshot_center=False))
    return {"ok": True, "mode": "no_motor_presence", "movement": "none", "result": result}


@app.post("/presence/remember-room")
async def presence_remember_room(zone: str = "room") -> dict:
    result = await visual_map_scan(VisualMapScanCommand(zone=zone, angles=[-45, -25, 0, 25, 45], settle_ms=400, capture_each_angle=True))
    return {"ok": True, "mode": "no_motor_presence", "movement": "none", "result": result, "next_step": "Send each capture to Hermes vision, then POST results to /vision/analysis."}


@app.post("/movement/move-step")
async def move_step(command: MoveStepCommand) -> dict:
    linear = 0.28 if command.forward_cm >= 0 else -0.25
    duration = int(min(500, max(180, abs(command.forward_cm) * 28)))
    result = await guarded_drive(DriveCommand(linear=linear, turn=0, duration_ms=duration), require_permission=command.require_permission)
    result["step"] = command.model_dump()
    return result


@app.post("/movement/rotate-step")
async def rotate_step(command: RotateStepCommand) -> dict:
    # Manual rotate-step uses the same gentle calibration as supervised escape.
    # Larger spins should be built from multiple rotate+scan cycles.
    turn = 0.45 if command.deg >= 0 else -0.45
    duration = int(min(320, max(120, abs(command.deg) * 12)))
    result = await guarded_drive(DriveCommand(linear=0, turn=turn, duration_ms=duration), require_permission=command.require_permission)
    result["step"] = command.model_dump()
    return result


@app.post("/movement/grant")
def grant_movement(command: MovementPermissionCommand) -> dict:
    global movement_grant
    expires_at = time.time() + command.duration_seconds
    movement_grant = command.model_dump() | {"expires_at": expires_at, "active": command.allow_movement}
    event = store.add_event(RoverEvent(kind=RoverEventKind.movement_permission, source="operator", label=command.task, payload=movement_grant))
    events.add(event)
    return {"ok": True, "movement": movement_grant, "event": event.model_dump()}


@app.post("/movement/revoke")
async def revoke_movement() -> dict:
    global movement_grant
    movement_grant = None
    await body.stop()
    return {"ok": True, "movement": None, "stopped": True}


@app.get("/movement/status")
def movement_status() -> dict:
    active = movement_grant is not None and bool(movement_grant.get("active")) and float(movement_grant.get("expires_at", 0)) > time.time()
    return {"ok": True, "active": active, "movement": movement_grant}


@app.get("/supervisor/status")
def supervisor_status() -> dict:
    return supervisor_snapshot(
        status=status().model_dump(),
        sensors=body.sensors(),
        movement=movement_status(),
        autonomy=autonomy.state.model_dump(),
    )


@app.post("/supervisor/intent")
async def supervisor_intent(command: BodyIntentCommand) -> dict:
    status_now = status().model_dump()
    sensors_now = body.sensors()
    movement_now = movement_status()
    ok, reason = validate_intent(command, status=status_now, sensors=sensors_now, movement=movement_now)
    if not ok:
        await body.stop()
        return {"ok": False, "accepted": False, "reason": reason, "stopped": True, "snapshot": supervisor_status()}
    actions = intent_to_actions(command)
    applied = []
    for action in actions:
        kind = action["kind"]
        payload = action.get("command") or {}
        if kind == "stop":
            applied.append({"kind": kind, "result": await stop()})
        elif kind == "expression":
            applied.append({"kind": kind, "result": await expression(ExpressionCommand.model_validate(payload))})
        elif kind == "rgb":
            applied.append({"kind": kind, "result": rgb(RGBCommand.model_validate(payload))})
        elif kind == "turret":
            applied.append({"kind": kind, "result": await turret(TurretCommand.model_validate(payload))})
        elif kind == "scan":
            applied.append({"kind": kind, "result": await map_scan(MapScanCommand.model_validate(payload))})
        elif kind == "drive":
            applied.append({"kind": kind, "result": await guarded_drive(DriveCommand.model_validate(payload), require_permission=True)})
    if command.speech:
        applied.append({"kind": "speech", "result": speak_text(command.speech)})
    event = remember_event(RoverEvent(kind=RoverEventKind.manual_control, source=command.source, label=command.intent, payload={"intent": command.model_dump(), "applied": applied}))
    return {"ok": True, "accepted": True, "reason": reason, "applied": applied, "event": event.model_dump(), "snapshot": supervisor_status()}


@app.post("/tasks/map-floor")
async def map_floor_task(command: MapFloorTaskCommand) -> dict:
    global movement_grant
    grant = MovementPermissionCommand(
        task=f"map-floor:{command.zone}",
        allow_movement=command.allow_movement,
        duration_seconds=600,
        max_linear=0.25,
        max_turn=0.45,
        notes=command.notes or "Conservative floor mapping task",
    )
    expires_at = time.time() + grant.duration_seconds
    movement_grant = grant.model_dump() | {"expires_at": expires_at, "active": grant.allow_movement}
    event = store.add_event(RoverEvent(kind=RoverEventKind.movement_permission, source="map_floor_task", label=grant.task, payload=movement_grant | {"zone": command.zone}))
    events.add(event)
    plan: list[dict] = []
    initial_scan = await map_scan(MapScanCommand(zone=command.zone, angles=[-45, -20, 0, 20, 45], settle_ms=200))
    plan.append({"kind": "scan", "result": initial_scan})
    if command.allow_movement:
        for step in range(command.steps):
            sensors_now = body.sensors()
            distance = sensors_now.get("front_distance_cm")
            if distance is not None and float(distance) < max(45.0, CONFIG.safety.front_stop_distance_cm + 20):
                plan.append({"kind": "halt", "reason": f"front distance {distance}cm is too close for floor mapping step", "sensors": sensors_now})
                break
            move = await move_step(MoveStepCommand(forward_cm=8, require_permission=True))
            plan.append({"kind": "move-step", "step": step + 1, "result": move})
            await asyncio.sleep(0.3)
            scan = await map_scan(MapScanCommand(zone=command.zone, angles=[-30, 0, 30], settle_ms=200))
            plan.append({"kind": "scan", "step": step + 1, "result": scan})
            if not move.get("ok"):
                break
    await body.stop()
    return {
        "ok": True,
        "task": movement_grant | {"zone": command.zone, "steps": command.steps},
        "plan": plan,
        "event": event.model_dump(),
        "safety": "Conservative floor mapping only moves if allow_movement=true, an active grant exists, motors are armed, and front range is clear.",
    }


@app.post("/safety/simulate")
async def safety_simulate(name: str | None = None) -> dict:
    out = []
    for scenario in scenarios():
        if name and scenario.name != name:
            continue
        saved = store.add_event(scenario.event)
        decision = autonomy.decide(recent_events=[saved], body_status=body_status_dict(), allow_movement=True)
        result = await apply_decision(decision)
        out.append({"scenario": scenario.name, "expected": scenario.expected_behavior, "decision": result["decision"], "passed": result["decision"]["behavior"] == scenario.expected_behavior})
    return {"ok": True, "results": out}


@app.post("/autonomy/tick")
async def autonomy_tick(command: AutonomyTickCommand | None = None) -> dict:
    command = command or AutonomyTickCommand()
    sensors_now = body.sensors()
    obstacle = sensor_safety_event(sensors_now, source="autonomy_tick")
    if obstacle:
        remember_event(obstacle)
    if command.inject_idle_tick:
        idle = store.add_event(RoverEvent(kind=RoverEventKind.idle_tick, source="autonomy", timestamp=time.time()))
        events.add(idle)
        autonomy.update_from_event(idle)
    decision = autonomy.decide(
        recent_events=events.recent(8),
        body_status=body_status_dict(),
        allow_movement=command.allow_movement,
    )
    return await apply_decision(decision)
