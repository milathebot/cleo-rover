from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class ExpressionMode(str, Enum):
    idle = "idle"
    listening = "listening"
    thinking = "thinking"
    speaking = "speaking"
    alert = "alert"
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
