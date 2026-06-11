from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class DisplayConfig(BaseModel):
    type: str = "waveshare-st7789"
    width: int = 240
    height: int = 320
    rotation: int = 180
    spi_bus: int = 0
    spi_device: int = 0
    dc_pin: int | None = None
    reset_pin: int | None = None
    backlight_pin: int | None = None


class MotorConfig(BaseModel):
    driver: str = "tb6612fng"
    left_pwm_pin: int | None = None
    left_in1_pin: int | None = None
    left_in2_pin: int | None = None
    right_pwm_pin: int | None = None
    right_in1_pin: int | None = None
    right_in2_pin: int | None = None
    pwm_frequency_hz: int = 1000
    max_duty_cycle: float = Field(default=0.55, ge=0.0, le=1.0)
    invert_left: bool = False
    invert_right: bool = False


class TurretConfig(BaseModel):
    driver: str = "pca9685"
    i2c_address: str = "0x40"
    pan_channel: int = 0
    tilt_channel: int = 1
    pan_min_deg: float = -70
    pan_max_deg: float = 70
    tilt_min_deg: float = -35
    tilt_max_deg: float = 45


class SensorConfig(BaseModel):
    front_tof: str = "vl53l1x"
    imu: str = "bno055_or_mpu6050"
    bumper_left_pin: int | None = None
    bumper_right_pin: int | None = None
    battery_monitor: str = "power-bank-unknown"


class SafetyConfig(BaseModel):
    max_drive_duration_ms: int = 2000
    default_drive_duration_ms: int = 250
    heartbeat_timeout_ms: int = 1500
    front_stop_distance_cm: float = 18
    bench_safe_no_motors: bool = True


class AudioConfig(BaseModel):
    mic: str = "usb"
    speaker_amp: str = "max98357a-i2s"


class RoverConfig(BaseModel):
    name: str = "cleo-rover-mk1"
    profile: str = "bench-sim"
    display: DisplayConfig = Field(default_factory=DisplayConfig)
    motors: MotorConfig = Field(default_factory=MotorConfig)
    turret: TurretConfig = Field(default_factory=TurretConfig)
    sensors: SensorConfig = Field(default_factory=SensorConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)

    def public_summary(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


def default_config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config" / "rover.default.json"


@lru_cache(maxsize=1)
def load_config() -> RoverConfig:
    path = Path(os.getenv("CLEO_ROVER_CONFIG", str(default_config_path()))).expanduser()
    data = json.loads(path.read_text(encoding="utf-8"))
    return RoverConfig.model_validate(data)
