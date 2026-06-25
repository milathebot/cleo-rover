from __future__ import annotations

import asyncio
import os
import re
import time
import traceback
from typing import Any

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse

from .autonomy import AutonomyEngine, EventStore
from .awareness import capture_motion_pair, cpu_temp_c, doctor_report, last_seen_summary, prune_capture_dir, range_state_from_samples
from .config import load_config
from .drivers import RoverBody
from .hermes_bridge import ask_hermes_as_pip, hermes_configured
from .hub import fetch_hub_snapshot
from .mapping import map_summary, normalize_distance_cm, observation_items, scan_item, semantic_events_from_analysis
from .navigation import (
    ACTION_ADVANCE,
    ACTION_ALIGN_TURN,
    ACTION_CREEP,
    ACTION_EMERGENCY_ESCAPE,
    ACTION_HOLD,
    ACTION_SCAN_TURN,
    DoorwayBands,
    decide_hallway_action,
)
from .odometry import estimate_chunk_distance_cm, motion_model_from
from . import vision_service
from . import voice_daemon
from . import explore
from . import arbiter
from . import social
from . import stuck
from . import vfh as vfh_mod
from . import consolidation as consolidation_mod
from . import perception as perception_mod
from . import cruise as cruise_mod
from . import battery as battery_mod
from . import rgb_affect as rgb_affect_mod
from . import degrade as degrade_mod
from .occupancy import OccupancyGrid, grid_config_from
from .topo_map import TopoMap
from . import topo_executor as topo_exec
from .wall_follow import wall_follow_config_from, wall_follow_step, ACTION_INSIDE_CORNER
from .models import Goal
from .models import AutonomyTickCommand, BehaviorDecision, BodyIntentCommand, DriveCommand, ExpressionCommand, ExpressionMode, FirstAdventureCommand, HallwayScoutCommand, LineFollowCommand, LittleBeingLoopCommand, MapFloorTaskCommand, MapScanCommand, MoveStepCommand, MovementPermissionCommand, PipCommand, PipLifeTickCommand, PipModeCommand, ReactiveExploreCommand, RGBCommand, RotateStepCommand, RoverEvent, RoverEventKind, RoverStatus, SpatialMemoryItem, TurretCommand, VisionAnalysisCommand, VisionAwarenessCommand, VisualMapScanCommand
from .line_follow import decide_line_follow, search_turn
from .peripherals import audio_devices, camera_tool, capture_camera_snapshot, play_tone, speak_text
from .pip_brain import build_pip_brain
from .pip_soul import PIP_SOUL_VERSION, pip_soul_prompt, pip_soul_public
from . import mind
from .brain import choose_body_intent
from .supervisor import intent_to_actions, supervisor_snapshot, validate_intent
from .persistence import RoverStore
from .renderer import render_expression
from .safety_sim import scenarios
from .ui import operator_panel_html

ROVER_MODE = os.getenv("CLEO_ROVER_MODE", "sim")
CONFIG = load_config()
# Single source of truth for cm<->pulse conversions and honest (encoder-less)
# distance estimates. Replaces the old scattered *95/*55/*20 magic constants.
MOTION = motion_model_from(CONFIG.odometry)
body = RoverBody(mode=ROVER_MODE, config=CONFIG)
events = EventStore()
store = RoverStore(CONFIG.life_loop.data_path)
autonomy = AutonomyEngine(CONFIG.life_loop, state=store.load_state(), cooldowns=store.load_cooldowns())
movement_grant: dict | None = None
pip_identity = {
    "name": "Pip",
    "species": "shy office droid",
    "home_base": "office",
    "approved_zones": ["office"],
    "personality": {
        "curiosity": 0.75,
        "shyness": 0.70,
        "boldness": 0.55,
        "talkativeness": 0.25,
        "cat_respect": 0.95,
        "helpfulness": 0.60,
        "independence": 0.70,
    },
}
DEFAULT_PIP_STATE = {
    "mode": "social",
    "awake": True,
    "home_base": "office",
    "current_zone": "office",
    "last_greet_at": None,
    "last_patrol_at": None,
    "last_observe_at": None,
    "last_rescue_at": None,
    "last_life_tick_at": None,
    "boredom": 0.35,
    "mood": "curious",
}
pip_state = {**DEFAULT_PIP_STATE, **(store.load_json("pip_state") or {})}
pip_interrupts: list[dict] = list(store.load_json("pip_interrupts") or [])


def save_pip_runtime() -> None:
    store.save_json("pip_state", pip_state)
    store.save_json("pip_interrupts", pip_interrupts[-50:])


# --- Tier 3 nav/mapping singletons --------------------------------------------
# A body-frame rolling occupancy grid (advisory; informs where to go, never
# relaxes a reflex) and a topological place graph loaded from the store. Both are
# rebuildable; the grid accumulates only when CONFIG.nav.mapping_enabled is on.
NAV_GRID = OccupancyGrid(config=grid_config_from(CONFIG.nav))
VFH_CFG = vfh_mod.vfh_config_from(CONFIG.nav)
WALL_CFG = wall_follow_config_from(CONFIG.nav)
_topo_data = store.load_json("topo_map")
TOPO = (
    TopoMap.from_dict(_topo_data)
    if _topo_data
    else TopoMap(sonar_thresh=CONFIG.nav.topo_sonar_thresh, hist_thresh=CONFIG.nav.topo_hist_thresh, min_votes=CONFIG.nav.topo_min_votes)
)
# Restored from the KV store so "power up and return home" works after a reboot
# (the TOPO graph was already persisted; this is the runtime pointer into it).
_last_topo_node: str | None = store.load_json("last_topo_node")
_heartbeat_count = 0


def set_last_topo_node(node_id: str | None) -> None:
    """Update + persist the current place pointer (survives a power cycle).

    Persists even on clear (None) so a restart can't resurrect a stale place."""
    global _last_topo_node
    _last_topo_node = node_id
    store.save_json("last_topo_node", node_id)
# Continuous-motion ("cruise") singletons. Tasks only auto-start on hardware with
# nav.continuous_motion_enabled; the dry-run endpoint works anywhere.
CRUISE_PARAMS = cruise_mod.cruise_params_from(CONFIG.nav, CONFIG.odometry, CONFIG.safety)
CRUISE_SNAPSHOT = perception_mod.PolarSnapshot()
# Honest battery state-of-charge + health (sag-aware, idle-gated, debounced low).
BATTERY = battery_mod.BatteryEstimator()
_last_battery: Any = None
_rgb_task_handle: Any = None
# Unified, lightweight task history (a finished-product "what has Pip been doing?"
# surface without rewriting every task's response schema).
_task_history: list[dict] = list(store.load_json("task_history") or [])


def record_task_result(name: str, started: float, *, did_move: bool = False, ok: bool = True, extra: dict | None = None) -> dict:
    entry = {"task": name, "at": round(started, 2), "duration_s": round(time.time() - started, 2), "did_move": bool(did_move), "ok": bool(ok)}
    if extra:
        entry.update(extra)
    _task_history.append(entry)
    if len(_task_history) > 50:
        del _task_history[:-50]
    store.save_json("task_history", _task_history[-50:])
    return entry


def update_battery(sensors_now: dict) -> Any:
    """Feed the battery estimator and remember its latest reading (for RGB + arbiter)."""
    global _last_battery
    _last_battery = BATTERY.update(voltage=sensors_now.get("battery_voltage"), motors_active=not body.state.stopped)
    return _last_battery


def current_degradation(sensors_now: dict | None = None, reading: Any = None):
    """Assess Pip's current capability tier (full/scan-only/turret-only/stopped)."""
    sensors_now = sensors_now if sensors_now is not None else body.sensors()
    reading = reading if reading is not None else update_battery(sensors_now)
    rs = body.state.last_reflex_stop
    reflex_active = bool(rs and (time.time() - float(rs.get("time") or 0.0)) < 2.0)
    temp = cpu_temp_c()
    thermal_hot = temp is not None and temp >= float(CONFIG.safety.thermal_hard_c)
    return degrade_mod.assess_degradation(
        motors_armed=body.motors_armed,
        bench_safe=CONFIG.safety.bench_safe_no_motors,
        ultrasonic_ready=bool(sensors_now.get("ultrasonic_ready")),
        battery_critical=bool(getattr(reading, "critical", False)),
        reflex_active=reflex_active,
        thermal_hot=thermal_hot,
    )


def compute_affect_frame(phase: float = 0.0):
    """Map Pip's current feelings + battery/alert state to an RGB affect frame."""
    feelings = pip_feelings()
    rs = body.state.last_reflex_stop
    alert = bool(rs and (time.time() - float(rs.get("time") or 0.0)) < 3.0)
    low_battery = bool(_last_battery and (_last_battery.warn or _last_battery.critical))
    charging = bool(_last_battery and _last_battery.charging)
    return rgb_affect_mod.affect_to_frame(
        str(feelings.get("mood") or "calm"),
        energy=float(feelings.get("energy") or 0.6),
        charging=charging,
        low_battery=low_battery,
        alert=alert,
        asleep=pip_state.get("mode") == "sleep",
        max_brightness=int(CONFIG.life_loop.rgb_max_brightness),
        phase=phase,
    )
_cruise_stop_event: Any = None
_perception_task_handle: Any = None
_cruise_task_handle: Any = None


def save_topo() -> None:
    store.save_json("topo_map", TOPO.to_dict())


def sweep_samples_from_summary(summary: dict) -> list[tuple[float, float | None]]:
    """Convert a scan summary's samples into VFH/grid (bearing, distance_cm) pairs."""
    out: list[tuple[float, float | None]] = []
    for s in summary.get("samples") or []:
        try:
            out.append((float(s["bearing_deg"]), float(s["distance_cm"])))
        except (TypeError, ValueError, KeyError):
            continue
    return out


def sonar_signature_from_summary(summary: dict, angles: list[float]) -> list[float | None]:
    """A fixed-order range vector (place fingerprint) at the requested angles."""
    by_bearing = {round(float(s["bearing_deg"])): float(s["distance_cm"]) for s in (summary.get("samples") or []) if s.get("bearing_deg") is not None and s.get("distance_cm") is not None}
    sig: list[float | None] = []
    for a in angles:
        key = round(float(a))
        match = next((v for b, v in by_bearing.items() if abs(b - key) <= 3), None)
        sig.append(match)
    return sig

app = FastAPI(title="Cleo Rover Mk1 Body Service", version="0.1.0")


_heartbeat_task: asyncio.Task | None = None


def _start_life_heartbeat() -> None:
    """Start the internal life heartbeat (hardware only) so Pip's emotional state
    evolves on its own. Stays off in sim/tests to avoid background event noise."""
    global _heartbeat_task
    interval = CONFIG.life_loop.heartbeat_seconds
    if body.mode != "hardware" or not CONFIG.life_loop.enabled or interval <= 0:
        return
    if _heartbeat_task and not _heartbeat_task.done():
        return

    async def loop() -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                life_heartbeat_step()
            except Exception:
                pass

    _heartbeat_task = asyncio.create_task(loop())


def _start_rgb_expression() -> None:
    """Animate the RGB strip to reflect Pip's mood/energy/state (hardware only).
    With no display, this is Pip's primary 'aliveness' channel."""
    global _rgb_task_handle
    hz = CONFIG.life_loop.rgb_expression_hz
    if body.mode != "hardware" or not CONFIG.life_loop.rgb_expression_enabled or hz <= 0:
        return
    if _rgb_task_handle and not _rgb_task_handle.done():
        return

    async def loop() -> None:
        period = 1.0 / hz
        phase = 0.0
        while True:
            await asyncio.sleep(period)
            try:
                frame = compute_affect_frame(phase=phase)
                body.set_rgb(RGBCommand(red=frame.color[0], green=frame.color[1], blue=frame.color[2], brightness=frame.brightness))
            except Exception:
                pass
            # ~5s breathe period: advance phase so a full cycle ~= 5 seconds.
            phase = (phase + period / 5.0) % 1.0

    _rgb_task_handle = asyncio.create_task(loop())


@app.on_event("startup")
async def start_body_watchdog() -> None:
    body.start_safety_watchdog()
    _start_life_heartbeat()
    _start_arbiter_loop()
    _start_rgb_expression()


@app.on_event("shutdown")
async def stop_body_watchdog() -> None:
    await body.stop_safety_watchdog()
    # Cancel ALL background loops (not just heartbeat/arbiter) so none outlive the
    # instance and double-drive motors/turret/RGB across a reload (audit I-9).
    if _cruise_stop_event is not None:
        _cruise_stop_event.set()
    for task in (_heartbeat_task, _arbiter_task, _rgb_task_handle, _perception_task_handle, _cruise_task_handle):
        if task is not None and not task.done():
            task.cancel()
    # Flush volatile state so a power loss between heartbeats doesn't regress mood/
    # cooldowns/goals/place (audit I-10).
    try:
        store.save_state(autonomy.state)
        if hasattr(autonomy, "last_behavior_at"):
            store.save_cooldowns(autonomy.last_behavior_at)
        save_pip_runtime()
        save_topo()
    except Exception:
        pass


def gpio_pin_claims() -> dict[int, list[str]]:
    claims: dict[int, list[str]] = {}

    def claim(pin: int | None, label: str) -> None:
        if pin is not None:
            claims.setdefault(pin, []).append(label)

    if CONFIG.display.spi_bus == 1:
        claim(20, "display.din_mosi")
        claim(21, "display.clk_sclk")
        claim(CONFIG.display.cs_pin if CONFIG.display.cs_pin is not None else {0: 18, 1: 17, 2: 16}.get(CONFIG.display.spi_device), "display.cs")
    else:
        claim(10, "display.din_mosi")
        claim(11, "display.clk_sclk")
        claim(CONFIG.display.cs_pin if CONFIG.display.cs_pin is not None else {0: 8, 1: 7}.get(CONFIG.display.spi_device), "display.cs")
    claim(CONFIG.display.dc_pin, "display.dc")
    claim(CONFIG.display.reset_pin, "display.rst")
    claim(CONFIG.display.backlight_pin, "display.bl")
    claim(CONFIG.sensors.ultrasonic_trigger_pin, "ultrasonic.trigger")
    claim(CONFIG.sensors.ultrasonic_echo_pin, "ultrasonic.echo")
    claim(CONFIG.sensors.line_left_pin, "line.left")
    claim(CONFIG.sensors.line_center_pin, "line.center")
    claim(CONFIG.sensors.line_right_pin, "line.right")
    claim(CONFIG.sensors.bumper_left_pin, "bumper.left")
    claim(CONFIG.sensors.bumper_right_pin, "bumper.right")
    return claims


def gpio_pin_conflicts() -> dict[int, list[str]]:
    return {pin: labels for pin, labels in gpio_pin_claims().items() if len(labels) > 1}


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


def extend_active_movement_grant(seconds: float) -> None:
    """Keep an internal task grant alive while a supervised task is still running.

    Speech/camera scans can take longer than the original movement window. This
    does not move the rover by itself; it only prevents safe, short chunks inside
    the current task from failing due to narration latency.
    """
    global movement_grant
    if movement_grant is None or not movement_grant.get("active"):
        return
    movement_grant["expires_at"] = max(float(movement_grant.get("expires_at", 0)), time.time() + float(seconds))


def sensor_safety_event(sensors_now: dict, *, source: str) -> RoverEvent | None:
    distance = normalize_distance_cm(sensors_now.get("front_distance_cm"))
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


def pip_feelings() -> dict:
    """Single unified view of Pip's emotional state (the AutonomyEngine is the
    source of truth; boredom is the legacy life-loop scalar kept for continuity)."""
    a = autonomy.state
    return {
        "mood": a.mood,
        "energy": round(a.energy, 3),
        "curiosity": round(a.curiosity, 3),
        "attention": round(a.attention, 3),
        "confidence": round(a.confidence, 3),
        "boredom": round(float(pip_state.get("boredom", 0.0) or 0.0), 3),
    }


