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
    driver: str = "freenove-pca9685-4wd"
    i2c_address: str = "0x40"
    left_pwm_pin: int | None = None
    left_in1_pin: int | None = None
    left_in2_pin: int | None = None
    right_pwm_pin: int | None = None
    right_in1_pin: int | None = None
    right_in2_pin: int | None = None
    pwm_frequency_hz: int = 50
    max_duty_cycle: float = Field(default=0.35, ge=0.0, le=1.0)
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


class PersonalityConfig(BaseModel):
    baseline_mood: str = "calm"
    curiosity: float = Field(default=0.55, ge=0.0, le=1.0)
    attention_seeking: float = Field(default=0.35, ge=0.0, le=1.0)
    talkativeness: float = Field(default=0.25, ge=0.0, le=1.0)
    shyness: float = Field(default=0.40, ge=0.0, le=1.0)


class QuietHoursConfig(BaseModel):
    enabled: bool = True
    start: str = "23:30"
    end: str = "09:00"


class BehaviorCooldownConfig(BaseModel):
    attention_ping_seconds: int = 1800
    curious_scan_seconds: int = 90
    idle_presence_seconds: int = 45
    react_to_sound_seconds: int = 20
    wake_response_seconds: int = 8
    request_charge_seconds: int = 900


class LifeLoopConfig(BaseModel):
    enabled: bool = True
    data_path: str = "data/rover.sqlite"
    cleo_hub_url: str = "http://127.0.0.1:8787"
    personality: PersonalityConfig = Field(default_factory=PersonalityConfig)
    quiet_hours: QuietHoursConfig = Field(default_factory=QuietHoursConfig)
    behavior_cooldowns: BehaviorCooldownConfig = Field(default_factory=BehaviorCooldownConfig)


class RoverConfig(BaseModel):
    name: str = "cleo-rover-mk1"
    profile: str = "bench-sim"
    display: DisplayConfig = Field(default_factory=DisplayConfig)
    motors: MotorConfig = Field(default_factory=MotorConfig)
    turret: TurretConfig = Field(default_factory=TurretConfig)
    sensors: SensorConfig = Field(default_factory=SensorConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    life_loop: LifeLoopConfig = Field(default_factory=LifeLoopConfig)

    def public_summary(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


def default_config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config" / "rover.default.json"


@lru_cache(maxsize=1)
def load_config() -> RoverConfig:
    path = Path(os.getenv("CLEO_ROVER_CONFIG", str(default_config_path()))).expanduser()
    data = json.loads(path.read_text(encoding="utf-8"))
    return RoverConfig.model_validate(data)
