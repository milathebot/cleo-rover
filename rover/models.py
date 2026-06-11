from __future__ import annotations

from enum import Enum
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