def life_heartbeat_step() -> dict:
    """One internal life tick: refresh energy from battery, decay attention/
    curiosity via an idle tick, and keep Pip's displayed mood in sync with its
    feelings. Lets the emotional state evolve without any external poke (D19)."""
    sensors_now = body.sensors()
    percent = sensors_now.get("battery_percent")
    # Feed the sag-aware estimator (idle samples are trusted; in-motion advisory).
    update_battery(sensors_now)
    if percent is not None:
        remember_event(RoverEvent(kind=RoverEventKind.battery, source="heartbeat", value=float(percent), payload={"percent": percent}))
    idle = remember_event(RoverEvent(kind=RoverEventKind.idle_tick, source="heartbeat", timestamp=time.time()))
    if pip_state.get("mode") != "sleep" and pip_state.get("mood") != "low_power":
        pip_state["mood"] = autonomy.state.mood
    # Opportunistic memory consolidation while idle: distill episodic sightings
    # into durable facts every N heartbeats (cheap, local SQLite + arithmetic).
    global _heartbeat_count
    _heartbeat_count += 1
    consolidated = None
    if CONFIG.nav.consolidation_enabled and _heartbeat_count % max(1, CONFIG.nav.consolidation_interval_heartbeats) == 0:
        try:
            consolidated = run_consolidation()
        except Exception:
            consolidated = None
    save_pip_runtime()
    return {"ok": True, "feelings": pip_feelings(), "idle_event_at": idle.timestamp, "consolidated": consolidated}


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
    distance = normalize_distance_cm(sensors_now.get("front_distance_cm"))
    if command.linear > 0 and distance is not None and float(distance) < CONFIG.safety.front_stop_distance_cm:
        return False, f"drive rejected: obstacle at {distance}cm is closer than stop threshold {CONFIG.safety.front_stop_distance_cm}cm", command
    # Thermal back-off for a fanless Pi running autonomy for hours (None off-Pi).
    temp = cpu_temp_c()
    if temp is not None:
        if temp >= CONFIG.safety.thermal_hard_c and command.linear > 0:
            return False, f"drive rejected: CPU {temp}C >= hard thermal limit {CONFIG.safety.thermal_hard_c}C; cooling down", command
        if temp >= CONFIG.safety.thermal_warn_c:
            command = command.model_copy(update={"linear": command.linear * 0.5, "turn": command.turn * 0.5})
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
    return {"ok": True, "mode": body.mode, "name": CONFIG.name, "profile": CONFIG.profile, "version": app.version, "soul_version": PIP_SOUL_VERSION}


@app.get("/health/composite")
def health_composite() -> dict:
    """The single 'is Pip OK / what is it doing / can it do X right now?' view.

    Merges battery SOC+health, mood/energy, movement permission (+grant owner),
    active goal, the arbiter's current choice + why-it-can't-move, every subsystem
    readiness bit, nav/place state, the RGB affect, and the build/soul version --
    so an operator answers 'safe to send it now?' in one call (audit P-1)."""
    sensors_now = body.sensors()
    reading = update_battery(sensors_now)
    feelings = pip_feelings()
    battery = battery_safety_summary(sensors_now)
    move_ok, move_reason = pip_can_autonomously_move(allow_movement=True, battery=battery)
    grant = active_movement_grant()
    goal = active_goal()
    degradation = current_degradation(sensors_now, reading)
    # The arbiter's would-be choice (read-only) + the RGB affect.
    try:
        decision = arbiter.arbitrate(arbiter_context())
    except Exception as exc:  # never let status crash
        decision = {"behavior": "unknown", "reason": f"context error: {exc!r}"}
    try:
        frame = compute_affect_frame(phase=0.0)
        rgb = {"color": list(frame.color), "pattern": frame.pattern, "label": frame.label}
    except Exception:
        rgb = None
    blockers: list[str] = []
    if not body.motors_armed:
        blockers.append("motors not armed")
    if reading.critical:
        blockers.append("battery critical")
    if not move_ok:
        blockers.append(move_reason)
    return {
        "ok": True,
        "ready_to_move": bool(move_ok and body.motors_armed and not reading.critical),
        "blockers": blockers,
        "identity": {"name": CONFIG.name, "profile": CONFIG.profile, "mode": pip_state.get("mode"), "version": app.version, "soul_version": PIP_SOUL_VERSION},
        "battery": {
            "soc_percent": reading.soc_percent,
            "voltage": reading.voltage,
            "charging": reading.charging,
            "warn": reading.warn,
            "critical": reading.critical,
            "recommendation": "charge_before_movement" if reading.critical else battery.get("recommendation"),
        },
        "feelings": feelings,
        "movement": {"permitted": move_ok, "reason": move_reason, "grant": grant, "owner": (grant or {}).get("owner")},
        "goal": goal.model_dump() if goal else None,
        "degradation": degradation.as_dict(),
        "arbiter": {"would_choose": decision.get("behavior"), "reason": decision.get("reason")},
        "nav": {
            "current_place": _last_topo_node,
            "topo": TOPO.summary(),
            "continuous_motion_enabled": CONFIG.nav.continuous_motion_enabled,
            "arbiter_enabled": CONFIG.life_loop.arbiter_enabled,
        },
        "rgb_affect": rgb,
        "subsystems": {
            **body.readiness(),
            "ultrasonic_ready": sensors_now.get("ultrasonic_ready"),
            "line_sensors_ready": sensors_now.get("line_sensors_ready"),
            "adc_ready": sensors_now.get("adc_ready"),
            "camera_ready": (sensors_now.get("camera") or {}).get("ready"),
            "mind_configured": hermes_configured() or mind.mind_configured(),
        },
    }


@app.get("/health/degradation")
def health_degradation() -> dict:
    """What Pip can safely do right now (full / scan-only / turret-only / stopped)
    and why -- one capability authority shared by health, the UI, and behaviors."""
    return {"ok": True, **current_degradation().as_dict()}


@app.get("/life/diary")
def life_diary() -> dict:
    """A short, truthful first-person diary of Pip's inner life (mood, what it did,
    what it has learned). Grounded entirely in real state -- nothing invented."""
    from . import diary as diary_mod

    reading = _last_battery if _last_battery is not None else update_battery(body.sensors())
    entries = [e.model_dump() for e in store.recent_events(40)]
    diary = diary_mod.compose_diary(
        feelings=pip_feelings(),
        recent_events=entries,
        facts=store.list_facts(20),
        place_count=len(TOPO.nodes),
        battery_percent=getattr(reading, "soc_percent", None),
        charging=bool(getattr(reading, "charging", False)),
    )
    return {"ok": True, **diary}


@app.get("/tasks/history")
def tasks_history(limit: int = 25) -> dict:
    """Recent task/behavior history (what Pip has been doing), newest first."""
    return {"ok": True, "history": list(reversed(_task_history))[: max(1, min(limit, 50))]}


@app.post("/pip/live")
async def pip_live(on: bool = True) -> dict:
    """Bring the whole being to life (or pause it): the heartbeat, the behavior
    arbiter, and the RGB expression loop. On hardware these auto-start per their
    flags; this is the single explicit on/off + a composite snapshot of the result.
    In sim the loops are inert (no hardware), so this reports what WOULD run."""
    if on:
        _start_life_heartbeat()
        _start_arbiter_loop()
        _start_rgb_expression()
    else:
        if _cruise_stop_event is not None:
            _cruise_stop_event.set()
        for task in (_heartbeat_task, _arbiter_task, _rgb_task_handle):
            if task is not None and not task.done():
                task.cancel()
        await body.stop()
    alive = {
        "heartbeat": bool(_heartbeat_task and not _heartbeat_task.done()),
        "arbiter": bool(_arbiter_task and not _arbiter_task.done()),
        "rgb": bool(_rgb_task_handle and not _rgb_task_handle.done()),
    }
    return {
        "ok": True,
        "live": on,
        "loops": alive,
        "note": "loops auto-start only on hardware with their flags; in sim, drive ticks via /pip/arbiter/tick and /pip/life-tick.",
        "arbiter_enabled": CONFIG.life_loop.arbiter_enabled,
        "mode": body.mode,
    }


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
    conflicts = gpio_pin_conflicts()
    add("gpio_pin_conflicts", not conflicts, f"conflicts={conflicts}" if conflicts else "no duplicate GPIO claims")
    add("display_pin_map", CONFIG.display.spi_bus == 1 and CONFIG.display.spi_device == 0 and CONFIG.display.cs_pin == 6 and CONFIG.display.dc_pin == 25 and CONFIG.display.reset_pin == 5, f"ST7789 SPI{CONFIG.display.spi_bus}.{CONFIG.display.spi_device}: DIN=GPIO20, CLK=GPIO21, CS=GPIO{CONFIG.display.cs_pin}, DC=GPIO{CONFIG.display.dc_pin}, RST=GPIO{CONFIG.display.reset_pin}, BL={'3.3V/manual' if CONFIG.display.backlight_pin is None else 'GPIO' + str(CONFIG.display.backlight_pin)}")

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


@app.post("/hearing/listen")
async def hearing_listen(text: str | None = None, seconds: float = 4.0) -> dict:
    """Hear a spoken command. With ?text= (external STT / testing) it routes that
    transcript; otherwise it captures from the USB mic and transcribes offline on
    hardware, then routes through the same /pip/command intent router. Talking
    never enables movement (allow_movement stays False; motion stays gated)."""
    transcript = text
    listen_result = None
    if transcript is None:
        if body.mode != "hardware":
            return {"ok": True, "available": False, "reason": "mic capture only on hardware; pass ?text= to route an external transcript", "backends": voice_daemon.voice_backends()}
        # Mic capture + offline STT are blocking; run them off the event loop.
        listen_result = await asyncio.to_thread(
            voice_daemon.capture_and_transcribe,
            seconds=seconds,
            mic_device=CONFIG.voice.mic_device,
            rate=CONFIG.voice.sample_rate,
            backend=CONFIG.voice.stt_backend,
            model_path=CONFIG.voice.stt_model_path,
        )
        if not listen_result.get("ok"):
            return {"ok": False, "available": listen_result.get("available", False), "result": listen_result, "backends": voice_daemon.voice_backends()}
        transcript = listen_result.get("text")
    if not transcript:
        return {"ok": True, "available": True, "transcript": None, "note": "no speech recognized"}
    remember_event(RoverEvent(kind=RoverEventKind.speech, source="voice", label="heard", payload={"text": transcript}))
    routed = await pip_command(PipCommand(text=transcript, source="voice"))
    return {"ok": True, "available": True, "transcript": transcript, "listen": listen_result, "routed": routed}


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


VISION_ANALYSIS_FIELDS = {"summary", "labels", "objects", "confidence", "zone", "snapshot_path", "source", "clear_path", "hazards"}


def ingest_local_vision(zone: str, image_path: str | None) -> dict:
    """Run on-Pi vision on a captured frame and emit a real vision_analysis event.

    This is what finally gives pip-brain fresh latest_vision instead of null: the
    analysis flows through the same path as external vision (events + spatial +
    semantic). Degrades to a low-confidence placeholder when no detector/model is
    available, so the pipeline is never silently empty.
    """
    analysis = vision_service.analyze_frame(
        image_path,
        zone=zone,
        conf_threshold=CONFIG.vision.conf_threshold,
        model_path=CONFIG.vision.model_path,
        labelmap_path=CONFIG.vision.labelmap_path,
    )
    payload = {key: value for key, value in analysis.items() if key in VISION_ANALYSIS_FIELDS}
    result = vision_analysis(VisionAnalysisCommand.model_validate(payload))
    return {"analysis": analysis, "ingested_ok": bool(result.get("ok"))}


@app.get("/autonomy/state")
def autonomy_state() -> dict:
    return {
        "ok": True,
        "state": autonomy.state.model_dump(),
        "cooldowns": autonomy.last_behavior_at,
        "hub": body_status_dict().get("hub"),
        "recent_events": [event.model_dump() for event in store.recent_events(10)],
    }


@app.post("/autonomy/heartbeat")
def autonomy_heartbeat() -> dict:
    """Run one internal life tick (refresh energy from battery, decay, sync mood).
    The background heartbeat calls this on hardware; exposed for manual/test use."""
    return life_heartbeat_step()


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
        "memory_bias": explore.memory_bias(items, now=time.time()),
        "recent_events": [event.model_dump() for event in store.recent_events(8)],
    }


@app.post("/map/scan")
async def map_scan(command: MapScanCommand) -> dict:
    observations = []
    capture = None
    try:
        for angle in command.angles:
            clamped = max(CONFIG.turret.pan_min_deg, min(CONFIG.turret.pan_max_deg, float(angle)))
            await body.set_turret(TurretCommand(pan_deg=clamped))
            await asyncio.sleep(command.settle_ms / 1000)
            sensors_now = body.sensors()
            # Deliberate per-angle median read (noise/specular-dropout resistant) so
            # the scan-center clearance the navigator trusts is not a single bad ping.
            median_cm = body.front_distance_median()
            distance_cm = normalize_distance_cm(median_cm if median_cm is not None else sensors_now.get("front_distance_cm"))
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
        if command.snapshot_center:
            capture = capture_camera_snapshot(CONFIG.camera.capture_dir, width=CONFIG.camera.width, height=CONFIG.camera.height) if body.mode == "hardware" else None
        return {"ok": True, "zone": command.zone, "observations": observations, "capture": capture}
    finally:
        await body.set_turret(TurretCommand(pan_deg=0))


@app.post("/map/visual-scan")
async def visual_map_scan(command: VisualMapScanCommand) -> dict:
    observations = []
    try:
        for angle in command.angles:
            clamped = max(CONFIG.turret.pan_min_deg, min(CONFIG.turret.pan_max_deg, float(angle)))
            await body.set_turret(TurretCommand(pan_deg=clamped))
            await asyncio.sleep(command.settle_ms / 1000)
            sensors_now = body.sensors()
            median_cm = body.front_distance_median()
            distance_cm = normalize_distance_cm(median_cm if median_cm is not None else sensors_now.get("front_distance_cm"))
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
        return {"ok": True, "zone": command.zone, "observations": observations, "needs_external_vision": True}
    finally:
        await body.set_turret(TurretCommand(pan_deg=0))


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
    # A single move-step is one short, safety-capped pulse. Larger travel must be
    # built from several chunks (adaptive_forward_stride), because the pulse is
    # capped by max_drive_duration_ms. We keep the proven duty/timing, but now
    # report an HONEST estimated distance for the *actually applied* pulse so
    # callers stop believing a capped pulse moved the full requested distance.
    linear = 0.38 if command.forward_cm >= 0 else -0.32
    duration = int(min(850, max(260, abs(command.forward_cm) * 95)))
    result = await guarded_drive(DriveCommand(linear=linear, turn=0, duration_ms=duration), require_permission=command.require_permission)
    result["step"] = command.model_dump()
    result["requested_cm"] = command.forward_cm
    if result.get("ok"):
        applied = result.get("command") or {}
        applied_duration = float(applied.get("duration_ms", min(duration, CONFIG.safety.max_drive_duration_ms)))
        applied_linear = float(applied.get("linear", linear))
        signed = MOTION.distance_cm_for(applied_linear, applied_duration)
        result["estimated_cm"] = round(signed if command.forward_cm >= 0 else -signed, 1)
    else:
        result["estimated_cm"] = 0.0
    result["distance_note"] = "open-loop estimate (no encoders); a single pulse is capped by max_drive_duration_ms"
    return result


def adaptive_forward_step_cm(
    *,
    center_distance_cm: float | None,
    front_distance_cm: float | None,
    blocked_cm: float,
    min_step_cm: float,
    max_step_cm: float,
    fallback_step_cm: float,
) -> float:
    """Choose a route-level stride from clearance, while actual movement stays chunked.

    This is Pip's general navigation rule: use larger strides in open hallway, but
    shrink to tiny nudges near doorways/obstacles. It does not trust odometry.
    """
    readings = [v for v in (center_distance_cm, front_distance_cm) if v is not None]
    if not readings:
        return max(min_step_cm, min(fallback_step_cm, max_step_cm))
    clearance = max(0.0, min(readings) - blocked_cm)
    # Use less than half of measured spare clearance. At 150cm with blocked=45cm,
    # this asks for about 47cm, then max_step_cm caps the stride for supervision.
    planned = clearance * 0.45
    return round(max(min_step_cm, min(max_step_cm, planned)), 1)


