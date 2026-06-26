from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from .config import RoverConfig
from .display import NullDisplay, ST7789Display
from .freenove import FreenoveHardware, drive_to_wheel_duty, freenove_hardware_map
from .models import DriveCommand, ExpressionCommand, ExpressionMode, RGBCommand, TurretCommand
from .peripherals import FreenoveSensorReader, camera_ready, rgb_ready, set_rgb
from .renderer import render_expression


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


def should_panned_forward_stop(command: DriveCommand, pan_deg: Any, *, guard_deg: float = 5.0) -> tuple[bool, str | None]:
    """Bearing guard: refuse forward motion while the turret sonar is panned away.

    The forward ultrasonic reflex trusts the *live* range reading, but the single
    sonar is turret-mounted. If the turret is panned to a side (e.g. mid-sweep)
    and returns a clear *side* reading, that reading would otherwise satisfy the
    reflex and let Pip drive forward into a wall the sonar is not pointed at. So
    when driving forward, require the turret to be within +/- guard_deg of centre;
    fail CLOSED if the pan angle is unknown.
    """
    if command.linear <= 0:
        return False, None
    try:
        pan = abs(float(pan_deg))
    except (TypeError, ValueError):
        return True, "forward drive with unknown turret bearing; failing closed"
    if pan > guard_deg:
        return True, f"forward drive while turret panned {pan:.0f}deg (> {guard_deg:.0f}deg); sonar not looking ahead"
    return False, None


def should_cliff_stop(sensors: dict[str, Any], *, enabled: bool, drop_value: int) -> tuple[bool, str | None]:
    """Floor-drop reflex from the downward IR line sensors.

    Requires ALL line sensors to read the "no reflection / no floor" value, so a
    single dark line under one sensor (line-following) is not mistaken for an
    edge. Polarity is hardware-specific and configured via safety.line_drop_value;
    disabled by default until verified on the robot.
    """
    if not enabled:
        return False, None
    line = sensors.get("line_sensors")
    if not isinstance(line, dict) or not line:
        return False, None
    try:
        all_drop = all(int(value) == int(drop_value) for value in line.values())
    except (TypeError, ValueError):
        return False, None
    if all_drop:
        return True, f"cliff/floor-drop reflex: all line sensors read no-floor ({drop_value})"
    return False, None


def resolve_front_range(
    fd: float | None,
    last_good_cm: float | None,
    last_good_at: float,
    now: float,
    hold_s: float,
) -> tuple[float | None, bool, float | None, float]:
    """Resolve the forward range for the reflex under HC-SR04 motor-noise dropouts.

    Under driving, the ultrasonic intermittently returns garbage (dropped to None),
    which must NOT instantly blind the reflex (else Pip stops on a clear path). A
    valid read passes through and refreshes the cache; a None reuses the last good
    read while it is younger than hold_s; only a None with a stale/absent cache fails
    CLOSED (blind). Pure so the policy is unit-tested.

    Returns (range_cm_or_None, fail_closed, new_last_good_cm, new_last_good_at).
    """
    if fd is not None:
        return fd, False, float(fd), now
    if last_good_cm is not None and (now - last_good_at) <= hold_s:
        return last_good_cm, False, last_good_cm, last_good_at
    return None, True, last_good_cm, last_good_at


def should_bump_stop(sensors: dict[str, Any], *, enabled: bool) -> tuple[bool, str | None]:
    """Contact reflex from the front bump switches (value 1 == pressed)."""
    if not enabled:
        return False, None
    bumpers = sensors.get("bumpers")
    if not isinstance(bumpers, dict) or not bumpers:
        return False, None
    try:
        hit = [name for name, value in bumpers.items() if int(value) == 1]
    except (TypeError, ValueError):
        return False, None
    if hit:
        return True, f"bump reflex: bumper(s) {hit} triggered"
    return False, None


