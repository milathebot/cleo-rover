from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

from .config import RoverConfig
from .models import DriveCommand, TurretCommand

PCA9685_ADDRESS = 0x40
PCA9685_PWM_FREQUENCY_HZ = 50
PCA9685_MAX_DUTY = 4095

# Derived from Freenove FNK0043 Code/Server/motor.py, commit a49db4b,
# then corrected against Noot's physical Cleo Rover bench test on 2026-06-17.
# We keep this as a clean-room map/driver inside Cleo Rover rather than running
# Freenove's TCP/app stack.
# Tuple order is (reverse_channel, forward_channel) from the rover's physical
# perspective. Positive Cleo drive duty should make the wheel roll forward.
FREENOVE_WHEEL_CHANNELS: dict[str, tuple[int, int]] = {
    "left_upper": (1, 0),
    "left_lower": (2, 3),
    "right_upper": (7, 6),
    "right_lower": (5, 4),
}

FREENOVE_DEFAULT_SERVO_CHANNELS: dict[str, int] = {
    "pan": 8,   # Freenove Servo0
    "tilt": 9,  # Freenove Servo1
}

FREENOVE_LINE_SENSOR_PINS: dict[str, int] = {
    "left": 14,
    "center": 15,
    "right": 23,
}

FREENOVE_ULTRASONIC_PINS: dict[str, int] = {
    "trigger": 27,
    "echo": 22,
}


@dataclass(frozen=True)
class WheelDuty:
    left_upper: int
    left_lower: int
    right_upper: int
    right_lower: int

    def as_dict(self) -> dict[str, int]:
        return {
            "left_upper": self.left_upper,
            "left_lower": self.left_lower,
            "right_upper": self.right_upper,
            "right_lower": self.right_lower,
        }


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def drive_to_wheel_duty(command: DriveCommand, max_duty_cycle: float = 0.55) -> WheelDuty:
    """Convert normalized linear/turn command to Freenove 4-wheel duties.

    Positive linear means forward. Positive turn means turn right. The output
    mirrors Freenove's ordinary-wheel examples: forward is all wheels positive,
    left turn is left wheels negative/right wheels positive, and right turn is
    the inverse. Duties are capped conservatively by config.
    """

    max_pwm = int(PCA9685_MAX_DUTY * clamp(max_duty_cycle, 0.0, 1.0))
    left = clamp(command.linear + command.turn, -1.0, 1.0)
    right = clamp(command.linear - command.turn, -1.0, 1.0)
    return WheelDuty(
        left_upper=int(left * max_pwm),
        left_lower=int(left * max_pwm),
        right_upper=int(right * max_pwm),
        right_lower=int(right * max_pwm),
    )


class PCA9685Bus:
    """Tiny PCA9685 wrapper for the Freenove car board.

    Imports SMBus lazily so the Cleo Rover service still runs and tests on a
    laptop/WSL without Raspberry Pi I2C packages installed.
    """

    MODE1 = 0x00
    PRESCALE = 0xFE
    LED0_ON_L = 0x06

    def __init__(self, address: int = PCA9685_ADDRESS, bus_id: int = 1) -> None:
        try:
            from smbus2 import SMBus  # type: ignore
        except ImportError:  # pragma: no cover - only on Pi images with apt smbus
            from smbus import SMBus  # type: ignore

        self.address = address
        self.bus = SMBus(bus_id)
        self.write(self.MODE1, 0x00)

    def write(self, register: int, value: int) -> None:
        self.bus.write_byte_data(self.address, register, value)

    def read(self, register: int) -> int:
        return int(self.bus.read_byte_data(self.address, register))

    def set_pwm_freq(self, freq_hz: float) -> None:
        prescale = math.floor(25_000_000.0 / 4096.0 / float(freq_hz) - 1.0 + 0.5)
        oldmode = self.read(self.MODE1)
        self.write(self.MODE1, (oldmode & 0x7F) | 0x10)
        self.write(self.PRESCALE, int(prescale))
        self.write(self.MODE1, oldmode)
        self.write(self.MODE1, oldmode | 0x80)

    def set_pwm(self, channel: int, on: int, off: int) -> None:
        base = self.LED0_ON_L + 4 * channel
        self.write(base, on & 0xFF)
        self.write(base + 1, on >> 8)
        self.write(base + 2, off & 0xFF)
        self.write(base + 3, off >> 8)

    def set_motor_pwm(self, channel: int, duty: int) -> None:
        self.set_pwm(channel, 0, int(clamp(duty, 0, PCA9685_MAX_DUTY)))

    def set_servo_pulse_us(self, channel: int, pulse_us: float) -> None:
        off = int(pulse_us * 4096 / 20_000)
        self.set_pwm(channel, 0, off)

    def close(self) -> None:
        self.bus.close()