async def adaptive_forward_stride(total_cm: float, *, chunk_cm: float, require_permission: bool = True, brake_cm: float = 30.0) -> dict:
    """Move a planned stride as several short open-loop chunks with sensor checks.

    We still stop and re-read range between chunks, so a 24-50cm high-level stride
    is never one blind motor command.
    """
    remaining = max(0.0, float(total_cm))
    chunk_limit = max(1.0, min(16.0, float(chunk_cm)))
    chunks: list[dict[str, Any]] = []
    est_travelled = 0.0
    stall_streak = 0

    def stride_result(ok: bool, reason: str | None = None, **extra) -> dict:
        out = {
            "ok": ok,
            "kind": "adaptive-stride",
            "planned_cm": round(total_cm, 1),
            "est_travelled_cm": round(est_travelled, 1),
            # Back-compat alias; both are open-loop estimates, never measured truth.
            "travelled_cm": round(est_travelled, 1),
            "chunk_cm": chunk_limit,
            "chunks": chunks,
            "distance_note": "open-loop estimate (no encoders); ultrasonic-delta blended with motion model",
        }
        if reason is not None:
            out["reason"] = reason
        out.update(extra)
        return out

    while remaining > 0.1:
        sensors_now = body.sensors()
        front = normalize_distance_cm(sensors_now.get("front_distance_cm"))
        front_before = float(front) if front is not None else None
        if front_before is None:
            await body.stop()
            return stride_result(False, "front range invalid before chunk", front_distance_cm=front_before)
        if front_before < brake_cm:
            await body.stop()
            return stride_result(False, "front blocked before chunk", front_distance_cm=front_before)
        extend_active_movement_grant(12)
        this_chunk = min(chunk_limit, remaining)
        move = await move_step(MoveStepCommand(forward_cm=this_chunk, require_permission=require_permission))
        command_payload = move.get("command") if isinstance(move, dict) else None
        duration_ms = float(command_payload.get("duration_ms", 0)) if isinstance(command_payload, dict) else 0.0
        applied_linear = float(command_payload.get("linear", 0.0)) if isinstance(command_payload, dict) else 0.0
        # Let the asynchronous drive monitor finish the pulse, then stop and measure.
        await asyncio.sleep(max(0.15, duration_ms / 1000.0 + 0.05))
        await body.stop()
        if not move.get("ok"):
            return stride_result(False, "chunk move failed")
        front_after = normalize_distance_cm(body.sensors().get("front_distance_cm"))
        est = estimate_chunk_distance_cm(
            model=MOTION,
            duty=applied_linear,
            duration_ms=duration_ms,
            front_before_cm=front_before,
            front_after_cm=front_after,
        )
        chunks.append({"requested_cm": round(this_chunk, 1), "front_before_cm": front_before, "front_after_cm": front_after, "estimate": est})
        est_travelled += est["estimated_cm"]
        remaining -= this_chunk
        # Stall = commanded forward but a near surface ahead did not get closer.
        if est["stalled"]:
            stall_streak += 1
            if stall_streak >= 2:
                await body.stop()
                return stride_result(False, "stalled: commanded forward but no range progress", stalled=True)
        else:
            stall_streak = 0
    return stride_result(True)


@app.post("/movement/rotate-step")
async def rotate_step(command: RotateStepCommand) -> dict:
    # Tuned from real Pip floor tests: direct turn=0.65 for 300ms worked cleanly.
    # Larger spins should be built from multiple rotate+scan cycles.
    turn = 0.65 if command.deg >= 0 else -0.65
    duration = int(min(450, max(300, abs(command.deg) * 20)))
    result = await guarded_drive(DriveCommand(linear=0, turn=turn, duration_ms=duration), require_permission=command.require_permission)
    result["step"] = command.model_dump()
    return result


@app.post("/movement/grant")
def grant_movement(command: MovementPermissionCommand) -> dict:
    global movement_grant
    expires_at = time.time() + command.duration_seconds
    movement_grant = command.model_dump() | {"expires_at": expires_at, "active": command.allow_movement, "owner": command.task or "operator"}
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


def scan_observation_summary(scan: dict) -> dict:
    samples = []
    for obs in scan.get("observations") or []:
        payload = ((obs.get("event") or {}).get("payload") or {}) if isinstance(obs, dict) else {}
        bearing = payload.get("bearing_deg")
        distance = payload.get("distance_cm")
        if bearing is None or distance is None:
            continue
        try:
            samples.append({"bearing_deg": float(bearing), "distance_cm": float(distance)})
        except (TypeError, ValueError):
            continue
    best = max(samples, key=lambda item: item["distance_cm"]) if samples else None
    center = min((item for item in samples if abs(item["bearing_deg"]) < 8.0), key=lambda item: abs(item["bearing_deg"]), default=None)
    return {"samples": samples, "best": best, "center": center}


async def reactive_escape_scan(zone: str, angles: list[float]) -> tuple[dict, dict]:
    scan = await map_scan(MapScanCommand(zone=zone, angles=angles, settle_ms=160, snapshot_center=False))
    return scan, scan_observation_summary(scan)


def reactive_turn_degrees(best: dict | None, *, blocked_streak: int = 0) -> float:
    """Pick a small open-loop turn toward the best scan bearing.

    Freenove's ordinary-wheel demo uses direct tank turns. Pip uses the same
    channel logic, but in smaller increments so she can scan/rotate/scan instead
    of giving up when the first escape angle is poor.
    """
    if not best:
        return 12.0 if blocked_streak % 2 == 0 else -12.0
    bearing = float(best.get("bearing_deg", 0) or 0)
    if abs(bearing) < 8:
        return 0.0
    magnitude = min(24.0, max(8.0, abs(bearing) * 0.42))
    if blocked_streak >= 3:
        magnitude = min(32.0, magnitude + 6.0)
    return magnitude if bearing >= 0 else -magnitude


async def reactive_turn_toward(best: dict | None, *, blocked_streak: int = 0) -> dict:
    deg = reactive_turn_degrees(best, blocked_streak=blocked_streak)
    if abs(deg) < 1.0:
        return {"ok": True, "skipped": True, "reason": "best bearing already centered", "deg": deg}
    return await rotate_step(RotateStepCommand(deg=deg, require_permission=True))


async def hallway_scout_scan_turn(zone: str, angles: list[float], *, reason: str) -> dict:
    scan, summary = await reactive_escape_scan(zone, angles)
    best = summary.get("best")
    center = summary.get("center")
    if not best:
        turn = await rotate_step(RotateStepCommand(deg=15, require_permission=True))
        return {"kind": "scan-turn", "reason": reason, "summary": summary, "turn": turn, "fallback": "no scan best; small right search"}

    best_bearing = float(best.get("bearing_deg") or 0.0)
    best_distance = float(best.get("distance_cm") or 0.0)
    center_distance = float(center.get("distance_cm") or 0.0) if center else None
    if abs(best_bearing) < 8.0:
        # If the clearest return is centered but still blocked, search right first to avoid sitting at a doorframe.
        deg = 15.0
    else:
        # Convert scan bearing to a bounded open-loop rotate. Keep it small and re-scan often.
        deg = max(-25.0, min(25.0, best_bearing * 0.45))
        if abs(deg) < 12.0:
            deg = 12.0 if deg >= 0 else -12.0
    turn = await rotate_step(RotateStepCommand(deg=deg, require_permission=True))
    return {
        "kind": "scan-turn",
        "reason": reason,
        "summary": summary,
        "best_bearing_deg": best_bearing,
        "best_distance_cm": best_distance,
        "center_distance_cm": center_distance,
        "turn_deg": deg,
        "turn": turn,
    }


def battery_safety_summary(sensors: dict) -> dict:
    percent = sensors.get("battery_percent")
    voltage = sensors.get("battery_voltage")
    recommendation = "ok_for_gentle_testing"
    if percent is not None:
        if float(percent) < 30:
            recommendation = "charge_before_movement"
        elif float(percent) < 50:
            recommendation = "gentle_tests_only"
    if voltage is not None and float(voltage) < 7.0:
        recommendation = "charge_before_movement"
    return {"battery_percent": percent, "battery_voltage": voltage, "recommendation": recommendation}


def compact_action(item: dict) -> dict:
    out = {"kind": item.get("kind")}
    for key in ("cycle", "phase", "reason", "front_distance_cm", "raw_front_cm", "scan_center_cm", "decision_front_cm", "planned_step_cm", "blocked_streak"):
        if key in item:
            out[key] = item[key]
    if item.get("summary"):
        summary = item["summary"]
        out["scan"] = {"best": summary.get("best"), "center": summary.get("center"), "samples": len(summary.get("samples") or [])}
    result = item.get("result")
    if isinstance(result, dict):
        if result.get("command"):
            out["command"] = result["command"]
        elif result.get("path"):
            out["path"] = result["path"]
        elif result.get("reason"):
            out["result_reason"] = result["reason"]
    return out


def plan_summary(plan: list[dict]) -> dict:
    counts: dict[str, int] = {}
    front_values: list[float] = []
    last_action: dict | None = None
    best_scan: dict | None = None
    for item in plan:
        kind = str(item.get("kind"))
        counts[kind] = counts.get(kind, 0) + 1
        if item.get("front_distance_cm") is not None:
            front_values.append(float(item["front_distance_cm"]))
        if item.get("kind") in {"crawl", "turn", "reverse", "stop", "hold", "corner-search", "corner-trap", "reflex-stop"}:
            last_action = compact_action(item)
        summary = item.get("summary") or {}
        best = summary.get("best")
        if best and (best_scan is None or float(best.get("distance_cm", 0)) > float(best_scan.get("distance_cm", 0))):
            best_scan = best
    return {
        "counts": counts,
        "min_front_distance_cm": round(min(front_values), 1) if front_values else None,
        "max_front_distance_cm": round(max(front_values), 1) if front_values else None,
        "best_scan": best_scan,
        "last_action": last_action,
        "corner_trap": counts.get("corner-trap", 0) > 0,
        "corner_search": counts.get("corner-search", 0) > 0,
        "reflex_stop": counts.get("reflex-stop", 0) > 0,
    }


def compact_plan(plan: list[dict]) -> list[dict]:
    return [compact_action(item) for item in plan]


def pip_recent_interrupt(kind: str, *, within_seconds: float) -> dict | None:
    cutoff = time.time() - within_seconds
    for item in reversed(pip_interrupts):
        if item.get("kind") == kind and float(item.get("timestamp") or 0) >= cutoff:
            return item
    return None


def pip_enqueue_interrupt(priority: str, message: str, *, kind: str = "note", payload: dict | None = None) -> dict:
    item = {
        "id": f"pip-{int(time.time() * 1000)}",
        "priority": priority,
        "kind": kind,
        "message": message,
        "payload": payload or {},
        "timestamp": time.time(),
        "delivered": False,
    }
    pip_interrupts.append(item)
    del pip_interrupts[:-50]
    remember_event(RoverEvent(kind=RoverEventKind.manual_control, source="pip", label=f"interrupt:{kind}", payload=item))
    save_pip_runtime()
    return item


def pip_public_state() -> dict:
    sensors_now = body.sensors()
    battery = battery_safety_summary(sensors_now)
    pending = [item for item in pip_interrupts if not item.get("delivered")]
    return {
        "ok": True,
        "identity": pip_identity,
        "soul_version": PIP_SOUL_VERSION,
        "state": pip_state,
        "feelings": pip_feelings(),
        "battery": battery,
        "movement": movement_status(),
        "sensors": {
            "front_distance_cm": sensors_now.get("front_distance_cm"),
            "last_reflex_stop": (sensors_now.get("motors") or {}).get("last_reflex_stop"),
            "errors": sensors_now.get("errors"),
        },
        "pending_interrupts": len(pending),
        "capabilities": [
            "office_home_base",
            "modes:sleep|quiet|social|assistant",
            "greet",
            "rescue_request",
            "bored_patrol",
            "reactive_explore",
            "vision_awareness",
            "first_adventure_readiness",
            "soul_identity_protocol",
            "central_brain_digest",
            "telegram_or_voice_command_bridge",
        ],
    }


def pip_brain_snapshot(*, compact: bool = True) -> dict:
    sensors_now = body.sensors()
    # Kind-filtered fetch so the latest vision survives a flood of scan events.
    vision_events = store.recent_events(1, kind=RoverEventKind.vision_analysis.value)
    return build_pip_brain(
        pip_state=pip_state,
        identity=pip_identity,
        battery=battery_safety_summary(sensors_now),
        sensors=sensors_now,
        status=status().model_dump(),
        movement=movement_status(),
        autonomy=autonomy.state,
        recent_events=store.recent_events(40),
        spatial_items=store.list_spatial(100),
        compact=compact,
        latest_vision_event=vision_events[0] if vision_events else None,
        hazard_max_age_s=CONFIG.vision.hazard_max_age_s,
    )


def pip_can_autonomously_move(*, allow_movement: bool, battery: dict) -> tuple[bool, str]:
    if not allow_movement:
        return False, "movement not allowed by request"
    if pip_state["mode"] == "sleep":
        return False, "Pip is sleeping"
    if pip_state["mode"] == "quiet":
        return False, "Pip is quiet; observation only"
    if pip_state.get("current_zone") not in pip_identity["approved_zones"]:
        return False, "current zone is not approved"
    if battery["recommendation"] == "charge_before_movement":
        return False, "battery says charge before movement"
    return True, "movement allowed"


async def pip_set_expression(mode: ExpressionMode, text: str, brightness: float = 0.55) -> None:
    await body.set_expression(ExpressionCommand(mode=mode, text=text, brightness=brightness))


async def pip_rescue(message: str, *, priority: str = "medium", payload: dict | None = None) -> dict:
    await body.stop()
    pip_state["last_rescue_at"] = time.time()
    pip_state["mood"] = "confused"
    await pip_set_expression(ExpressionMode.confused, "help?", 0.55)
    interrupt = pip_enqueue_interrupt(priority, message, kind="rescue", payload=payload)
    return {"ok": True, "rescued": False, "interrupt": interrupt, "state": pip_public_state()}


def pip_should_patrol(*, force: bool = False) -> tuple[bool, str]:
    if force:
        return True, "forced"
    now = time.time()
    last = pip_state.get("last_patrol_at")
    if last and now - float(last) < 600:
        return False, "patrol cooldown active"
    # Patrol when bored OR when the unified emotion engine is genuinely curious,
    # so curiosity (not just a legacy boredom scalar) actually drives exploration.
    if float(pip_state.get("boredom", 0)) < 0.6 and autonomy.state.curiosity < 0.68:
        return False, "not bored or curious enough"
    return True, "bored or curious"


@app.get("/pip/state")
def pip_state_endpoint() -> dict:
    return pip_public_state()


@app.get("/pip/soul")
def pip_soul_endpoint() -> dict:
    return {"ok": True, **pip_soul_public()}


@app.get("/pip/brain")
def pip_brain_endpoint(compact: bool = True) -> dict:
    return pip_brain_snapshot(compact=compact)


@app.post("/pip/mode")
async def pip_mode(command: PipModeCommand) -> dict:
    pip_state["mode"] = command.mode
    pip_state["awake"] = command.mode != "sleep"
    pip_state["mood"] = "sleeping" if command.mode == "sleep" else "curious"
    if command.mode == "sleep":
        await body.stop()
        await pip_set_expression(ExpressionMode.sleeping, "sleep", 0.25)
    elif command.mode == "quiet":
        await pip_set_expression(ExpressionMode.watching, "quiet", 0.35)
    elif command.mode == "assistant":
        await pip_set_expression(ExpressionMode.listening, "listening", 0.55)
    else:
        await pip_set_expression(ExpressionMode.curious, "pip", 0.55)
    event = remember_event(RoverEvent(kind=RoverEventKind.manual_control, source="pip", label=f"mode:{command.mode}", payload={"mode": command.mode, "reason": command.reason}))
    save_pip_runtime()
    return {"ok": True, "mode": command.mode, "event": event.model_dump(), "state": pip_public_state()}


@app.post("/pip/wake")
async def pip_wake() -> dict:
    return await pip_mode(PipModeCommand(mode="social", reason="wake requested"))


@app.post("/pip/sleep")
async def pip_sleep() -> dict:
    return await pip_mode(PipModeCommand(mode="sleep", reason="sleep requested"))


@app.post("/pip/greet")
async def pip_greet(source: str = "operator") -> dict:
    pip_state["last_greet_at"] = time.time()
    pip_state["boredom"] = max(0.0, float(pip_state.get("boredom", 0)) - 0.2)
    pip_state["mood"] = "happy"
    await pip_set_expression(ExpressionMode.happy, "hi noot", 0.6)
    rgb_result = rgb(RGBCommand(red=90, green=180, blue=255, brightness=28))
    event = remember_event(RoverEvent(kind=RoverEventKind.manual_control, source="pip", label="greet", payload={"source": source, "line": "hi noot."}))
    save_pip_runtime()
    return {"ok": True, "line": "hi noot.", "rgb": rgb_result, "event": event.model_dump(), "state": pip_public_state()}


@app.post("/pip/rescue-needed")
async def pip_rescue_needed(reason: str = "I found a corner and need help.") -> dict:
    return await pip_rescue(f"um... {reason}", priority="high", payload={"reason": reason})


@app.get("/pip/interrupts")
def pip_interrupt_list(mark_delivered: bool = False) -> dict:
    pending = [item for item in pip_interrupts if not item.get("delivered")]
    if mark_delivered:
        for item in pending:
            item["delivered"] = True
        save_pip_runtime()
    return {"ok": True, "interrupts": pending, "count": len(pending)}