def display_spi_pins(bus: int, device: int, cs_pin: int | None = None) -> dict[str, int | None]:
    if bus == 1:
        chip_selects = {0: 18, 1: 17, 2: 16}
        return {"din_mosi": 20, "clk_sclk": 21, "cs": cs_pin if cs_pin is not None else chip_selects.get(device)}
    chip_selects = {0: 8, 1: 7}
    return {"din_mosi": 10, "clk_sclk": 11, "cs": cs_pin if cs_pin is not None else chip_selects.get(device)}


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
        self.display = NullDisplay()
        if mode == "hardware" and self.config.display.type not in {"none", "disabled", "off"}:
            self.display = ST7789Display(self.config.display)
        self.display_ready = self.display.ready
        self.hardware: FreenoveHardware | None = None
        if mode == "hardware" and self.config.motors.driver == "freenove-pca9685-4wd":
            self.hardware = FreenoveHardware(self.config)
        self.hardware_ready = mode == "hardware" and self.hardware is not None
        self.motors_armed = self.hardware_ready and not self.config.safety.bench_safe_no_motors
        # Freshness cursor for event-based reflex consumption (see consume_reflex_stop).
        self._last_reflex_consumed_at: float = 0.0
        # Fail-closed counter: stop forward motion if the front range is unknown
        # for several consecutive checks (tolerates single ultrasonic dropouts,
        # which are common right after the turret moves, without a blind window).
        self._consecutive_none_range: int = 0
        self._max_none_range: int = 3
        # Last valid forward range + when, so brief HC-SR04 dropouts under motor noise
        # reuse a recent good reading instead of instantly blinding the reflex.
        self._last_good_front_cm: float | None = None
        self._last_good_front_at: float = 0.0
        self._range_hold_s: float = 0.25

    def _reflex_threshold_cm(self) -> float:
        # Configurable hard emergency floor instead of the old hardcoded max(45,...)
        # that made doorway approach impossible. front_stop still acts as a lower bound.
        return max(
            float(self.config.safety.reflex_hard_cm),
            float(self.config.safety.front_stop_distance_cm),
        )

    def consume_reflex_stop(self) -> dict[str, Any] | None:
        """Return the latest reflex stop only if it is *new* since the last consume.

        `state.last_reflex_stop` is retained telemetry (read by /sensors and the
        brain). Navigation loops must react to a fresh reflex *event* exactly once;
        previously they tested the truthy retained dict every cycle, so one real
        reflex was re-counted forever and forced spurious recovery turns. This
        consumes by timestamp: it hands back the reflex once, then stays quiet
        until a newer reflex fires, without erasing the telemetry.
        """
        reflex = self.state.last_reflex_stop
        if not reflex:
            return None
        stamp = float(reflex.get("time") or 0.0)
        if stamp <= self._last_reflex_consumed_at:
            return None
        self._last_reflex_consumed_at = stamp
        return reflex

    def _sensor_snapshot(self) -> dict[str, Any]:
        return FreenoveSensorReader(
            front_stop_distance_cm=self.config.safety.front_stop_distance_cm,
            adc_voltage_coefficient=self.config.sensors.adc_voltage_coefficient,
            bumper_left_pin=self.config.sensors.bumper_left_pin,
            bumper_right_pin=self.config.sensors.bumper_right_pin,
            pcb_version=self.config.sensors.pcb_version,
        ).snapshot()

    def front_distance_median(self, samples: int | None = None) -> float | None:
        """Deliberate median range read for scans (noise-resistant). None in sim."""
        if self.mode != "hardware":
            return None
        count = samples if samples is not None else int(getattr(self.config.odometry, "range_samples", 5))
        return FreenoveSensorReader(
            front_stop_distance_cm=self.config.safety.front_stop_distance_cm,
            adc_voltage_coefficient=self.config.sensors.adc_voltage_coefficient,
            pcb_version=self.config.sensors.pcb_version,
        ).read_front_distance_cm(samples=count)

    async def _check_forward_reflex(self, command: DriveCommand, *, source: str) -> bool:
        if not self.hardware or not self.motors_armed or command.linear <= 0:
            return False
        # Bearing guard FIRST: a forward pulse while the turret is panned away is a
        # stop regardless of the (side-pointed) distance reading. This closes a
        # real hole -- the reflex otherwise trusts a clear side reading as "ahead".
        panned, panned_reason = should_panned_forward_stop(
            command, self.state.turret.pan_deg, guard_deg=float(self.config.safety.forward_cone_guard_deg)
        )
        if panned:
            self.state.last_reflex_stop = {
                "reason": panned_reason,
                "kind": "panned_forward",
                "pan_deg": getattr(self.state.turret, "pan_deg", None),
                "threshold_cm": self._reflex_threshold_cm(),
                "drive": command.model_dump(),
                "source": source,
                "time": time.time(),
            }
            await self.stop()
            return True
        sensors = self._sensor_snapshot()
        # Resolve the forward range tolerantly: the HC-SR04 emits intermittent garbage
        # (dropped to None) under motor noise, which must NOT instantly blind the reflex
        # (else Pip stops dead on a clear path mid-drive). Reuse a recent good reading
        # through brief dropouts; only fail CLOSED when blind longer than _range_hold_s.
        now = time.time()
        resolved, blind, self._last_good_front_cm, self._last_good_front_at = resolve_front_range(
            sensors.get("front_distance_cm"), self._last_good_front_cm, self._last_good_front_at, now, self._range_hold_s
        )
        if blind:
            blind_ms = (now - self._last_good_front_at) * 1000 if self._last_good_front_cm is not None else -1.0
            self.state.last_reflex_stop = {
                "reason": (f"front range blind for {blind_ms:.0f}ms (> {self._range_hold_s*1000:.0f}ms); failing closed"
                           if blind_ms >= 0 else "front range never read; failing closed"),
                "kind": "range_unknown",
                "front_distance_cm": None,
                "threshold_cm": self._reflex_threshold_cm(),
                "drive": command.model_dump(),
                "source": source,
                "time": now,
            }
            await self.stop()
            return True
        sensors["front_distance_cm"] = resolved
        reflex, reason = should_reflex_stop(command, sensors, threshold_cm=self._reflex_threshold_cm())
        kind = "ultrasonic"
        if not reflex:
            cliff, cliff_reason = should_cliff_stop(
                sensors, enabled=self.config.safety.cliff_reflex_enabled, drop_value=self.config.safety.line_drop_value
            )
            if cliff:
                reflex, reason, kind = True, cliff_reason, "cliff"
        if not reflex:
            bump, bump_reason = should_bump_stop(sensors, enabled=self.config.safety.bumper_reflex_enabled)
            if bump:
                reflex, reason, kind = True, bump_reason, "bumper"
        if reflex:
            self.state.last_reflex_stop = {
                "reason": reason,
                "kind": kind,
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

        slack_s = float(self.config.safety.motion_deadline_slack_ms) / 1000.0

        async def watchdog() -> None:
            while True:
                await asyncio.sleep(0.03)
                command = self.state.last_drive
                if self.state.stopped or command is None:
                    continue
                # Liveness backstop: if a drive should have ended (its pulse + slack)
                # but the rover is still marked moving, force-stop. Catches a stalled
                # or cancelled drive_monitor so motion can never run away.
                if self.state.last_drive_at is not None and time.time() > self.state.last_drive_at + command.duration_ms / 1000.0 + slack_s:
                    await self.stop()
                    continue
                if command.linear <= 0:
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
        self.display.close()

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
        if self.mode == "hardware":
            result = self.display.show(render_expression(command).image)
            self.display_ready = result.ready

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
            "bumpers": None,
            "bumpers_ready": False,
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
                bumper_left_pin=self.config.sensors.bumper_left_pin,
                bumper_right_pin=self.config.sensors.bumper_right_pin,
                pcb_version=self.config.sensors.pcb_version,
            ).snapshot()

        return {
            "mode": self.mode,
            "simulated": self.mode == "sim",
            "front_distance_cm": live.get("front_distance_cm"),
            "front_stop_distance_cm": self.config.safety.front_stop_distance_cm,
            "line_sensors": live.get("line_sensors"),
            "line_sensors_ready": live.get("line_sensors_ready", False),
            "bumpers": live.get("bumpers"),
            "bumpers_ready": live.get("bumpers_ready", False),
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
                "spi": [self.config.display.spi_bus, self.config.display.spi_device],
                "pins": display_spi_pins(self.config.display.spi_bus, self.config.display.spi_device, self.config.display.cs_pin) | {
                    "dc": self.config.display.dc_pin,
                    "rst": self.config.display.reset_pin,
                    "bl": self.config.display.backlight_pin,
                },
                "last_error": getattr(self.display, "last_error", None),
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
