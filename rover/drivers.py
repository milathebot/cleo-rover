from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from .config import RoverConfig
from .freenove import FreenoveHardware, drive_to_wheel_duty, freenove_hardware_map
from .models import DriveCommand, ExpressionCommand, ExpressionMode, RGBCommand, TurretCommand
from .peripherals import FreenoveSensorReader, camera_ready, rgb_ready, set_rgb


@dataclass
class SimState:
    stopped: bool = True
    last_drive: DriveCommand | None = None
    last_drive_at: float | None = None
    last_reflex_stop: dict[str, Any] | None = None
    expression: ExpressionCommand = field(
        default_factory=lambda: ExpressionCommand(mode=ExpressionMode.idle, text="Cleo", brightness=0.45)
    )
    turret: TurretCommand = field(default_factory=lambda: TurretCommand(pan_deg=0))


def should_reflex_stop(command: DriveCommand, sensors: dict[str, Any], *, threshold_cm: float) -> tuple[bool, str | None]:
    """Local body reflex: stop forward motion if the front range gets too close."""
    if command.linear <= 0:
        return False, None
    distance = sensors.get("front_distance_cm")
    if distance is None:
        return False, None
    try:
        distance_cm = float(distance)
    except (TypeError, ValueError):
        return False, None
    if distance_cm < threshold_cm:
        return True, f"front reflex stop: {distance_cm:.1f}cm below {threshold_cm:.1f}cm"
    return False, None


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
        self._watchdog_task: asyncio.Task | None = None
        self.display_ready = mode == "hardware"
        self.hardware: FreenoveHardware | None = None
        if mode == "hardware" and self.config.motors.driver == "freenove-pca9685-4wd":
            self.hardware = FreenoveHardware(self.config)
        self.hardware_ready = mode == "hardware" and self.hardware is not None
        self.motors_armed = self.hardware_ready and not self.config.safety.bench_safe_no_motors

    def _reflex_threshold_cm(self) -> float:
        return max(45.0, float(self.config.safety.front_stop_distance_cm))

    def _sensor_snapshot(self) -> dict[str, Any]:
        return FreenoveSensorReader(
            front_stop_distance_cm=self.config.safety.front_stop_distance_cm,
            adc_voltage_coefficient=self.config.sensors.adc_voltage_coefficient,
        ).snapshot()

    async def _check_forward_reflex(self, command: DriveCommand, *, source: str) -> bool:
        if not self.hardware or not self.motors_armed or command.linear <= 0:
            return False
        sensors = self._sensor_snapshot()
        reflex, reason = should_reflex_stop(command, sensors, threshold_cm=self._reflex_threshold_cm())
        if reflex:
            self.state.last_reflex_stop = {
                "reason": reason,
                "front_distance_cm": sensors.get("front_distance_cm"),
                "threshold_cm": self._reflex_threshold_cm(),
                "drive": command.model_dump(),
                "source": source,
                "time": time.time(),
            }
            await self.stop()
            return True
        return False

    def start_safety_watchdog(self) -> None:
        if self._watchdog_task and not self._watchdog_task.done():
            return

        async def watchdog() -> None:
            while True:
                await asyncio.sleep(0.03)
                command = self.state.last_drive
                if self.state.stopped or command is None or command.linear <= 0:
                    continue
                await self._check_forward_reflex(command, source="persistent_watchdog")

        self._watchdog_task = asyncio.create_task(watchdog())

    async def stop_safety_watchdog(self) -> None:
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass

    async def drive(self, command: DriveCommand) -> None:
        safe_duration = min(command.duration_ms, self.config.safety.max_drive_duration_ms)
        command = command.model_copy(update={"duration_ms": safe_duration})
        self.state.stopped = False
        self.state.last_drive = command
        self.state.last_drive_at = time.time()

        if self.hardware and self.motors_armed:
            self.hardware.drive(command)

        if self._stop_task and not self._stop_task.done():
            self._stop_task.cancel()

        async def drive_monitor() -> None:
            deadline = time.time() + command.duration_ms / 1000
            while time.time() < deadline:
                await asyncio.sleep(0.02)
                if await self._check_forward_reflex(command, source="drive_monitor"):
                    return
            await self.stop()

        self._stop_task = asyncio.create_task(drive_monitor())

    async def stop(self) -> None:
        self.state.stopped = True
        if self.hardware:
            self.hardware.stop()

    async def set_expression(self, command: ExpressionCommand) -> None:
        self.state.expression = command
        # Hardware mode: render abstract Cleo UI on Waveshare ST7789.

    async def set_turret(self, command: TurretCommand) -> None:
        self.state.turret = command
        if self.hardware:
            self.hardware.set_turret(command)

    def set_rgb(self, command: RGBCommand) -> dict[str, Any]:
        if self.mode != "hardware":
            return {"ok": True, "simulated": True, "rgb": command.model_dump()}
        return set_rgb(command.red, command.green, command.blue, brightness=command.brightness, count=self.config.rgb.count)

    def camera_ready(self) -> bool:
        return self.mode == "hardware" and camera_ready()

    def rgb_ready(self) -> bool:
        return self.mode == "hardware" and rgb_ready()

    def readiness(self) -> dict[str, bool]:
        return {
            "hardware_ready": self.hardware_ready,
            "display_ready": self.display_ready,
            "motors_armed": self.motors_armed,
            "bench_safe_no_motors": self.config.safety.bench_safe_no_motors,
        }

    def sensors(self) -> dict[str, Any]:
        live: dict[str, Any] = {
            "front_distance_cm": None,
            "front_stop_distance_cm": self.config.safety.front_stop_distance_cm,
            "line_sensors": None,
            "line_sensors_ready": False,
            "ultrasonic_ready": False,
            "adc_channels": None,
            "adc_ready": False,
            "battery_percent": None,
            "battery_voltage": None,
            "errors": {},
        }
        if self.mode == "hardware":
            live = FreenoveSensorReader(
                front_stop_distance_cm=self.config.safety.front_stop_distance_cm,
                adc_voltage_coefficient=self.config.sensors.adc_voltage_coefficient,
            ).snapshot()

        return {
            "mode": self.mode,
            "simulated": self.mode == "sim",
            "front_distance_cm": live.get("front_distance_cm"),
            "front_stop_distance_cm": self.config.safety.front_stop_distance_cm,
            "line_sensors": live.get("line_sensors"),
            "line_sensors_ready": live.get("line_sensors_ready", False),
            "ultrasonic_ready": live.get("ultrasonic_ready", False),
            "adc_channels": live.get("adc_channels"),
            "adc_ready": live.get("adc_ready", False),
            "imu": None,
            "battery_percent": live.get("battery_percent"),
            "battery_voltage": live.get("battery_voltage"),
            "camera": {
                "driver": self.config.camera.driver,
                "ready": self.camera_ready(),
                "capture_dir": self.config.camera.capture_dir,
                "size": [self.config.camera.width, self.config.camera.height],
            },
            "rgb": {
                "driver": self.config.rgb.driver,
                "ready": self.rgb_ready(),
                "count": self.config.rgb.count,
                "spi": [self.config.rgb.spi_bus, self.config.rgb.spi_device],
                "color_order": self.config.rgb.color_order,
                "brightness": self.config.rgb.brightness,
            },
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
                "last_wheel_duty": drive_to_wheel_duty(
                    self.state.last_drive, self.config.motors.max_duty_cycle
                ).as_dict()
                if self.state.last_drive
                else None,
                "last_reflex_stop": self.state.last_reflex_stop,
            },
            "freenove_map": freenove_hardware_map(self.config),
            "turret": {
                "driver": self.config.turret.driver,
                "pan_range": [self.config.turret.pan_min_deg, self.config.turret.pan_max_deg],
                "tilt_range": [self.config.turret.tilt_min_deg, self.config.turret.tilt_max_deg],
            },
            "errors": live.get("errors", {}),
        }
