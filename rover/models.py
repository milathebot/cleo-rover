from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class ExpressionMode(str, Enum):
    idle = "idle"
    happy = "happy"
    sad = "sad"
    listening = "listening"
    thinking = "thinking"
    confused = "confused"
    speaking = "speaking"
    alert = "alert"
    mad = "mad"
    focused = "focused"
    laugh = "laugh"
    charging = "charging"
    disconnected = "disconnected"
    manual = "manual"
    curious = "curious"
    watching = "watching"
    seeking = "seeking"
    sleeping = "sleeping"
    shy = "shy"
    proud = "proud"
    low_power = "low_power"


class RoverEventKind(str, Enum):
    sound = "sound"
    speech = "speech"
    wake_word = "wake_word"
    motion = "motion"
    camera_snapshot = "camera_snapshot"
    button = "button"
    bump = "bump"
    obstacle = "obstacle"
    battery = "battery"
    network = "network"
    manual_control = "manual_control"
    idle_tick = "idle_tick"
    vision_analysis = "vision_analysis"
    map_observation = "map_observation"
    movement_permission = "movement_permission"


class RoverEvent(BaseModel):
    kind: RoverEventKind
    source: str = Field(default="sim", max_length=40)
    value: float | None = None
    label: str | None = Field(default=None, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: float | None = None


class AutonomyState(BaseModel):
    enabled: bool = True
    mood: str = "calm"
    attention: float = Field(default=0.25, ge=0.0, le=1.0)
    curiosity: float = Field(default=0.35, ge=0.0, le=1.0)
    energy: float = Field(default=0.80, ge=0.0, le=1.0)
    confidence: float = Field(default=0.65, ge=0.0, le=1.0)
    connected: bool = True
    do_not_disturb: bool = False
    current_intent: str = "quiet_presence"
    last_stimulus_at: float | None = None
    last_behavior: str | None = None
    last_decision_at: float | None = None


class BehaviorDecision(BaseModel):
    behavior: str
    reason: str
    attention_level: int = Field(default=0, ge=0, le=4)
    expression: "ExpressionCommand | None" = None
    turret: "TurretCommand | None" = None
    drive: "DriveCommand | None" = None
    speech: str | None = Field(default=None, max_length=240)
    stop: bool = False


class SpatialMemoryItem(BaseModel):
    id: str = Field(max_length=80)
    label: str = Field(max_length=120)
    kind: str = Field(default="object", max_length=40)
    zone: str | None = Field(default=None, max_length=80)
    bearing_deg: float | None = Field(default=None, ge=-180.0, le=180.0)
    distance_m: float | None = Field(default=None, ge=0.0, le=50.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    notes: str | None = Field(default=None, max_length=240)
    first_seen_at: float | None = None
    last_seen_at: float | None = None
    observations: int = Field(default=1, ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class AutonomyTickCommand(BaseModel):
    allow_movement: bool = False
    inject_idle_tick: bool = True


class VisionAnalysisCommand(BaseModel):
    summary: str = Field(max_length=800)
    labels: list[str] = Field(default_factory=list, max_length=20)
    objects: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = Field(default=0.55, ge=0.0, le=1.0)
    zone: str = Field(default="unknown", max_length=80)
    snapshot_path: str | None = Field(default=None, max_length=240)
    source: str = Field(default="external_vision", max_length=40)
    # Advisory navigation cues (None = unknown). Vision can add caution but never
    # relaxes the ultrasonic/cliff/bumper reflexes.
    clear_path: bool | None = None
    hazards: list[str] = Field(default_factory=list, max_length=20)


class MapScanCommand(BaseModel):
    zone: str = Field(default="unknown", max_length=80)
    angles: list[float] = Field(default_factory=lambda: [-45, -25, 0, 25, 45], max_length=13)
    settle_ms: int = Field(default=250, ge=50, le=1500)
    snapshot_center: bool = False


class VisualMapScanCommand(MapScanCommand):
    capture_each_angle: bool = True


class MovementPermissionCommand(BaseModel):
    task: str = Field(max_length=80)
    allow_movement: bool = False
    duration_seconds: int = Field(default=300, ge=1, le=1800)
    max_linear: float = Field(default=0.35, ge=0.0, le=1.0)
    max_turn: float = Field(default=0.7, ge=0.0, le=1.0)
    notes: str | None = Field(default=None, max_length=240)


class MapFloorTaskCommand(BaseModel):
    zone: str = Field(default="floor", max_length=80)
    allow_movement: bool = False
    steps: int = Field(default=3, ge=1, le=12)
    notes: str | None = Field(default=None, max_length=240)


class HallwayScoutCommand(BaseModel):
    zone: str = Field(default="hallway-transition", max_length=80)
    allow_movement: bool = False
    cycles: int = Field(default=8, ge=1, le=30)
    vision_every: int = Field(default=3, ge=0, le=10)
    scan_before_move: bool = True
    adaptive_step: bool = True
    step_cm: float = Field(default=4.0, ge=1.0, le=30.0)
    min_step_cm: float = Field(default=2.0, ge=1.0, le=10.0)
    max_step_cm: float = Field(default=24.0, ge=2.0, le=90.0)
    stride_chunk_cm: float = Field(default=6.0, ge=1.0, le=16.0)
    clear_cm: float = Field(default=75.0, ge=35.0, le=220.0)
    # blocked_cm is the top of the "too close to advance" band and the bottom of
    # the creep band. Lowered from 55 to 42 so there is a real creep band
    # (blocked_cm..clear_cm) for threading a doorway instead of a dead-zone.
    blocked_cm: float = Field(default=42.0, ge=30.0, le=140.0)
    # Below emergency_cm Pip stops + escapes immediately (independent of the
    # driver's hard reflex floor). Ordered: emergency_cm < blocked_cm < clear_cm.
    emergency_cm: float = Field(default=25.0, ge=10.0, le=60.0)
    # An off-axis bearing must beat the centered clearance by this much before Pip
    # turns to line up with it, so it does not abandon an open doorway ahead.
    side_gain_cm: float = Field(default=25.0, ge=5.0, le=80.0)
    # Hysteresis: consecutive fresh confirmations required before a recovery turn
    # (blocked) or before declaring the doorway exited (clear).
    confirm_blocked: int = Field(default=2, ge=1, le=6)
    confirm_clear: int = Field(default=2, ge=1, le=6)
    # Avoid turret extremes that can clip Pip's shell; use ~85% of physical pan range.
    scan_angles: list[float] = Field(default_factory=lambda: [-60, -40, -20, 0, 20, 40, 60], max_length=9)
    pause_seconds: float = Field(default=1.0, ge=0.0, le=8.0)
    speak: bool = False
    compact: bool = True
    notes: str | None = Field(default=None, max_length=240)


class ReactiveExploreCommand(BaseModel):
    zone: str = Field(default="office", max_length=80)
    allow_movement: bool = False
    duration_seconds: int = Field(default=45, ge=1, le=300)
    max_cycles: int = Field(default=20, ge=1, le=80)
    crawl_linear: float = Field(default=0.20, ge=0.0, le=0.5)
    crawl_duration_ms: int = Field(default=120, ge=60, le=300)
    decision_pause_ms: int = Field(default=80, ge=20, le=300)
    front_clear_cm: float = Field(default=120.0, ge=30.0, le=300.0)
    front_stop_cm: float = Field(default=45.0, ge=15.0, le=150.0)
    front_emergency_cm: float = Field(default=25.0, ge=5.0, le=80.0)
    reverse_on_blocked: bool = True
    scan_angles: list[float] = Field(default_factory=lambda: [-70, -45, -20, 0, 20, 45, 70], max_length=9)
    keep_searching_when_stuck: bool = True
    compact: bool = True
    notes: str | None = Field(default=None, max_length=240)


class LineFollowCommand(BaseModel):
    zone: str = Field(default="line", max_length=80)
    allow_movement: bool = False
    duration_seconds: int = Field(default=30, ge=1, le=300)
    max_cycles: int = Field(default=40, ge=1, le=200)
    base_linear: float = Field(default=0.22, ge=0.0, le=0.5)
    kp: float = Field(default=0.45, ge=0.0, le=2.0)
    kd: float = Field(default=0.15, ge=0.0, le=2.0)
    # Digital value that means "this sensor is over the line". Verify on hardware.
    line_on_value: int = Field(default=1, ge=0, le=1)
    step_ms: int = Field(default=140, ge=60, le=400)
    decision_pause_ms: int = Field(default=60, ge=10, le=300)
    lost_stop_cycles: int = Field(default=6, ge=1, le=30)
    compact: bool = True
    notes: str | None = Field(default=None, max_length=240)


class VisionAwarenessCommand(BaseModel):
    zone: str = Field(default="office", max_length=80)
    capture: bool = True
    scan: bool = True
    angles: list[float] = Field(default_factory=lambda: [-45, 0, 45], max_length=9)
    compact: bool = True
    remember_placeholder: bool = True
    notes: str | None = Field(default=None, max_length=240)


class LittleBeingLoopCommand(BaseModel):
    zone: str = Field(default="office", max_length=80)
    allow_movement: bool = False
    duration_seconds: int = Field(default=60, ge=5, le=600)
    explore_cycles: int = Field(default=8, ge=1, le=40)
    observe_every_cycles: int = Field(default=4, ge=1, le=20)
    capture_vision: bool = True
    compact: bool = True
    mood: str = Field(default="curious", max_length=40)
    notes: str | None = Field(default=None, max_length=240)


class FirstAdventureCommand(BaseModel):
    zone: str = Field(default="office", max_length=80)
    allow_movement: bool = False
    duration_seconds: int = Field(default=30, ge=5, le=180)
    explore_cycles: int = Field(default=4, ge=1, le=12)
    require_preflight: bool = True
    speak: bool = True
    compact: bool = True
    notes: str | None = Field(default=None, max_length=240)


class PipModeCommand(BaseModel):
    mode: str = Field(default="social", pattern="^(sleep|quiet|social|assistant)$")
    reason: str | None = Field(default=None, max_length=160)


class PipLifeTickCommand(BaseModel):
    allow_movement: bool = False
    force: bool = False
    reason: str = Field(default="life_tick", max_length=80)
    compact: bool = True


class PipCommand(BaseModel):
    text: str = Field(max_length=240)
    source: str = Field(default="telegram", max_length=40)
    allow_movement: bool = False


class MoveStepCommand(BaseModel):
    forward_cm: float = Field(default=10.0, ge=-30.0, le=30.0)
    require_permission: bool = True


class RotateStepCommand(BaseModel):
    deg: float = Field(default=15.0, ge=-45.0, le=45.0)
    require_permission: bool = True


class BodyIntentCommand(BaseModel):
    """High-level PC/Hermes brain intent for the Pi body agent."""

    intent: str = Field(max_length=40)
    mood: str | None = Field(default=None, max_length=40)
    speech: str | None = Field(default=None, max_length=240)
    params: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="pc_brain", max_length=40)


class DriveCommand(BaseModel):
    linear: float = Field(default=0.0, ge=-1.0, le=1.0, description="Forward/back command")
    turn: float = Field(default=0.0, ge=-1.0, le=1.0, description="Left/right turn command")
    duration_ms: int = Field(default=250, ge=1, le=2000, description="Mandatory timeout")


class TurretCommand(BaseModel):
    pan_deg: float = Field(default=0.0, ge=-80.0, le=80.0)


class ExpressionCommand(BaseModel):
    mode: ExpressionMode
    text: str | None = Field(default=None, max_length=80)
    brightness: float = Field(default=0.6, ge=0.0, le=1.0)


class RGBCommand(BaseModel):
    red: int = Field(default=0, ge=0, le=255)
    green: int = Field(default=0, ge=0, le=255)
    blue: int = Field(default=0, ge=0, le=255)
    brightness: int = Field(default=24, ge=0, le=255)


class RoverStatus(BaseModel):
    mode: str
    name: str = "cleo-rover-mk1"
    profile: str = "bench-sim"
    online: bool
    stopped: bool
    expression: ExpressionCommand
    last_drive: DriveCommand | None
    turret: TurretCommand
    battery_percent: float | None = None
    battery_voltage: float | None = None
    camera_ready: bool = False
    mic_ready: bool = False
    speaker_ready: bool = False
    display_ready: bool = False
    motors_armed: bool = False
    hardware_ready: bool = False
    safety: dict = Field(default_factory=dict)