@app.post("/pip/life-tick")
async def pip_life_tick(command: PipLifeTickCommand) -> dict:
    pip_state["last_life_tick_at"] = time.time()
    sensors_now = body.sensors()
    battery = battery_safety_summary(sensors_now)
    # Feed real battery into the unified emotion engine so energy tracks reality.
    if sensors_now.get("battery_percent") is not None:
        remember_event(RoverEvent(kind=RoverEventKind.battery, source="life_tick", value=float(sensors_now["battery_percent"]), payload={"percent": sensors_now["battery_percent"]}))
    actions: list[dict] = []

    if pip_state["mode"] == "sleep" and not command.force:
        await pip_set_expression(ExpressionMode.sleeping, "sleep", 0.22)
        save_pip_runtime()
        return {"ok": True, "decision": "sleep", "reason": "Pip is sleeping", "battery": battery, "actions": actions, "state": pip_public_state()}

    if battery["recommendation"] == "charge_before_movement":
        pip_state["mood"] = "low_power"
        pip_state["boredom"] = 0.0
        recent = pip_recent_interrupt("rescue", within_seconds=900)
        if recent and (recent.get("payload") or {}).get("battery"):
            await pip_set_expression(ExpressionMode.sleeping, "charging", 0.20)
            save_pip_runtime()
            return {"ok": True, "decision": "resting_low_power", "battery": battery, "actions": [{"kind": "rest", "reason": "recent charge request already pending", "interrupt": recent}], "state": pip_public_state()}
        result = await pip_rescue("my battery feels too low for exploring. please charge me?", priority="medium", payload={"battery": battery})
        return {"ok": True, "decision": "low_power", "battery": battery, "actions": [result], "state": pip_public_state()}

    if pip_state.get("mood") == "low_power":
        pip_state["mood"] = "curious"
        for item in pip_interrupts:
            if item.get("kind") == "rescue" and (item.get("payload") or {}).get("battery"):
                item["delivered"] = True

    front = sensors_now.get("front_distance_cm")
    if front is not None and float(front) < 30:
        result = await pip_rescue(f"something is very close in front of me ({float(front):.1f}cm).", priority="high", payload={"front_distance_cm": front})
        return {"ok": True, "decision": "rescue", "battery": battery, "actions": [result], "state": pip_public_state()}

    movement_allowed, movement_reason = pip_can_autonomously_move(allow_movement=command.allow_movement, battery=battery)
    should_patrol, patrol_reason = pip_should_patrol(force=command.force)
    if should_patrol and pip_state["mode"] in {"social", "assistant"}:
        loop = await little_being_loop(
            LittleBeingLoopCommand(
                zone=str(pip_state.get("current_zone") or "office"),
                allow_movement=movement_allowed,
                duration_seconds=45,
                # Curiosity drives how far Pip ranges; confidence is reflected via mood.
                explore_cycles=4 + round(autonomy.state.curiosity * 4),
                observe_every_cycles=3,
                capture_vision=True,
                compact=True,
                mood=autonomy.state.mood,
                notes=f"pip life tick patrol: {command.reason}; {movement_reason}",
            )
        )
        pip_state["last_patrol_at"] = time.time()
        pip_state["boredom"] = 0.15
        actions.append({"kind": "patrol", "movement_allowed": movement_allowed, "reason": patrol_reason, "result": loop.get("summary")})
        reactive = (loop.get("summary") or {}).get("reactive") or {}
        if reactive.get("corner_trap") or reactive.get("reflex_stop"):
            actions.append(await pip_rescue("I got stuck during my patrol. can you rescue me?", priority="high", payload={"reactive": reactive}))
        save_pip_runtime()
        return {"ok": True, "decision": "patrol", "battery": battery, "actions": actions, "state": pip_public_state()}

    pip_state["boredom"] = min(1.0, float(pip_state.get("boredom", 0)) + (0.18 if pip_state["mode"] in {"social", "assistant"} else 0.06))
    await pip_set_expression(ExpressionMode.watching if pip_state["mode"] == "quiet" else ExpressionMode.curious, "watching", 0.45)
    observe = await vision_awareness_task(VisionAwarenessCommand(zone=str(pip_state.get("current_zone") or "office"), capture=False, scan=True, compact=True, notes="pip life tick quiet observation"))
    pip_state["last_observe_at"] = time.time()
    actions.append({"kind": "observe", "reason": patrol_reason, "scan_summary": observe.get("scan_summary")})
    save_pip_runtime()
    return {"ok": True, "decision": "observe", "battery": battery, "actions": actions, "state": pip_public_state()}


@app.get("/pip/hermes-bridge")
def pip_hermes_bridge_status() -> dict:
    return {
        "ok": True,
        "configured": hermes_configured(),
        "base": os.getenv("HERMES_API_BASE") or os.getenv("CLEO_ROVER_HERMES_API_BASE") or "",
        "model": os.getenv("HERMES_MODEL") or os.getenv("CLEO_ROVER_HERMES_MODEL") or "hermes-agent",
        "speak_response": os.getenv("HERMES_PIP_SPEAK_RESPONSE", "true"),
    }


