from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

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

    def __init__(self, mode: str = "sim") -> None:
        self.mode = mode
        self.state = SimState()
        self._stop_task: asyncio.Task | None = None

    async def drive(self, command: DriveCommand) -> None:
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

    def sensors(self) -> dict:
        return {
            "mode": self.mode,
            "simulated": self.mode == "sim",
            "front_distance_cm": None,
            "imu": None,
            "battery_percent": None,
            "battery_voltage": None,
        }
