from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from .config import RoverConfig
from .models import DriveCommand, ExpressionCommand, ExpressionMode, TurretCommand


@dataclass
class SimState:
    stopped: bool = True
    last_drive: DriveCommand | None = None
    last_drive_at: float | None = None
    expression: ExpressionCommand = field(
        default_factory=lambda: ExpressionCommand(mode=ExpressionMode.idle, text="Cleo", brightness=0.45)
    )
    turret: TurretCommand = field(default_factory=lambda: TurretCommand(pan_deg=0))


class RoverBody:
    """Hardware abstraction.

    Starts as a simulator so the API and Hermes integration can be built before
    hardware arrives. Pi-specific GPIO/display/camera drivers will plug in here.
    """

    def __init__(self, mode: str = "sim", config: RoverConfig | None = None) -> None:
        self.mode = mode
        self.config = config or RoverConfig()
        self.state = SimState()
        self._stop_task: asyncio.Task | None = None
        self.hardware_ready = mode == "hardware" and not self.config.safety.bench_safe_no_motors
        self.display_ready = mode == "hardware"
        self.motors_armed = self.hardware_ready

    async def drive(self, command: DriveCommand) -> None:
        safe_duration = min(command.duration_ms, self.config.safety.max_drive_duration_ms)
        command = command.model_copy(update={"duration_ms": safe_duration})
        self.state.stopped = False
        self.state.last_drive = command
        self.state.last_drive_at = time.time()

        if self._stop_task and not self._stop_task.done():
            self._stop_task.cancel()

        async def auto_stop() -> None:
            await asyncio.sleep(command.duration_ms / 1000)
            await self.stop()

        self._stop_task = asyncio.create_task(auto_stop())

    async def stop(self) -> None:
        self.state.stopped = True
        # In hardware mode this will immediately zero motor PWM.

    async def set_expression(self, command: ExpressionCommand) -> None:
        self.state.expression = command
        # Hardware mode: render abstract Cleo UI on Waveshare ST7789.

    async def set_turret(self, command: TurretCommand) -> None:
        self.state.turret = command
        # Hardware mode: fixed camera pod means this may become a no-op unless
        # the Freenove kit's servo head is retained.

    def readiness(self) -> dict[str, bool]:
        return {
            "hardware_ready": self.hardware_ready,
            "display_ready": self.display_ready,
            "motors_armed": self.motors_armed,
            "bench_safe_no_motors": self.config.safety.bench_safe_no_motors,
        }

    def sensors(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "simulated": self.mode == "sim",
            "front_distance_cm": None,
            "front_stop_distance_cm": self.config.safety.front_stop_distance_cm,
            "imu": None,
            "battery_percent": None,
            "battery_voltage": None,
            "display": {
                "type": self.config.display.type,
                "ready": self.display_ready,
                "size": [self.config.display.width, self.config.display.height],
                "rotation": self.config.display.rotation,
            },
            "motors": {
                "driver": self.config.motors.driver,
                "armed": self.motors_armed,
                "max_duty_cycle": self.config.motors.max_duty_cycle,
            },
            "turret": {
                "driver": self.config.turret.driver,
                "pan_range": [self.config.turret.pan_min_deg, self.config.turret.pan_max_deg],
                "tilt_range": [self.config.turret.tilt_min_deg, self.config.turret.tilt_max_deg],
            },
        }