def parse_destination_wish(text: str) -> str | None:
    patterns = [
        r"(?:i want to|i wanna|can we|lets|let's|please)\s+(?:go|get|head|explore)\s+(?:to\s+)?(?P<dest>[a-z0-9 _-]{3,60})",
        r"(?:go|get|head|explore)\s+(?:to\s+)?(?P<dest>the\s+[a-z0-9 _-]{3,60}|[a-z0-9 _-]{3,60})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            dest = re.sub(r"\s+", " ", match.group("dest")).strip(" .?!")
            if dest and dest not in {"status", "sleep", "wake", "quiet", "social", "assistant"}:
                return dest[:60]
    return None


def destination_requires_help(destination: str) -> bool:
    outdoor_words = {"yard", "backyard", "back yard", "outside", "outdoors", "garden", "garage", "driveway", "porch", "deck"}
    room_transition_words = {"hall", "hallway", "kitchen", "bedroom", "living room", "bathroom", "door"}
    return any(word in destination for word in outdoor_words | room_transition_words)


def pip_set_exploration_goal(destination: str, *, source: str) -> dict:
    requires_help = destination_requires_help(destination)
    goal = {
        "destination": destination,
        "source": source,
        "created_at": time.time(),
        "status": "waiting_for_human_help" if requires_help else "waiting_for_preflight",
        "requires_human_help": requires_help,
        "help_needed": "open/clear doorway and supervise transition" if requires_help else "preflight and movement permission",
        "safety_note": "Pip may want destinations, but cannot self-authorize movement or doors.",
    }
    pip_state["exploration_goal"] = goal
    pip_state["mood"] = "seeking"
    pip_state["boredom"] = min(1.0, max(0.65, float(pip_state.get("boredom", 0) or 0)))
    # Also create a FORMAL goal the arbiter will actually pursue (audit I-7): a
    # destination wish was previously a dead parallel store the arbiter never read.
    # Only auto-pursue ones that don't need human help (door/supervision).
    if not requires_help:
        store_goal(Goal(kind="explore_zone", target=destination, notes=f"owner asked to go to {destination}"))
    save_pip_runtime()
    remember_event(RoverEvent(kind=RoverEventKind.manual_control, source="pip_goal", label=f"goal:{destination}", payload=goal))
    return goal


@app.post("/pip/command")
async def pip_command(command: PipCommand) -> dict:
    text = command.text.strip().lower()
    if text in {"status", "pip status", "where are you", "pip where are you"}:
        return {"ok": True, "handled": True, "action": "state", "state": pip_public_state()}
    if text in {"brain", "pip brain", "what are you doing", "pip what are you doing", "what do you want", "pip what do you want"}:
        return {"ok": True, "handled": True, "action": "brain", "brain": pip_brain_snapshot(compact=True)}
    destination = parse_destination_wish(text)
    if destination:
        goal = pip_set_exploration_goal(destination, source=command.source)
        line = f"I want to go to {destination}. " + ("I need you to open/clear the way and supervise me before I try." if goal["requires_human_help"] else "I can plan it after preflight and movement permission.")
        await pip_set_expression(ExpressionMode.seeking, "go?", 0.55)
        return {"ok": True, "handled": True, "action": "destination_goal", "line": line, "goal": goal, "brain": pip_brain_snapshot(compact=True)}
    if text in {"wake", "pip wake", "hi pip", "hello pip"}:
        return {"ok": True, "handled": True, "action": "wake", "result": await pip_wake()}
    if text in {"sleep", "pip sleep"}:
        return {"ok": True, "handled": True, "action": "sleep", "result": await pip_sleep()}
    if text in {"quiet", "pip quiet"}:
        return {"ok": True, "handled": True, "action": "mode", "result": await pip_mode(PipModeCommand(mode="quiet", reason=f"{command.source} command"))}
    if text in {"social", "pip social"}:
        return {"ok": True, "handled": True, "action": "mode", "result": await pip_mode(PipModeCommand(mode="social", reason=f"{command.source} command"))}
    if text in {"assistant", "pip assistant"}:
        return {"ok": True, "handled": True, "action": "mode", "result": await pip_mode(PipModeCommand(mode="assistant", reason=f"{command.source} command"))}
    if text in {"greet", "pip greet"}:
        return {"ok": True, "handled": True, "action": "greet", "result": await pip_greet(source=command.source)}
    if text in {"patrol", "pip patrol", "explore", "pip explore"}:
        return {"ok": True, "handled": True, "action": "life_tick", "result": await pip_life_tick(PipLifeTickCommand(allow_movement=command.allow_movement, force=True, reason=f"{command.source} patrol command"))}
    if text in {"first adventure", "pip first adventure", "adventure", "pip adventure"}:
        return {"ok": True, "handled": True, "action": "first_adventure", "result": await first_adventure_task(FirstAdventureCommand(zone="office", allow_movement=command.allow_movement, duration_seconds=30, explore_cycles=4, speak=True, compact=True, notes=f"{command.source} first adventure command"))}
    if text in {"observe", "pip observe", "look around", "pip look around"}:
        return {"ok": True, "handled": True, "action": "observe", "result": await vision_awareness_task(VisionAwarenessCommand(zone="office", capture=True, scan=True, compact=True, notes=f"{command.source} observe command"))}
    if text in {"stop", "pip stop"}:
        await body.stop()
        return {"ok": True, "handled": True, "action": "stop", "stopped": True}
    hermes_context = {"state": pip_public_state(), "brain": pip_brain_snapshot(compact=True)}
    # Blocking HTTP/TTS off the event loop so the reflex watchdog keeps running.
    hermes = await asyncio.to_thread(ask_hermes_as_pip, command.text, context=hermes_context)
    if hermes.get("ok"):
        answer = str(hermes.get("answer") or "").strip()
        pip_state["mood"] = "happy" if any(word in answer.lower() for word in ["hi", "ready", "good", "happy"]) else "curious"
        await pip_set_expression(ExpressionMode.speaking, "pip", 0.55)
        speech = (await asyncio.to_thread(speak_text, answer)) if os.getenv("HERMES_PIP_SPEAK_RESPONSE", "true").lower() not in {"0", "false", "no"} else {"ok": True, "skipped": True}
        event = remember_event(RoverEvent(kind=RoverEventKind.speech, source="pip_hermes_bridge", label="pip reply", payload={"prompt": command.text, "answer": answer, "speech": speech, "usage": hermes.get("raw_usage")}))
        save_pip_runtime()
        return {"ok": True, "handled": True, "action": "hermes_reply", "answer": answer, "speech": speech, "event": event.model_dump(), "state": pip_public_state()}
    return {
        "ok": True,
        "handled": False,
        "action": "relay_to_hermes",
        "prompt": command.text,
        "context": hermes_context,
        "bridge": hermes,
        "note": "Set HERMES_API_BASE/HERMES_API_KEY (or CLEO_ROVER_HERMES_API_BASE/_API_KEY) on cleo-rover-body to let Pip ask Hermes automatically, then speak the answer.",
    }


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


@app.get("/mind/status")
def mind_status() -> dict:
    return {
        "ok": True,
        "enabled": CONFIG.mind.enabled,
        "configured": mind.mind_configured(),
        "allowed_intents": list(mind.ALLOWED_INTENTS),
        "note": "The LLM mind proposes intents; the Pi validates and may refuse. Deterministic policy is the default + fallback.",
    }


@app.post("/mind/step")
async def mind_step(zone: str = "office") -> dict:
    """One deliberative step: ask the pluggable LLM mind for a high-level intent,
    validate it Pi-side, dispatch it if safe, else fall back to the deterministic
    policy. The deterministic policy is also used directly when the mind is
    disabled/offline, so Pip never depends on the cloud to keep acting safely.
    """

    def deterministic_command() -> BodyIntentCommand:
        intent = choose_body_intent(supervisor_status(), zone=zone)
        return BodyIntentCommand.model_validate(intent | {"source": "deterministic"})

    # Local-only path: mind disabled or no endpoint configured.
    if not CONFIG.mind.enabled or not mind.mind_configured():
        command = deterministic_command()
        result = await supervisor_intent(command)
        return {"ok": True, "source": "deterministic", "mind_used": False, "intent": command.model_dump(), "result": result}

    # Offload the (blocking) LLM HTTP call to a thread so the event loop -- and the
    # async safety watchdog/drive-monitor running on it -- keep ticking while we wait.
    mind_result = await asyncio.to_thread(
        mind.ask_mind_for_intent,
        packet=pip_brain_snapshot(compact=True),
        soul_prompt=pip_soul_prompt(),
        max_tokens=CONFIG.mind.max_tokens,
        timeout=CONFIG.mind.timeout_s,
    )
    if mind_result.get("ok"):
        intent = mind_result["intent"]
        # set_goal is a mission, not a motor command: persist it (the arbiter/local
        # layer executes it across ticks, even if the mind later goes offline).
        if intent.get("intent") == "set_goal":
            params = intent.get("params") or {}
            goal = store_goal(Goal(kind=params.get("goal_kind", "observe"), target=str(params.get("target", "")), notes="set by mind"))
            return {"ok": True, "source": "mind", "mind_used": True, "set_goal": goal.model_dump()}
        command = BodyIntentCommand.model_validate(intent | {"source": "mind"})
        result = await supervisor_intent(command)
        if result.get("accepted"):
            return {"ok": True, "source": "mind", "mind_used": True, "intent": command.model_dump(), "result": result}
        # The mind's intent was refused by Pi-local safety -> deterministic fallback.
        fallback = deterministic_command()
        fb_result = await supervisor_intent(fallback)
        return {
            "ok": True,
            "source": "deterministic_fallback",
            "mind_used": True,
            "mind_refused": result.get("reason"),
            "mind_intent": command.model_dump(),
            "intent": fallback.model_dump(),
            "result": fb_result,
        }

    # Mind error / offline -> deterministic fallback (Pip keeps acting).
    command = deterministic_command()
    result = await supervisor_intent(command)
    return {"ok": True, "source": "deterministic_fallback", "mind_used": False, "mind_error": mind_result.get("error"), "intent": command.model_dump(), "result": result}


# --------------------------------------------------------------------------- #
# Tier 3 navigation: VFH+ steering, occupancy-grid frontiers, topological place
# graph, wall-following, and memory consolidation. All ADVISORY -- movement still
# flows through grant + armed motors + the authoritative reflex tier.
# --------------------------------------------------------------------------- #
def ingest_summary_into_grid(summary: dict) -> None:
    """Feed a scan into the persistent rolling grid (only when mapping is on)."""
    if not CONFIG.nav.mapping_enabled:
        return
    samples = sweep_samples_from_summary(summary)
    if samples:
        NAV_GRID.update_from_sweep(samples)


def vfh_turn_deg(result, *, blocked_streak: int = 0) -> float:
    """Convert a VFH steering bearing into a bounded open-loop rotate (deg)."""
    if result.blocked or result.chosen_bearing_deg is None:
        return 18.0 if blocked_streak % 2 == 0 else -18.0
    bearing = float(result.chosen_bearing_deg)
    if abs(bearing) < 8.0:
        return 0.0
    deg = max(-25.0, min(25.0, bearing * 0.45))
    if abs(deg) < 12.0:
        deg = 12.0 if deg >= 0 else -12.0
    if blocked_streak >= 3:
        deg += 6.0 if deg >= 0 else -6.0
    return max(-32.0, min(32.0, deg))


async def reactive_choose_turn(summary: dict, *, blocked_streak: int = 0) -> dict:
    """Pick a recovery/steering turn. Uses VFH+ when nav.use_vfh_steering is on,
    else the legacy widest-gap heuristic. Same return contract either way."""
    if not CONFIG.nav.use_vfh_steering:
        return await reactive_turn_toward(summary.get("best"), blocked_streak=blocked_streak)
    result = vfh_mod.steer(sweep_samples_from_summary(summary), cfg=VFH_CFG, target_bearing_deg=0.0)
    deg = vfh_turn_deg(result, blocked_streak=blocked_streak)
    vfh_detail = {"chosen_bearing_deg": result.chosen_bearing_deg, "blocked": result.blocked, "free_runs": result.free_runs, "reason": result.reason}
    if abs(deg) < 1.0:
        return {"ok": True, "skipped": True, "reason": "vfh: gap already centered", "deg": deg, "vfh": vfh_detail}
    turn = await rotate_step(RotateStepCommand(deg=deg, require_permission=True))
    turn["vfh"] = vfh_detail
    return turn


@app.post("/nav/plan")
async def nav_plan(command: MapScanCommand, target_bearing_deg: float = 0.0) -> dict:
    """Read-only smart-nav plan: sweep -> VFH+ body-frame steering + occupancy-grid
    frontiers. No movement (the operator/mind can act on the advice via a task)."""
    scan, summary = await reactive_escape_scan(command.zone, command.angles)
    samples = sweep_samples_from_summary(summary)
    steer = vfh_mod.steer(samples, cfg=VFH_CFG, target_bearing_deg=target_bearing_deg)
    snap = OccupancyGrid(config=grid_config_from(CONFIG.nav))
    snap.update_from_sweep(samples)
    ingest_summary_into_grid(summary)
    return {
        "ok": True,
        "zone": command.zone,
        "samples": samples,
        "steering": {
            "chosen_bearing_deg": steer.chosen_bearing_deg,
            "blocked": steer.blocked,
            "reason": steer.reason,
            "free_runs": steer.free_runs,
            "candidates": steer.candidates,
        },
        "frontiers": snap.frontiers(min_cluster=3),
        "grid": snap.stats(),
        "advisory": "VFH+ body-frame steering + occupancy-grid frontiers. Movement still requires a grant + armed motors + reflex clearance.",
    }


@app.get("/nav/grid")
def nav_grid() -> dict:
    return {"ok": True, "stats": NAV_GRID.stats(), "ascii": NAV_GRID.ascii_map(), "frontiers": NAV_GRID.frontiers(min_cluster=3), "mapping_enabled": CONFIG.nav.mapping_enabled}


@app.post("/nav/grid/reset")
def nav_grid_reset() -> dict:
    global NAV_GRID
    NAV_GRID = OccupancyGrid(config=grid_config_from(CONFIG.nav))
    return {"ok": True, "reset": True, "stats": NAV_GRID.stats()}


@app.post("/topo/observe")
async def topo_observe(command: MapScanCommand, name: str | None = None, action: str = "forward") -> dict:
    """Fingerprint the current place (sonar signature) and add/recognize it in the
    topological graph, linking an edge from the last place. Relocalizes on a match."""
    global _last_topo_node
    if not CONFIG.nav.topo_enabled:
        return {"ok": False, "reason": "topo graph disabled (nav.topo_enabled=false)"}
    scan, summary = await reactive_escape_scan(command.zone, command.angles)
    sig = sonar_signature_from_summary(summary, command.angles)
    result = TOPO.observe(sonar_sig=sig, last_node_id=_last_topo_node, action=action, now=time.time(), name=name or command.zone)
    set_last_topo_node(result["node_id"])
    save_topo()
    return {"ok": True, "result": result, "signature": sig, "graph": TOPO.summary()}


@app.get("/topo/graph")
def topo_graph() -> dict:
    return {"ok": True, "summary": TOPO.summary(), "current_node": _last_topo_node, "graph": TOPO.to_dict()}


@app.get("/topo/plan")
def topo_plan(to: str, frm: str | None = None) -> dict:
    start = frm or _last_topo_node
    if not start:
        return {"ok": False, "reason": "no current place; run /topo/observe first"}
    return {"ok": True, **TOPO.plan(start, to)}


@app.post("/topo/merge")
def topo_merge() -> dict:
    merged = TOPO.merge_duplicates()
    save_topo()
    return {"ok": True, "merged": merged, "graph": TOPO.summary()}


def _spatial_to_episodes() -> list[dict]:
    """Map remembered sightings into consolidation episodes (label@zone, with the
    item's observation count so a repeatedly-seen landmark can become a fact)."""
    episodes: list[dict] = []
    for item in store.list_spatial(300):
        if not item.zone or item.kind == "range_scan":
            continue  # raw range pings are not semantic landmarks
        episodes.append(
            {
                "label": item.label,
                "zone": item.zone,
                "confidence": item.confidence,
                "timestamp": item.last_seen_at or time.time(),
                "bearing_deg": item.bearing_deg,
                "count": item.observations,
                "detail": item.notes,
            }
        )
    return episodes


def run_consolidation() -> dict:
    """Distill episodic spatial memory into durable semantic facts (decay/
    reinforce/promote/prune) and persist them."""
    cfg = consolidation_mod.ConsolidationConfig(promote_n=CONFIG.nav.consolidation_promote_n)
    facts = consolidation_mod.facts_from_dicts(store.list_facts(500))
    res = consolidation_mod.consolidate(_spatial_to_episodes(), facts, now=time.time(), cfg=cfg)
    store.save_facts(consolidation_mod.facts_to_dicts(res["facts"]))
    return {"ok": True, "promoted": res["promoted"], "reinforced": res["reinforced"], "pruned": res["pruned"], "fact_count": res["fact_count"]}


@app.post("/memory/consolidate")
def memory_consolidate() -> dict:
    return run_consolidation()


@app.get("/memory/facts")
def memory_facts(limit: int = 100) -> dict:
    return {"ok": True, "facts": store.list_facts(limit)}


@app.get("/battery")
def battery_status() -> dict:
    """Honest battery state: sag-aware SOC, charging trend, debounced low/critical.

    Reads fresh, feeds the estimator (idle vs in-motion), and returns its view.
    SOC uses the real 2S Li-ion resting curve, not the old linear guess."""
    sensors_now = body.sensors()
    reading = update_battery(sensors_now)
    return {
        "ok": True,
        "pcb_version": CONFIG.sensors.pcb_version,
        "voltage": reading.voltage,
        "resting_voltage": reading.resting_voltage,
        "soc_percent": reading.soc_percent,
        "instantaneous_soc": reading.instantaneous_soc,
        "charging": reading.charging,
        "warn": reading.warn,
        "critical": reading.critical,
        "trusted": reading.trusted,
        "note": reading.note,
        "thresholds": {"warn_v": BATTERY.warn_v, "critical_v": BATTERY.critical_v},
    }


@app.get("/calibration")
def calibration_status() -> dict:
    """Power-up bring-up: the ordered FNK0043 calibration checklist + the auto-
    checkable readiness gates (sensor readiness, plausible battery) so Pip can
    confirm it is ready for a supervised drive after a short calibration."""
    from . import calibration as calibration_mod

    sensors_now = body.sensors()
    reading = update_battery(sensors_now)
    gates = calibration_mod.autonomy_gates(
        sensors=sensors_now, battery_voltage=getattr(reading, "voltage", None), pcb_version=CONFIG.sensors.pcb_version
    )
    return {"ok": True, "mode": body.mode, "checklist": calibration_mod.CHECKLIST, **gates}


@app.get("/pip/rgb-affect")
def pip_rgb_affect() -> dict:
    """The RGB expression frame Pip is showing now (mood->colour/pattern). With no
    display, the LED strip is the expression channel. Sim-safe (computes only)."""
    frame = compute_affect_frame(phase=0.0)
    return {"ok": True, "color": list(frame.color), "brightness": frame.brightness, "pattern": frame.pattern, "label": frame.label, "enabled": CONFIG.life_loop.rgb_expression_enabled}


@app.post("/vision/flow")
def vision_flow() -> dict:
    """Advisory optical-flow stall/looming cue. Needs OpenCV + a live camera; in
    sim/dev it reports unavailable (the pure logic is unit-tested separately)."""
    available = vision_service.optical_flow_available() and body.mode == "hardware"
    return {
        "ok": True,
        "available": available,
        "enabled": CONFIG.nav.flow_stall_enabled,
        "note": "Optical flow confirms stalls + looming on hardware; advisory only, never relaxes a reflex.",
        "backends": vision_service.vision_backends(),
    }


def _cruise_dry_run_decision(summary: dict) -> dict:
    """Build a PolarSnapshot from a scan summary and compute the would-be cruise
    decision WITHOUT moving. Shows what continuous motion would choose right now."""
    now = time.time()
    snap = perception_mod.PolarSnapshot()
    for b, d in sweep_samples_from_summary(summary):
        snap.update(b, d, now)
    steer = vfh_mod.steer(snap.vfh_samples(now), cfg=VFH_CFG, target_bearing_deg=0.0)
    fwd_min, fwd_age = snap.fwd_cone(now, half_deg=CRUISE_PARAMS.forward_cone_deg, max_age_ms=CRUISE_PARAMS.fwd_stale_ms)
    decision = cruise_mod.steer_to_command(
        chosen_bearing_deg=steer.chosen_bearing_deg,
        blocked=steer.blocked,
        fwd_min_cm=fwd_min,
        fwd_worst_age_ms=fwd_age,
        grant_active=True,  # reveal the drive decision as if a grant existed
        pan_deg=0.0,
        params=CRUISE_PARAMS,
    )
    return {
        "action": decision.action,
        "linear": decision.linear,
        "turn": decision.turn,
        "stop": decision.stop,
        "cornered": decision.cornered,
        "reason": decision.reason,
        "speed_cap_linear": round(cruise_mod.cruise_speed_cap(CRUISE_PARAMS), 3),
        "speed_cap_cm_s": round(cruise_mod.cruise_speed_cap_cm_s(CRUISE_PARAMS), 1),
        "forward_min_cm": fwd_min,
        "steering": {"chosen_bearing_deg": steer.chosen_bearing_deg, "blocked": steer.blocked},
    }


@app.post("/pip/cruise")
async def pip_cruise(on: bool = False, dry_run: bool = True, zone: str = "cruise", duration_seconds: int = 300) -> dict:
    """Continuous smooth-motion control.

    - dry_run (default): sweep once, show the cruise decision Pip WOULD make now
      (no movement) -- safe everywhere, the way to validate the policy on the floor.
    - on=true: start the perception + cruise tasks (requires
      nav.continuous_motion_enabled AND hardware AND a movement grant). on=false: stop.

    Movement still flows through grant + armed motors + the authoritative reflex/
    bearing guard; cruise can only choose among safe motions, never relax a stop.
    """
    global _cruise_stop_event, _perception_task_handle, _cruise_task_handle, movement_grant
    if not on and not dry_run:
        # explicit stop
        if _cruise_stop_event is not None:
            _cruise_stop_event.set()
        await body.stop()
        return {"ok": True, "cruising": False, "stopped": True}

    if dry_run or not on:
        angles = sorted(set([float(a) for a in CONFIG.nav.cruise_side_angles] + [0.0]))
        scan, summary = await reactive_escape_scan(zone, angles)
        return {"ok": True, "dry_run": True, "moved": False, "decision": _cruise_dry_run_decision(summary), "advisory": "dry-run only; no movement. Flip nav.continuous_motion_enabled + grant + on=true on hardware to cruise."}

    # on=true live path (hardware + flag + grant gated)
    if not CONFIG.nav.continuous_motion_enabled:
        return {"ok": False, "reason": "continuous motion disabled (nav.continuous_motion_enabled=false)"}
    if body.mode != "hardware":
        return {"ok": False, "reason": "cruise tasks only start on hardware; use dry_run in sim"}
    if not body.motors_armed:
        return {"ok": False, "reason": "motors not armed"}
    if _cruise_task_handle is not None and not _cruise_task_handle.done():
        return {"ok": True, "cruising": True, "note": "already cruising"}
    _cruise_stop_event = asyncio.Event()
    # Cruise takes an owned self-grant so it (and only it) may drive while cruising;
    # an operator/arbiter task overwriting the grant flips the owner -> cruise yields.
    movement_grant = MovementPermissionCommand(task="cruise", allow_movement=True, duration_seconds=duration_seconds, max_linear=CONFIG.nav.cruise_max_linear, max_turn=CONFIG.nav.cruise_max_turn, notes="continuous cruise").model_dump() | {"expires_at": time.time() + duration_seconds, "active": True, "owner": "cruise"}

    def _clamp_pan(a: float) -> float:
        return max(CONFIG.turret.pan_min_deg, min(CONFIG.turret.pan_max_deg, float(a)))

    def _grant_active() -> bool:
        # Drive only while cruise still OWNS the grant (yield to any foreign owner).
        return cruise_mod.grant_permits(active_movement_grant(), "cruise")

    _perception_task_handle = asyncio.create_task(
        perception_mod.perception_task(
            body, CRUISE_SNAPSHOT, side_angles=list(CONFIG.nav.cruise_side_angles),
            settle_ms=CONFIG.nav.weave_settle_ms, clamp_pan=_clamp_pan, now_fn=time.monotonic, stop_event=_cruise_stop_event,
        )
    )
    _cruise_task_handle = asyncio.create_task(
        cruise_mod.cruise_task(
            body, CRUISE_SNAPSHOT, vfh_cfg=VFH_CFG, params=CRUISE_PARAMS,
            grant_active_fn=_grant_active, guarded_drive=guarded_drive, now_fn=time.monotonic, stop_event=_cruise_stop_event,
        )
    )
    return {"ok": True, "cruising": True, "speed_cap_linear": round(cruise_mod.cruise_speed_cap(CRUISE_PARAMS), 3)}


@app.post("/tasks/return-home")
async def return_home_task(goal: str = "charger", allow_movement: bool = False, max_hops: int = 12, segment_cm: float = 40.0, duration_seconds: int = 120) -> dict:
    """Traverse the topological place-graph to a goal place (default the charger),
    relocalising at each node. Aborts and asks for help if it can't recognise the
    next place after a few tries (drift never compounds across the route).

    allow_movement=false => plan + report only (no driving)."""
    global _last_topo_node, movement_grant
    if not CONFIG.nav.topo_enabled:
        return {"ok": False, "reason": "topo graph disabled (nav.topo_enabled=false)"}
    route = topo_exec.plan_return(TOPO, _last_topo_node, goal)
    if not route.get("ok"):
        return {"ok": False, "reason": route.get("reason", "no route"), "route": route}
    state = topo_exec.ReturnState(path=list(route["path"]), actions=list(route["actions"]))
    armed_note = None
    if allow_movement and not body.motors_armed:
        # Honest state: don't publish a live grant while motors are disarmed (I-4).
        allow_movement = False
        armed_note = "motors not armed; planned route only (no movement)"
    if not allow_movement:
        return {"ok": True, "moved": False, "route": route, "status": state.status(), "note": armed_note or "plan only; set allow_movement=true (with armed motors + grant) to traverse"}

    grant = MovementPermissionCommand(task=f"return-home:{goal}", allow_movement=True, duration_seconds=duration_seconds, max_linear=0.3, max_turn=0.65, notes="Pi-side topo route traversal")
    movement_grant = grant.model_dump() | {"expires_at": time.time() + grant.duration_seconds, "active": True, "owner": "return_home"}
    events.add(store.add_event(RoverEvent(kind=RoverEventKind.movement_permission, source="return_home", label=grant.task, payload=movement_grant | {"goal": goal})))

    log_steps: list[dict] = []
    deadline = time.time() + duration_seconds
    hops = 0
    while not state.done and not state.aborted and hops < max_hops and time.time() < deadline:
        hops += 1
        action = state.current_action or {}
        for kind, value in topo_exec.edge_motions(action.get("action", "forward"), float(action.get("heading_out", 0.0)), segment_cm=segment_cm):
            if kind == "rotate" and abs(value) >= 1.0:
                # rotate_step is a single bounded pulse (<=45deg); a 90/180deg edge
                # must be issued in chunks or the turn is silently truncated and
                # relocalisation always misses (bug found in review).
                for step in topo_exec.rotation_chunks(value, max_step=45.0):
                    await rotate_step(RotateStepCommand(deg=step, require_permission=True))
            elif kind == "forward":
                await adaptive_forward_stride(value, chunk_cm=6.0, require_permission=True)
        # Relocalise: fingerprint where we ended up and check against the expected node.
        angles = sorted(set([float(a) for a in CONFIG.nav.cruise_side_angles] + [0.0]))
        _, summary = await reactive_escape_scan(goal, angles)
        sig = sonar_signature_from_summary(summary, angles)
        rec = TOPO.recognize(sig, [], 0)
        result = state.on_observed(rec.node_id)
        if rec.node_id:
            set_last_topo_node(rec.node_id)
        log_steps.append({"hop": hops, "expected": state.expected_next, "observed": rec.node_id, "result": result, "status": state.status()})
        if result == "advanced" and state.done:
            break
    await body.stop()
    save_topo()
    if state.aborted:
        pip_enqueue_interrupt("high", f"I tried to get to {goal} but lost my way. Can you help me?", kind="rescue", payload={"route": route, "steps": log_steps})
    return {"ok": True, "moved": True, "goal": goal, "done": state.done, "aborted": state.aborted, "route": route, "steps": log_steps, "status": state.status()}


@app.post("/tasks/wall-follow")
async def wall_follow_task(zone: str = "wall", side: str = "left", allow_movement: bool = False, max_cycles: int = 20, duration_seconds: int = 45) -> dict:
    """Trace a wall at a setpoint distance (best coverage primitive without pose).

    Pans the sonar to the side for the perpendicular reading and forward for
    inside-corner detection, then PD-follows. Gated by nav.wall_follow_enabled."""
    global movement_grant
    if not CONFIG.nav.wall_follow_enabled:
        return {"ok": False, "reason": "wall-follow disabled (nav.wall_follow_enabled=false)"}
    side = "left" if side != "right" else "right"
    side_angle = max(CONFIG.turret.pan_min_deg, min(CONFIG.turret.pan_max_deg, 70.0 if side == "left" else -70.0))
    grant = MovementPermissionCommand(task=f"wall-follow:{zone}", allow_movement=allow_movement, duration_seconds=duration_seconds, max_linear=max(0.1, WALL_CFG.base_linear), max_turn=WALL_CFG.max_turn, notes="Pi-side PD wall follow")
    movement_grant = grant.model_dump() | {"expires_at": time.time() + grant.duration_seconds, "active": grant.allow_movement and body.motors_armed, "owner": "wall_follow"}
    event = store.add_event(RoverEvent(kind=RoverEventKind.movement_permission, source="wall_follow", label=grant.task, payload=movement_grant | {"zone": zone, "side": side}))
    events.add(event)
    plan: list[dict] = []
    prev_error: float | None = None
    deadline = time.time() + duration_seconds
    try:
        for cycle in range(max_cycles):
            if time.time() >= deadline:
                plan.append({"kind": "halt", "reason": "duration elapsed"})
                break
            await body.set_turret(TurretCommand(pan_deg=side_angle))
            await asyncio.sleep(0.12)
            side_cm = normalize_distance_cm(body.front_distance_median())
            await body.set_turret(TurretCommand(pan_deg=0))
            await asyncio.sleep(0.08)
            front_cm = normalize_distance_cm(body.front_distance_median())
            decision = wall_follow_step(side_cm=side_cm, front_cm=front_cm, prev_error_cm=prev_error, side=side, cfg=WALL_CFG)
            prev_error = decision.error_cm
            plan.append({"kind": "decision", "cycle": cycle + 1, "action": decision.action, "side_cm": side_cm, "front_cm": front_cm, "turn": decision.turn, "reason": decision.reason})
            if not allow_movement:
                plan.append({"kind": "scan-only", "reason": "movement not permitted"})
                break
            drive = await guarded_drive(DriveCommand(linear=decision.linear, turn=decision.turn, duration_ms=160), require_permission=True)
            plan.append({"kind": "drive", "result": drive})
            fresh_reflex = body.consume_reflex_stop()
            if fresh_reflex:
                plan.append({"kind": "reflex-stop", "result": fresh_reflex})
            await asyncio.sleep(0.1)
    finally:
        await body.set_turret(TurretCommand(pan_deg=0))
        await body.stop()
    return {"ok": True, "side": side, "zone": zone, "plan": plan, "task": movement_grant | {"zone": zone}}


@app.post("/tasks/reactive-explore")
async def reactive_explore_task(command: ReactiveExploreCommand) -> dict:
    """Freenove-style local obstacle avoidance loop.

    This runs on the Pi/body service: sense -> decide -> short action -> sense.
    The PC brain only grants/starts the task; fast obstacle handling is local.
    """
    global movement_grant
    grant = MovementPermissionCommand(
        task=f"reactive-explore:{command.zone}",
        allow_movement=command.allow_movement,
        duration_seconds=command.duration_seconds,
        max_linear=max(0.1, command.crawl_linear),
        max_turn=0.65,
        notes=command.notes or "Pi-side Freenove-style reactive explore",
    )
    # Honest grant: active only when movement is BOTH requested AND motors are armed,
    # so /status never shows a live grant while disarmed (audit I-4). The loop still
    # runs its sense/scan logic; guarded_drive is the real motion gate.
    movement_grant = grant.model_dump() | {"expires_at": time.time() + grant.duration_seconds, "active": grant.allow_movement and body.motors_armed, "owner": "reactive_explore"}
    event = store.add_event(RoverEvent(kind=RoverEventKind.movement_permission, source="reactive_explore", label=grant.task, payload=movement_grant | {"zone": command.zone}))
    events.add(event)
    # Pre-move memory consult + coverage: order the scan so least-recently-visited
    # bearings come first (systematic sweep), then prefer remembered-open / avoid
    # remembered-close. Order only -- the same angles are still sampled.
    _now = time.time()
    _items = store.list_spatial(200)
    _covered = explore.least_recently_visited_first(command.scan_angles, _items, now=_now)
    command = command.model_copy(update={"scan_angles": explore.prioritize_scan_angles(_covered, explore.memory_bias(_items, now=_now))})
    plan: list[dict] = []
    deadline = time.time() + command.duration_seconds
    blocked_streak = 0

    for cycle in range(command.max_cycles):
        if time.time() >= deadline:
            plan.append({"kind": "halt", "reason": "duration elapsed"})
            break
        # Escalation ladder: when truly stuck (high blocked streak), stop grinding
        # and surface a corner-trap so the post-run rescue asks the owner for help.
        if stuck.stuck_level(blocked_streak=blocked_streak) >= 4:
            plan.append({"kind": "corner-trap", "cycle": cycle + 1, "reason": f"stuck after blocked_streak={blocked_streak}; asking for help"})
            break
        sensors_now = body.sensors()
        distance = sensors_now.get("front_distance_cm")
        distance_value = float(distance) if distance is not None else None
        plan.append({"kind": "sense", "cycle": cycle + 1, "front_distance_cm": distance_value, "sensors": {"errors": sensors_now.get("errors"), "battery_percent": sensors_now.get("battery_percent")}})

        if not command.allow_movement:
            scan, summary = await reactive_escape_scan(command.zone, command.scan_angles)
            plan.append({"kind": "scan-only", "cycle": cycle + 1, "summary": summary, "result": scan})
            break

        if distance_value is None:
            scan, summary = await reactive_escape_scan(command.zone, command.scan_angles)
            plan.append({"kind": "scan", "reason": "front range unknown", "summary": summary})
            turn = await reactive_choose_turn(summary, blocked_streak=blocked_streak)
            plan.append({"kind": "turn", "reason": "range unknown", "result": turn})
            await asyncio.sleep(0.08)
            continue

        if distance_value < command.front_emergency_cm:
            blocked_streak += 1
            await body.stop()
            plan.append({"kind": "stop", "reason": f"emergency front {distance_value:.1f}cm < {command.front_emergency_cm:.1f}cm"})
            if command.reverse_on_blocked:
                reverse = await guarded_drive(DriveCommand(linear=-0.28, turn=0, duration_ms=220), require_permission=True)
                plan.append({"kind": "reverse", "result": reverse})
                await asyncio.sleep(0.25)
            scan, summary = await reactive_escape_scan(command.zone, command.scan_angles)
            plan.append({"kind": "scan", "reason": "emergency escape", "summary": summary, "result": scan})
            turn = await reactive_choose_turn(summary, blocked_streak=blocked_streak)
            plan.append({"kind": "turn", "reason": "emergency escape", "result": turn})
            await asyncio.sleep(0.15)
            continue

        if distance_value < command.front_stop_cm:
            blocked_streak += 1
            await body.stop()
            scan, summary = await reactive_escape_scan(command.zone, command.scan_angles)
            plan.append({"kind": "scan", "reason": f"front blocked {distance_value:.1f}cm", "summary": summary, "result": scan})
            best = summary.get("best")
            best_distance = float(best["distance_cm"]) if best else 0.0
            if blocked_streak >= 4 and best_distance < command.front_clear_cm:
                plan.append({"kind": "corner-search", "reason": f"blocked for {blocked_streak} cycles; best side only {best_distance:.1f}cm; continuing scan/rotate search", "summary": summary})
                if command.reverse_on_blocked and blocked_streak % 3 == 1:
                    reverse = await guarded_drive(DriveCommand(linear=-0.20, turn=0, duration_ms=160), require_permission=True)
                    plan.append({"kind": "reverse", "reason": "make room for continued corner search", "result": reverse})
                    await asyncio.sleep(0.18)
            if blocked_streak >= 2 and command.reverse_on_blocked and not (blocked_streak >= 4 and blocked_streak % 3 == 1):
                reverse = await guarded_drive(DriveCommand(linear=-0.24, turn=0, duration_ms=180), require_permission=True)
                plan.append({"kind": "reverse", "reason": "blocked streak", "result": reverse})
                await asyncio.sleep(0.2)
            turn = await reactive_choose_turn(summary, blocked_streak=blocked_streak)
            plan.append({"kind": "turn", "reason": "front blocked", "result": turn})
            await asyncio.sleep(0.12)
            continue

        blocked_streak = 0
        if distance_value < command.front_clear_cm:
            scan, summary = await reactive_escape_scan(command.zone, command.scan_angles)
            plan.append({"kind": "scan", "reason": f"clearance {distance_value:.1f}cm below crawl threshold", "summary": summary, "result": scan})
            best = summary.get("best")
            center = summary.get("center")
            if best and (center is None or float(best["distance_cm"]) > float(center["distance_cm"]) + 20):
                turn = await reactive_choose_turn(summary, blocked_streak=blocked_streak)
                plan.append({"kind": "turn", "reason": "better side clearance", "result": turn})
            else:
                plan.append({"kind": "hold", "reason": "no side sufficiently better"})
            await asyncio.sleep(0.12)
            continue

        crawl = await guarded_drive(DriveCommand(linear=command.crawl_linear, turn=0, duration_ms=command.crawl_duration_ms), require_permission=True)
        plan.append({"kind": "crawl", "result": crawl, "sense_after_ms": command.decision_pause_ms})
        await asyncio.sleep(command.decision_pause_ms / 1000)
        fresh_reflex = body.consume_reflex_stop()
        if fresh_reflex:
            plan.append({"kind": "reflex-stop", "result": fresh_reflex})
            blocked_streak += 1

    await body.stop()
    sensors_after = body.sensors()
    summary = plan_summary(plan)
    # Self-rescue for direct callers too (not only via pip_life_tick): if Pip hit a
    # fresh reflex or got cornered while exploring, raise an operator interrupt.
    if summary.get("reflex_stop") or summary.get("corner_trap"):
        pip_enqueue_interrupt("high", "I bumped into something I could not get around while exploring. Can you help?", kind="rescue", payload={"reactive": summary})
    response = {
        "ok": True,
        "task": movement_grant | {"zone": command.zone},
        "summary": summary,
        "battery": battery_safety_summary(sensors_after),
        "event": event.model_dump(),
        "safety": "Pi-side sense/decide/act loop with ramped wheel PWM, 20ms drive-monitor reflex checks, 30ms persistent forward watchdog, short configurable crawl pulses, no forward crawl below front_clear_cm, and continued scan/rotate search when blocked.",
    }
    response["plan"] = compact_plan(plan) if command.compact else plan
    return response


@app.post("/tasks/vision-awareness")
async def vision_awareness_task(command: VisionAwarenessCommand) -> dict:
    capture = capture_camera_snapshot(CONFIG.camera.capture_dir, width=CONFIG.camera.width, height=CONFIG.camera.height) if body.mode == "hardware" and command.capture else None
    # On a real capture, run on-Pi vision and emit a vision_analysis event so the
    # brain gets fresh latest_vision (fixes the latest_vision:null path).
    local_vision = None
    if CONFIG.vision.enabled and capture and capture.get("ok"):
        local_vision = ingest_local_vision(command.zone, capture.get("path"))
    scan = await visual_map_scan(VisualMapScanCommand(zone=command.zone, angles=command.angles, settle_ms=250, capture_each_angle=False)) if command.scan else None
    scan_summary = scan_observation_summary(scan) if scan else None
    placeholder_analysis = None
    if command.remember_placeholder and capture and capture.get("ok"):
        placeholder_analysis = {
            "summary": "Captured scene awaiting external vision labels.",
            "labels": ["scene"],
            "objects": [],
            "confidence": 0.25,
            "zone": command.zone,
            "snapshot_path": capture.get("path"),
            "source": "vision_awareness_placeholder",
        }
    event = remember_event(
        RoverEvent(
            kind=RoverEventKind.camera_snapshot,
            source="vision_awareness",
            label=f"vision awareness {command.zone}",
            payload={"zone": command.zone, "capture": capture, "scan": scan, "scan_summary": scan_summary, "placeholder_analysis": placeholder_analysis, "needs_external_vision": True, "notes": command.notes},
        )
    )
    response = {
        "ok": True,
        "zone": command.zone,
        "capture": capture,
        "scan_summary": scan_summary,
        "event": event.model_dump(),
        "placeholder_analysis": placeholder_analysis,
        "local_vision": local_vision,
        "next_step": "On-Pi vision ran if a model is installed; otherwise send capture to Hermes vision and POST to /vision/analysis.",
    }
    if not command.compact:
        response["scan"] = scan
    return response


async def topo_automap(zone: str) -> dict | None:
    """Fingerprint the current place into the topo graph during normal autonomy so
    the place-graph actually BUILDS (else return-home has no map). Cheap: one scan."""
    if not CONFIG.nav.topo_enabled:
        return None
    try:
        angles = sorted(set([float(a) for a in CONFIG.nav.cruise_side_angles] + [0.0]))
        _, summary = await reactive_escape_scan(zone, angles)
        sig = sonar_signature_from_summary(summary, angles)
        result = TOPO.observe(sonar_sig=sig, last_node_id=_last_topo_node, action="forward", now=time.time(), name=zone)
        set_last_topo_node(result["node_id"])
        save_topo()
        return result
    except Exception:
        return None


@app.post("/tasks/little-being-loop")
async def little_being_loop(command: LittleBeingLoopCommand) -> dict:
    started = time.time()
    initial_sensors = body.sensors()
    battery = battery_safety_summary(initial_sensors)
    movement_allowed = command.allow_movement and battery["recommendation"] != "charge_before_movement"
    mood = ExpressionMode(command.mood) if command.mood in ExpressionMode._value2member_map_ else ExpressionMode.curious
    await body.set_expression(ExpressionCommand(mode=mood, text="exploring" if movement_allowed else "watching", brightness=0.6))
    steps: list[dict] = []
    intro = remember_event(
        RoverEvent(
            kind=RoverEventKind.idle_tick,
            source="little_being_loop",
            label=f"little being loop {command.zone}",
            payload={"zone": command.zone, "allow_movement": command.allow_movement, "movement_allowed": movement_allowed, "battery": battery, "notes": command.notes},
        )
    )

    if command.capture_vision:
        vision = await vision_awareness_task(VisionAwarenessCommand(zone=command.zone, capture=True, scan=True, angles=[-45, 0, 45], compact=True, notes="little being opening observation"))
        steps.append({"kind": "observe", "result": {"capture": vision.get("capture"), "scan_summary": vision.get("scan_summary")}})

    remaining = max(5, int(command.duration_seconds - (time.time() - started)))
    explore = await reactive_explore_task(
        ReactiveExploreCommand(
            zone=command.zone,
            allow_movement=movement_allowed,
            duration_seconds=remaining,
            max_cycles=command.explore_cycles,
            crawl_linear=0.34,
            crawl_duration_ms=220,
            decision_pause_ms=100,
            front_clear_cm=130.0,
            front_stop_cm=55.0,
            front_emergency_cm=30.0,
            reverse_on_blocked=True,
            scan_angles=[-70, -45, -20, 0, 20, 45, 70],
            compact=True,
            notes="little being local reactive explore",
        )
    )
    steps.append({"kind": "reactive-explore", "summary": explore.get("summary"), "battery": explore.get("battery"), "plan": explore.get("plan")})

    if command.capture_vision and command.observe_every_cycles <= max(1, command.explore_cycles):
        vision = await vision_awareness_task(VisionAwarenessCommand(zone=command.zone, capture=True, scan=True, angles=[-35, 0, 35], compact=True, notes="little being closing observation"))
        steps.append({"kind": "observe", "result": {"capture": vision.get("capture"), "scan_summary": vision.get("scan_summary")}})

    await body.stop()
    # Build the topological map as Pip patrols, so return-home has a graph to use.
    automap = await topo_automap(command.zone)
    if automap:
        steps.append({"kind": "topo-automap", "result": {"event": automap.get("event"), "node_id": automap.get("node_id")}})
    final_sensors = body.sensors()
    final_battery = battery_safety_summary(final_sensors)
    if final_battery["recommendation"] == "charge_before_movement":
        await body.set_expression(ExpressionCommand(mode=ExpressionMode.low_power, text="charge me", brightness=0.45))
    else:
        await body.set_expression(ExpressionCommand(mode=ExpressionMode.proud, text="done", brightness=0.55))

    summary = {
        "movement_allowed": movement_allowed,
        "battery_start": battery,
        "battery_end": final_battery,
        "reactive": explore.get("summary"),
        "vision_observations": sum(1 for step in steps if step.get("kind") == "observe"),
        "duration_seconds": round(time.time() - started, 2),
    }
    done = remember_event(RoverEvent(kind=RoverEventKind.manual_control, source="little_being_loop", label="little being loop complete", payload={"summary": summary, "steps": steps if not command.compact else None}))
    response = {"ok": True, "event": intro.model_dump(), "complete_event": done.model_dump(), "summary": summary, "safety": "Fast motion safety remains Pi-side: reactive explore + watchdog. Vision is awareness, not collision safety."}
    if not command.compact:
        response["steps"] = steps
    return response


def first_adventure_readiness(preflight_now: dict, observe: dict | None, adventure: dict | None, *, allow_movement: bool) -> dict:
    failed = [check for check in preflight_now.get("checks", []) if not check.get("ok")]
    scan_summary = (observe or {}).get("scan_summary") or {}
    best = scan_summary.get("best") or {}
    center = scan_summary.get("center") or {}
    recommendations: list[str] = []
    ready = not failed
    if failed:
        recommendations.append("fix failed preflight checks before floor movement")
    if allow_movement and not ready:
        recommendations.append("keep Pip in observe-only mode until preflight is green")
    def maybe_float(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    best_distance = maybe_float(best.get("distance_cm"))
    center_distance = maybe_float(center.get("distance_cm"))
    if best_distance is not None and best_distance < 80:
        recommendations.append("clear a wider starting bubble around Pip")
    if center_distance is not None and center_distance < 60:
        recommendations.append("start with Pip facing a more open direction")
    reactive = (adventure or {}).get("summary", {}).get("reactive") or {}
    if reactive.get("reflex_stop"):
        ready = False
        recommendations.append("reflex stop fired; inspect the obstacle path before another run")
    if reactive.get("corner_search"):
        recommendations.append("Pip had to search for an exit; widen the first-adventure area")
    if not recommendations:
        recommendations.append("ready for one supervised tiny floor adventure")
    return {
        "ready": ready,
        "movement_mode": "tiny_supervised_floor" if allow_movement and ready else "observe_only",
        "failed_checks": failed,
        "recommendations": recommendations,
    }


@app.post("/tasks/first-adventure")
async def first_adventure_task(command: FirstAdventureCommand) -> dict:
    """Bounded launch ritual for Pip's first assembled-shell floor adventure."""
    await body.stop()
    pip_state["current_zone"] = command.zone
    pip_state["mood"] = "curious"
    save_pip_runtime()

    preflight_mode = "floor-cautious" if command.allow_movement else "presence"
    preflight_now = preflight(preflight_mode)
    actions: list[dict] = [{"kind": "safe-stop", "result": {"ok": True, "stopped": True}}, {"kind": "preflight", "mode": preflight_mode, "ok": preflight_now.get("ok")}]

    if command.require_preflight and not preflight_now.get("ok"):
        await pip_set_expression(ExpressionMode.watching, "preflight", 0.45)
        observe = await vision_awareness_task(VisionAwarenessCommand(zone=command.zone, capture=True, scan=True, angles=[-60, -30, 0, 30, 60], compact=True, notes="first adventure observe-only fallback"))
        actions.append({"kind": "observe-only", "result": {"capture": observe.get("capture"), "scan_summary": observe.get("scan_summary")}})
        readiness = first_adventure_readiness(preflight_now, observe, None, allow_movement=False)
        event = remember_event(RoverEvent(kind=RoverEventKind.manual_control, source="first_adventure", label="preflight blocked first adventure", payload={"readiness": readiness, "actions": actions, "notes": command.notes}))
        return {"ok": True, "started_movement": False, "event": event.model_dump(), "readiness": readiness, "actions": actions, "preflight": preflight_now, "next_step": "Fix preflight, then rerun first-adventure with --allow-movement."}

    await pip_set_expression(ExpressionMode.curious, "ready?", 0.58)
    if command.speak:
        speech = speak_text("Pip first adventure preflight started. I will stay tiny and careful.")
        actions.append({"kind": "speech", "result": speech})

    observe = await vision_awareness_task(VisionAwarenessCommand(zone=command.zone, capture=True, scan=True, angles=[-60, -30, 0, 30, 60], compact=True, notes="first adventure opening observation"))
    actions.append({"kind": "observe", "result": {"capture": observe.get("capture"), "scan_summary": observe.get("scan_summary")}})

    adventure = await little_being_loop(
        LittleBeingLoopCommand(
            zone=command.zone,
            allow_movement=command.allow_movement,
            duration_seconds=command.duration_seconds,
            explore_cycles=command.explore_cycles,
            observe_every_cycles=max(1, command.explore_cycles),
            capture_vision=False,
            compact=True,
            mood="curious",
            notes=command.notes or "first adventure: assembled-shell supervised tiny exploration",
        )
    )
    actions.append({"kind": "little-being-loop", "summary": adventure.get("summary")})

    await body.stop()
    await pip_set_expression(ExpressionMode.proud, "home", 0.55)
    readiness = first_adventure_readiness(preflight_now, observe, adventure, allow_movement=command.allow_movement)
    if command.speak:
        line = "First adventure complete. " + ("I am ready for another tiny supervised step." if readiness["ready"] else "I need a little help before moving again.")
        actions.append({"kind": "speech", "result": speak_text(line)})
    event = remember_event(RoverEvent(kind=RoverEventKind.manual_control, source="first_adventure", label="first adventure complete", payload={"readiness": readiness, "actions": None if command.compact else actions, "notes": command.notes}))
    response = {
        "ok": True,
        "started_movement": bool(command.allow_movement and preflight_now.get("ok")),
        "event": event.model_dump(),
        "readiness": readiness,
        "preflight": preflight_now,
        "summary": adventure.get("summary"),
        "safety": "First adventure always begins with stop+preflight, uses vision/ultrasonic awareness, delegates motion to little-being/reactive-explore, then stops again.",
    }
    if not command.compact:
        response["actions"] = actions
    return response


@app.post("/tasks/hallway-scout")
async def hallway_scout_task(command: HallwayScoutCommand) -> dict:
    try:
        return await _hallway_scout_task(command)
    except Exception as exc:  # Fail closed: stop motors and return the real error to the CLI.
        await body.stop()
        return {
            "ok": False,
            "started_movement": False,
            "reason": "hallway scout internal error",
            "error": repr(exc),
            "traceback_tail": traceback.format_exc().splitlines()[-8:],
            "stopped": True,
        }


async def _hallway_scout_task(command: HallwayScoutCommand) -> dict:
    """Fast supervised doorway/hallway scout.

    This is intentionally Pi-local and sensor-first: short proven movement pulses,
    stop after every action, quick ultrasonic checks every cycle, and camera/Hermes
    vision only every N cycles for slower semantic context. If front range blocks,
    it scans and turns toward the best clearance instead of repeatedly trying forward.
    """
    global movement_grant
    await body.stop()
    preflight_now = preflight("floor-cautious")
    actions: list[dict] = [{"kind": "safe-stop"}, {"kind": "preflight", "ok": preflight_now.get("ok")}]
    if not command.allow_movement:
        observe = await vision_awareness_task(VisionAwarenessCommand(zone=command.zone, capture=True, scan=True, angles=[-60, -30, 0, 30, 60], compact=True, notes="hallway scout observe-only"))
        return {"ok": True, "started_movement": False, "preflight": preflight_now, "actions": actions + [{"kind": "observe-only", "result": {"capture": observe.get("capture"), "scan_summary": observe.get("scan_summary")}}]}
    if not preflight_now.get("ok"):
        await body.stop()
        return {"ok": False, "started_movement": False, "reason": "preflight failed", "preflight": preflight_now, "actions": actions}

    estimated_cycle_seconds = command.pause_seconds + (22.0 if command.speak else 8.0)
    grant = MovementPermissionCommand(
        task=f"hallway-scout:{command.zone}",
        allow_movement=True,
        duration_seconds=int(max(90 if command.speak else 30, 30 + command.cycles * estimated_cycle_seconds)),
        max_linear=0.40,
        max_turn=0.75,
        notes=command.notes or "supervised fast hallway scout",
    )
    movement_grant = grant.model_dump() | {"expires_at": time.time() + grant.duration_seconds, "active": True}
    event = store.add_event(RoverEvent(kind=RoverEventKind.movement_permission, source="hallway_scout", label=grant.task, payload=movement_grant | {"zone": command.zone}))
    events.add(event)
    await pip_set_expression(ExpressionMode.seeking, "scout", 0.55)
    if command.speak:
        actions.append({"kind": "speech", "result": speak_text("Scout mode. I will move farther when it is open, and slow down near the doorway.")})

    blocked_streak = 0
    clear_streak = 0
    bands = DoorwayBands(
        emergency_cm=command.emergency_cm,
        blocked_cm=command.blocked_cm,
        clear_cm=command.clear_cm,
        reflex_hard_cm=body._reflex_threshold_cm(),
    )
    for cycle in range(1, command.cycles + 1):
        sensors_now = body.sensors()
        front = normalize_distance_cm(sensors_now.get("front_distance_cm"))
        raw_front_cm = float(front) if front is not None else None
        # Consume a *fresh* reflex event only. A stale retained reflex no longer
        # re-counts every cycle (the old bug that forced phantom recovery turns).
        fresh_reflex = body.consume_reflex_stop()
        if fresh_reflex:
            actions.append({"kind": "reflex-stop", "cycle": cycle, "result": fresh_reflex, "fresh": True})

        if command.vision_every and (cycle == 1 or cycle % command.vision_every == 0):
            try:
                vision = await vision_awareness_task(VisionAwarenessCommand(zone=command.zone, capture=True, scan=False, compact=True, notes=f"hallway scout cycle {cycle}"))
                latest = (vision.get("placeholder_analysis") or {}) if isinstance(vision, dict) else {}
                actions.append({"kind": "vision", "cycle": cycle, "raw_front_cm": raw_front_cm, "capture": vision.get("capture"), "latest_placeholder": latest})
            except Exception as exc:
                actions.append({"kind": "vision-error", "cycle": cycle, "raw_front_cm": raw_front_cm, "error": repr(exc)})
                # Vision is helpful but never allowed to crash the Pi-local safety loop.

        scan_summary: dict[str, Any] | None = None
        if command.scan_before_move:
            _scan, scan_summary = await reactive_escape_scan(command.zone, command.scan_angles)
            actions.append({"kind": "range-scan", "cycle": cycle, "raw_front_cm": raw_front_cm, "summary": scan_summary})

        center = (scan_summary or {}).get("center") if scan_summary else None
        best = (scan_summary or {}).get("best") if scan_summary else None
        scan_center_cm = float(center.get("distance_cm")) if center and center.get("distance_cm") is not None else None
        best_distance = float(best.get("distance_cm")) if best and best.get("distance_cm") is not None else None
        best_bearing = float(best.get("bearing_deg")) if best and best.get("bearing_deg") is not None else None

        # Advisory camera cue: only adds caution (holds forward motion), never
        # relaxes a reflex. Block on a fresh, confident "not clear ahead" + hazard.
        vision_block = False
        if CONFIG.vision.enabled:
            vis = store.recent_events(1, kind=RoverEventKind.vision_analysis.value)
            if vis:
                vp = vis[0].payload or {}
                if vp.get("clear_path") is False and (vp.get("hazards") or float(vp.get("confidence", 0.0) or 0.0) >= 0.5):
                    vision_block = True

        decision = decide_hallway_action(
            raw_front_cm=raw_front_cm,
            scan_center_cm=scan_center_cm,
            best_bearing_deg=best_bearing,
            best_distance_cm=best_distance,
            fresh_reflex=bool(fresh_reflex),
            blocked_streak=blocked_streak,
            clear_streak=clear_streak,
            bands=bands,
            side_gain_cm=command.side_gain_cm,
            confirm_blocked=command.confirm_blocked,
            confirm_clear=command.confirm_clear,
            creep_step_cm=command.min_step_cm,
            vision_block=vision_block,
        )
        blocked_streak = decision.blocked_streak
        clear_streak = decision.clear_streak
        extend_active_movement_grant(20)

        if decision.action == ACTION_ADVANCE:
            planned_step = command.step_cm
            if command.adaptive_step:
                planned_step = adaptive_forward_step_cm(
                    center_distance_cm=scan_center_cm,
                    front_distance_cm=raw_front_cm,
                    blocked_cm=command.blocked_cm,
                    min_step_cm=command.min_step_cm,
                    max_step_cm=command.max_step_cm,
                    fallback_step_cm=command.step_cm,
                )
            if command.speak:
                actions.append({"kind": "speech", "cycle": cycle, "result": speak_text(f"Path looks open. Moving about {planned_step:.0f} centimeters.")})
            move = await adaptive_forward_stride(planned_step, chunk_cm=command.stride_chunk_cm, require_permission=True, brake_cm=bands.reflex_hard_cm)
            action = {"kind": ACTION_ADVANCE, "planned_step_cm": planned_step, "result": move}
        elif decision.action == ACTION_CREEP:
            planned_step = decision.planned_step_cm or command.min_step_cm
            if command.speak:
                actions.append({"kind": "speech", "cycle": cycle, "result": speak_text(f"Doorway is open ahead. Creeping about {planned_step:.0f} centimeters.")})
            move = await adaptive_forward_stride(planned_step, chunk_cm=min(command.stride_chunk_cm, planned_step), require_permission=True, brake_cm=bands.reflex_hard_cm)
            action = {"kind": ACTION_CREEP, "planned_step_cm": planned_step, "result": move}
        elif decision.action == ACTION_EMERGENCY_ESCAPE:
            await body.stop()
            if command.speak:
                actions.append({"kind": "speech", "cycle": cycle, "result": speak_text("Too close. Backing off and finding another way.")})
            scan_turn = await hallway_scout_scan_turn(command.zone, command.scan_angles, reason=decision.reason)
            action = {"kind": ACTION_EMERGENCY_ESCAPE, "result": scan_turn}
        elif decision.action in (ACTION_SCAN_TURN, ACTION_ALIGN_TURN):
            if command.speak:
                line = "I see more room to one side. Turning to line up." if decision.action == ACTION_ALIGN_TURN else "Looking for a clear way through."
                actions.append({"kind": "speech", "cycle": cycle, "result": speak_text(line)})
            scan_turn = await hallway_scout_scan_turn(command.zone, command.scan_angles, reason=decision.reason)
            action = {"kind": decision.action, "result": scan_turn}
        else:  # ACTION_HOLD: a single ambiguous read; stop and re-confirm next cycle.
            await body.stop()
            action = {"kind": ACTION_HOLD}

        action.update({
            "cycle": cycle,
            "phase": decision.phase,
            "reason": decision.reason,
            "raw_front_cm": decision.raw_front_cm,
            "scan_center_cm": decision.scan_center_cm,
            "decision_front_cm": decision.decision_front_cm,
            # Kept for plan_summary/compact_action back-compat; reflects decided clearance.
            "front_distance_cm": decision.decision_front_cm,
            "blocked_streak": blocked_streak,
            "clear_streak": clear_streak,
        })
        if scan_summary:
            action["summary"] = scan_summary
        actions.append(action)
        await asyncio.sleep(command.pause_seconds)
        await body.stop()

    await body.stop()
    final_sensors = body.sensors()
    summary = plan_summary(actions)
    done = remember_event(RoverEvent(kind=RoverEventKind.manual_control, source="hallway_scout", label="hallway scout complete", payload={"summary": summary, "final_sensors": final_sensors, "notes": command.notes}))
    await pip_set_expression(ExpressionMode.proud, "done", 0.55)
    if command.speak:
        actions.append({"kind": "speech", "result": speak_text("Hallway scout complete. I stopped and I am waiting.")})
    return {
        "ok": True,
        "started_movement": True,
        "event": event.model_dump(),
        "complete_event": done.model_dump(),
        "summary": summary,
        "final_front_distance_cm": final_sensors.get("front_distance_cm"),
        "safety": "Adaptive route strides executed as short chunks, stop after every chunk, ultrasonic checks and range-scan before movement, scan+turn when center is not clear, camera/Hermes context at configured intervals.",
        "actions": compact_plan(actions) if command.compact else actions,
    }


@app.post("/tasks/return-to")
async def return_to_task(label: str = "charger", allow_movement: bool = False, zone: str = "office") -> dict:
    """Orient toward a remembered landmark (e.g. the charger).

    Scans, finds the nearest matching landmark in spatial memory, and (if movement
    is allowed + granted) turns toward its bearing. This is the 'go back to a known
    place' primitive; it only ORIENTS here -- full path planning is the LLM mind's
    job. Returns found:false (with guidance) when nothing matches yet.
    """
    await map_scan(MapScanCommand(zone=zone, angles=[-60, -40, -20, 0, 20, 40, 60], settle_ms=200))
    items = store.list_spatial(300)
    target = explore.nearest_landmark(items, label=label)
    if target is None or target.bearing_deg is None:
        return {"ok": True, "found": False, "label": label, "note": f"no remembered landmark matching '{label}'; explore/observe first or POST /map/remember"}
    turn_deg = explore.bearing_to_turn(target.bearing_deg)
    actions: list[dict[str, Any]] = [{"kind": "target", "landmark": target.model_dump(), "turn_deg": turn_deg}]
    if allow_movement and abs(turn_deg) >= 1.0:
        extend_active_movement_grant(10)
        actions.append({"kind": "turn", "result": await rotate_step(RotateStepCommand(deg=turn_deg, require_permission=True))})
    return {
        "ok": True,
        "found": True,
        "label": label,
        "target": target.model_dump(),
        "turn_deg": turn_deg,
        "actions": actions,
        "safety": "return-to only orients toward a remembered landmark; movement gated by grant + armed motors.",
    }


@app.post("/tasks/line-follow")
async def line_follow_task(command: LineFollowCommand) -> dict:
    """Gentle indoor line-follow with the 3 IR sensors.

    The cliff (downward IR), ultrasonic, and bumper reflexes always pre-empt line
    following — a fresh reflex stops the task. Movement stays gated by a grant +
    armed motors, so this is bench-safe by default.
    """
    global movement_grant
    grant = MovementPermissionCommand(
        task=f"line-follow:{command.zone}",
        allow_movement=command.allow_movement,
        duration_seconds=command.duration_seconds,
        max_linear=max(0.1, command.base_linear),
        max_turn=0.65,
        notes=command.notes or "gentle indoor line follow",
    )
    movement_grant = grant.model_dump() | {"expires_at": time.time() + grant.duration_seconds, "active": grant.allow_movement}
    event = store.add_event(RoverEvent(kind=RoverEventKind.movement_permission, source="line_follow", label=grant.task, payload=movement_grant | {"zone": command.zone}))
    events.add(event)
    plan: list[dict] = []
    deadline = time.time() + command.duration_seconds
    prev_error = 0.0
    lost_streak = 0
    for cycle in range(1, command.max_cycles + 1):
        if time.time() >= deadline:
            plan.append({"kind": "halt", "reason": "duration elapsed"})
            break
        # Safety reflexes (cliff/obstacle/bump) pre-empt line following.
        fresh_reflex = body.consume_reflex_stop()
        if fresh_reflex:
            await body.stop()
            plan.append({"kind": "reflex-stop", "cycle": cycle, "result": fresh_reflex})
            break
        sensors_now = body.sensors()
        line = sensors_now.get("line_sensors")
        if not isinstance(line, dict):
            plan.append({"kind": "no-line-sensors", "cycle": cycle})
            break
        decision = decide_line_follow(line, on_value=command.line_on_value, kp=command.kp, kd=command.kd, prev_error=prev_error, base_linear=command.base_linear)
        if decision["lost"]:
            lost_streak += 1
            await body.stop()
            plan.append({"kind": "line-lost", "cycle": cycle, "lost_streak": lost_streak})
            if lost_streak >= command.lost_stop_cycles:
                plan.append({"kind": "stop", "reason": "line lost"})
                break
            if command.allow_movement:
                extend_active_movement_grant(8)
                await guarded_drive(DriveCommand(linear=0.0, turn=search_turn(prev_error), duration_ms=150), require_permission=True)
            await asyncio.sleep(command.decision_pause_ms / 1000)
            continue
        lost_streak = 0
        prev_error = decision["error"]
        if command.allow_movement:
            extend_active_movement_grant(8)
            drive = await guarded_drive(DriveCommand(linear=decision["linear"], turn=decision["turn"], duration_ms=command.step_ms), require_permission=True)
            plan.append({"kind": "follow", "cycle": cycle, "decision": decision, "drive_ok": drive.get("ok")})
        else:
            plan.append({"kind": "follow-sim", "cycle": cycle, "decision": decision})
        await asyncio.sleep(command.decision_pause_ms / 1000)
    await body.stop()
    counts: dict[str, int] = {}
    for item in plan:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    return {
        "ok": True,
        "task": movement_grant | {"zone": command.zone},
        "counts": counts,
        "event": event.model_dump(),
        "plan": ([{"kind": item["kind"], "cycle": item.get("cycle")} for item in plan] if command.compact else plan),
        "safety": "Cliff/ultrasonic/bumper reflexes pre-empt line follow; movement gated by grant + armed motors.",
    }


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


# ---------------------------------------------------------------------------
# Top-level autonomy: goals, self-preservation, social reactions, and the
# behavior-arbitration loop that ties everything together so Pip acts on its own.
# All motion still flows through guarded_drive + grants + the reflex floor.
# ---------------------------------------------------------------------------

_arbiter_task: asyncio.Task | None = None


def active_goal() -> Goal | None:
    raw = pip_state.get("goal")
    if not raw:
        return None
    try:
        goal = Goal.model_validate(raw)
    except Exception:
        return None
    if goal.status != "active":
        return None
    if goal.expires_at and time.time() > float(goal.expires_at):
        return None
    return goal


def store_goal(goal: Goal) -> Goal:
    if goal.created_at is None:
        goal = goal.model_copy(update={"created_at": time.time()})
    pip_state["goal"] = goal.model_dump()
    save_pip_runtime()
    remember_event(RoverEvent(kind=RoverEventKind.manual_control, source="goal", label=f"goal:{goal.kind}:{goal.target}", payload=goal.model_dump()))
    return goal


def clear_goal() -> None:
    pip_state.pop("goal", None)
    save_pip_runtime()


def _latest_person_pet() -> dict:
    """Person/pet presence + coarse bearing from the latest vision analysis."""
    info = {"person": False, "pet": False, "bearing": None, "distance": None}
    vis = store.recent_events(1, kind=RoverEventKind.vision_analysis.value)
    if not vis:
        return info
    payload = vis[0].payload or {}
    labels = {str(label).lower() for label in (payload.get("labels") or [])}
    info["person"] = bool(labels & {"person", "human", "noot"})
    info["pet"] = bool(labels & {"cat", "dog", "pet"})
    for obj in payload.get("objects") or []:
        if isinstance(obj, dict) and str(obj.get("label", "")).lower() in {"person", "cat", "dog"}:
            info["bearing"] = obj.get("bearing_bucket")
            break
    return info


async def behavior_return_to_charger(*, allow_movement: bool) -> dict:
    """Self-preservation: actually TRAVERSE the topo graph to the charger (relocalising
    per node); fall back to orient-only, then ask to be docked. Wires the arbiter to
    the real navigator instead of just pointing at the charger (audit I-1)."""
    # Prefer the topo executor when we know where we are and a charger place exists.
    # Pass the MATCHED node's id (a place taught as "dock"/"charg" wouldn't match a
    # hardcoded goal="charger" — review bug).
    dock_node = TOPO.node_by_name("charg") or TOPO.node_by_name("dock")
    if CONFIG.nav.topo_enabled and _last_topo_node and dock_node:
        home = await return_home_task(goal=dock_node.id, allow_movement=allow_movement)
        if home.get("ok") and not home.get("aborted") and (home.get("done") or not allow_movement):
            return {"behavior": "return_to_charger", "via": "topo", "result": home}
        # aborted / lost the way -> fall through to orient + ask for help
    zone = str(pip_state.get("current_zone") or "office")
    result = await return_to_task(label="charger", allow_movement=allow_movement, zone=zone)
    if not result.get("found"):
        rescue = await pip_rescue("my battery is getting low and I can't find my charger. can you help me dock?", priority="high", payload={"battery": battery_safety_summary(body.sensors())})
        return {"behavior": "return_to_charger", "via": "orient", "found": False, "rescue": rescue}
    return {"behavior": "return_to_charger", "via": "orient", "result": result}


async def pursue_goal(goal: Goal, *, allow_movement: bool) -> dict:
    zone = goal.target or str(pip_state.get("current_zone") or "office")
    if goal.kind == "return_to":
        result = {"kind": "return_to", "result": await return_to_task(label=goal.target or "charger", allow_movement=allow_movement, zone=str(pip_state.get("current_zone") or "office"))}
    elif goal.kind == "explore_zone":
        loop = await little_being_loop(LittleBeingLoopCommand(zone=zone, allow_movement=allow_movement, duration_seconds=30, explore_cycles=6, capture_vision=True, compact=True, mood=autonomy.state.mood))
        result = {"kind": "explore_zone", "result": loop.get("summary")}
    elif goal.kind == "find_person":
        observe = await vision_awareness_task(VisionAwarenessCommand(zone=zone, capture=True, scan=True, compact=True, notes="goal: find person"))
        result = {"kind": "find_person", "result": {"scan_summary": observe.get("scan_summary"), "seen": _latest_person_pet()}}
    else:  # observe
        observe = await vision_awareness_task(VisionAwarenessCommand(zone=zone, capture=False, scan=True, compact=True, notes="goal: observe"))
        result = {"kind": "observe", "result": {"scan_summary": observe.get("scan_summary")}}
    # Advance the goal and retire it when its step budget is spent.
    goal = goal.model_copy(update={"progress": goal.progress + 1})
    if goal.progress >= goal.step_budget:
        goal = goal.model_copy(update={"status": "done"})
    store_goal(goal)
    return {"goal": goal.model_dump(), **result}


async def behavior_socialize(*, allow_movement: bool, quiet: bool) -> dict:
    info = _latest_person_pet()
    last_greet = pip_state.get("last_greet_at")
    seconds = (time.time() - float(last_greet)) if last_greet else None
    react = social.decide_social_reaction(
        person_present=info["person"],
        pet_present=info["pet"],
        bearing_bucket=info["bearing"],
        distance_cm=info["distance"],
        seconds_since_greet=seconds,
        quiet=quiet,
    )
    actions: list[dict] = [{"kind": "reaction", "result": react}]
    turn_deg = float(react.get("turn_deg") or 0.0)
    if abs(turn_deg) >= 1.0:
        if allow_movement:
            actions.append({"kind": "turn", "result": await rotate_step(RotateStepCommand(deg=turn_deg, require_permission=True))})
        else:
            # Even bench-safe, Pip can orient its turret/gaze toward the person.
            await body.set_turret(TurretCommand(pan_deg=max(-80.0, min(80.0, turn_deg))))
            actions.append({"kind": "look", "pan_deg": turn_deg})
    if react.get("reaction") == "social.greet" or react.get("reaction") == "greet":
        await pip_greet(source="social")
    return {"behavior": "socialize", "reaction": react, "actions": actions}


def _now_minutes() -> int:
    local = time.localtime()
    return local.tm_hour * 60 + local.tm_min


def arbiter_context() -> dict:
    sensors_now = body.sensors()
    battery = battery_safety_summary(sensors_now)
    # Prefer the debounced, sag-aware estimator over raw percent (audit I-2): it
    # distinguishes a real flat pack from in-motion voltage sag, and won't trip on
    # a single dip. critical => charge now; charging => already docked, don't leave.
    reading = update_battery(sensors_now)
    battery_recommendation = "charge_before_movement" if reading.critical else battery["recommendation"]
    battery_percent = reading.soc_percent if reading.soc_percent is not None else sensors_now.get("battery_percent")
    feelings = pip_feelings()
    items = store.list_spatial(200)
    dock_known = explore.nearest_landmark(items, kind="dock") is not None or explore.nearest_landmark(items, label="charg") is not None
    quiet = arbiter.in_quiet_hours(_now_minutes(), CONFIG.life_loop.quiet_hours.model_dump())
    movement_allowed, _reason = pip_can_autonomously_move(allow_movement=True, battery=battery)
    info = _latest_person_pet()
    front = sensors_now.get("front_distance_cm")
    hazards_present = front is not None and float(front) < float(CONFIG.safety.front_stop_distance_cm) + 10.0
    return {
        "mode": pip_state.get("mode"),
        "awake": pip_state.get("awake"),
        "battery_recommendation": battery_recommendation,
        "battery_percent": battery_percent,
        "battery_charging": reading.charging,
        "energy": feelings["energy"],
        "curiosity": feelings["curiosity"],
        "boredom": feelings["boredom"],
        "has_goal": active_goal() is not None,
        "person_present": info["person"] or info["pet"],
        "hazards_present": hazards_present,
        "quiet": quiet,
        "do_not_disturb": autonomy.state.do_not_disturb,
        "movement_allowed": movement_allowed,
        "dock_known": dock_known,
        "return_to_charger_min_battery": CONFIG.life_loop.return_to_charger_min_battery,
    }


async def arbiter_tick(*, allow_movement: bool = False) -> dict:
    """One top-level decision: pick a behavior and run it via a safe primitive."""
    started = time.time()
    ctx = arbiter_context()
    decision = arbiter.arbitrate(ctx)
    behavior = decision["behavior"]
    move_ok = bool(allow_movement and ctx["movement_allowed"])
    result: dict[str, Any]
    if behavior == arbiter.BEHAVIOR_REST:
        await pip_set_expression(ExpressionMode.sleeping, "rest", 0.25)
        result = {"resting": True}
    elif behavior == arbiter.BEHAVIOR_RETURN_TO_CHARGER:
        result = await behavior_return_to_charger(allow_movement=move_ok)
    elif behavior == arbiter.BEHAVIOR_PURSUE_GOAL:
        goal = active_goal()
        result = await pursue_goal(goal, allow_movement=move_ok) if goal else {"note": "no active goal"}
    elif behavior == arbiter.BEHAVIOR_SOCIALIZE:
        result = await behavior_socialize(allow_movement=move_ok, quiet=ctx["quiet"])
    elif behavior == arbiter.BEHAVIOR_PATROL:
        loop = await little_being_loop(LittleBeingLoopCommand(zone=str(pip_state.get("current_zone") or "office"), allow_movement=move_ok, duration_seconds=30, explore_cycles=4 + round(autonomy.state.curiosity * 4), capture_vision=True, compact=True, mood=autonomy.state.mood))
        result = {"summary": loop.get("summary")}
    elif behavior == arbiter.BEHAVIOR_HOLD:
        await body.stop()
        result = {"holding": True}
    else:  # observe
        observe = await vision_awareness_task(VisionAwarenessCommand(zone=str(pip_state.get("current_zone") or "office"), capture=False, scan=True, compact=True, notes="arbiter observe"))
        result = {"scan_summary": observe.get("scan_summary")}
    remember_event(RoverEvent(kind=RoverEventKind.idle_tick, source="arbiter", label=f"arbiter:{behavior}", payload={"decision": decision}))
    record_task_result(f"arbiter:{behavior}", started, did_move=move_ok and behavior in {arbiter.BEHAVIOR_RETURN_TO_CHARGER, arbiter.BEHAVIOR_PURSUE_GOAL, arbiter.BEHAVIOR_PATROL}, extra={"reason": decision.get("reason")})
    return {"ok": True, "decision": decision, "context": ctx, "result": result}


def _start_arbiter_loop() -> None:
    """Start the self-directed behavior loop (hardware + arbiter_enabled only)."""
    global _arbiter_task
    interval = CONFIG.life_loop.arbiter_interval_seconds
    if body.mode != "hardware" or not CONFIG.life_loop.enabled or not CONFIG.life_loop.arbiter_enabled or interval <= 0:
        return
    if _arbiter_task and not _arbiter_task.done():
        return

    async def loop() -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await arbiter_tick(allow_movement=True)
            except Exception:
                pass

    _arbiter_task = asyncio.create_task(loop())


@app.get("/pip/arbiter")
def pip_arbiter_status() -> dict:
    return {
        "ok": True,
        "enabled": CONFIG.life_loop.arbiter_enabled,
        "interval_seconds": CONFIG.life_loop.arbiter_interval_seconds,
        "running": bool(_arbiter_task and not _arbiter_task.done()),
        "context": arbiter_context(),
        "would_choose": arbiter.arbitrate(arbiter_context()),
        "note": "The arbiter picks one behavior per tick and runs it via existing safe primitives; OFF by default and hardware-only.",
    }


@app.post("/pip/arbiter/tick")
async def pip_arbiter_tick(allow_movement: bool = False) -> dict:
    return await arbiter_tick(allow_movement=allow_movement)


@app.post("/pip/goal")
def pip_set_goal(goal: Goal) -> dict:
    return {"ok": True, "goal": store_goal(goal).model_dump()}


@app.get("/pip/goal")
def pip_get_goal() -> dict:
    goal = active_goal()
    return {"ok": True, "goal": goal.model_dump() if goal else None}


@app.delete("/pip/goal")
def pip_delete_goal() -> dict:
    clear_goal()
    return {"ok": True, "goal": None}