class FreenoveHardware:
    """Cleo-native hardware driver for the Freenove FNK0043 board."""

    def __init__(self, config: RoverConfig) -> None:
        self.config = config
        self.pwm = PCA9685Bus(address=int(config.motors.i2c_address, 16))
        self.pwm.set_pwm_freq(config.motors.pwm_frequency_hz)
        self.last_wheel_duty = WheelDuty(0, 0, 0, 0)
        self.stop()

    def _set_wheel(self, wheel: str, duty: int) -> None:
        reverse_channel, forward_channel = FREENOVE_WHEEL_CHANNELS[wheel]
        duty = int(clamp(duty, -PCA9685_MAX_DUTY, PCA9685_MAX_DUTY))
        if duty > 0:
            self.pwm.set_motor_pwm(reverse_channel, 0)
            self.pwm.set_motor_pwm(forward_channel, duty)
        elif duty < 0:
            self.pwm.set_motor_pwm(forward_channel, 0)
            self.pwm.set_motor_pwm(reverse_channel, abs(duty))
        else:
            # Freenove uses both channels high as brake/stop for a wheel.
            self.pwm.set_motor_pwm(reverse_channel, PCA9685_MAX_DUTY)
            self.pwm.set_motor_pwm(forward_channel, PCA9685_MAX_DUTY)

    def _apply_wheel_duty(self, duty: WheelDuty) -> None:
        for wheel, value in duty.as_dict().items():
            self._set_wheel(wheel, value)
        self.last_wheel_duty = duty

    def _ramp_to(self, target: WheelDuty, *, ramp_ms: int = 90, steps: int = 5) -> WheelDuty:
        """Blend wheel PWM toward target instead of snapping.

        Freenove's reference code sends target PWM immediately, which is fine
        for manual RC control but makes Pip's short autonomous movements feel
        jerky. A tiny open-loop ramp keeps the verified channel map and reduces
        lurch without adding closed-loop wheel odometry.
        """
        start = self.last_wheel_duty
        steps = max(1, int(steps))
        delay = max(0.0, ramp_ms / 1000.0 / steps)
        for idx in range(1, steps + 1):
            t = idx / steps
            duty = WheelDuty(
                left_upper=int(start.left_upper + (target.left_upper - start.left_upper) * t),
                left_lower=int(start.left_lower + (target.left_lower - start.left_lower) * t),
                right_upper=int(start.right_upper + (target.right_upper - start.right_upper) * t),
                right_lower=int(start.right_lower + (target.right_lower - start.right_lower) * t),
            )
            self._apply_wheel_duty(duty)
            if delay:
                time.sleep(delay)
        return target

    def drive(self, command: DriveCommand) -> WheelDuty:
        duty = drive_to_wheel_duty(command, self.config.motors.max_duty_cycle)
        return self._ramp_to(duty, ramp_ms=90, steps=5)

    def stop(self) -> None:
        zero = self._ramp_to(WheelDuty(0, 0, 0, 0), ramp_ms=70, steps=4)
        for wheel in zero.as_dict():
            self._set_wheel(wheel, 0)
        self.last_wheel_duty = zero

    def set_turret(self, command: TurretCommand) -> None:
        # Map -80..80 user pan to a conservative servo angle around center.
        angle = int(clamp(90 + command.pan_deg, 10, 170))
        pulse = 500 + int(angle / 0.09)
        self.pwm.set_servo_pulse_us(self.config.turret.pan_channel, pulse)

    def close(self) -> None:
        self.stop()
        self.pwm.close()


def freenove_hardware_map(config: RoverConfig) -> dict[str, Any]:
    return {
        "source": "Freenove FNK0043 codebase commit a49db4b, mapped into Cleo Rover native driver",
        "runtime": "custom Cleo Rover service; Freenove app/TCP code is not used",
        "pca9685": {
            "i2c_address": config.motors.i2c_address,
            "frequency_hz": config.motors.pwm_frequency_hz,
            "max_pwm": PCA9685_MAX_DUTY,
        },
        "motors": {
            "driver": config.motors.driver,
            "channels": {name: list(channels) for name, channels in FREENOVE_WHEEL_CHANNELS.items()},
            "max_duty_cycle": config.motors.max_duty_cycle,
        },
        "servos": {
            "pan": config.turret.pan_channel,
            "tilt": config.turret.tilt_channel,
        },
        "line_sensors_bcm": FREENOVE_LINE_SENSOR_PINS,
        "ultrasonic_bcm": FREENOVE_ULTRASONIC_PINS,
    }
