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
    spi_bus: int = 1
    spi_device: int = 0
    cs_pin: int | None = 6
    dc_pin: int | None = 25
    reset_pin: int | None = 5
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
    pan_channel: int = 8
    tilt_channel: int = 9
    pan_min_deg: float = -70
    pan_max_deg: float = 70
    tilt_min_deg: float = -35
    tilt_max_deg: float = 45


class SensorConfig(BaseModel):
    front_tof: str = "hc-sr04"
    imu: str = "bno055_or_mpu6050"
    bumper_left_pin: int | None = None
    bumper_right_pin: int | None = None
    battery_monitor: str = "ads7830-channel-2"
    adc_i2c_address: str = "0x48"
    adc_voltage_coefficient: float = 5.2
    line_left_pin: int = 14
    line_center_pin: int = 15
    line_right_pin: int = 23
    ultrasonic_trigger_pin: int = 27
    ultrasonic_echo_pin: int = 22


class CameraConfig(BaseModel):
    driver: str = "rpicam-still"
    width: int = 1296
    height: int = 972
    capture_dir: str = "captures"


class RGBConfig(BaseModel):
    driver: str = "spi-ws2812"
    count: int = 8
    spi_bus: int = 0
    spi_device: int = 0
    color_order: str = "GRB"
    brightness: int = Field(default=24, ge=0, le=255)


class SafetyConfig(BaseModel):
    max_drive_duration_ms: int = 2000
    default_drive_duration_ms: int = 250
    heartbeat_timeout_ms: int = 1500
    front_stop_distance_cm: float = 18
    # Hard emergency reflex floor (cm). The Pi-local forward reflex stops below
    # max(reflex_hard_cm, front_stop_distance_cm). Previously this was hardcoded
    # to max(45, ...), which made approaching a doorway (closing inside 45cm)
    # structurally impossible. Configurable + scoped per profile now.
    reflex_hard_cm: float = 30.0
    # Cliff (downward IR) + bumper reflexes. OFF by default because the IR polarity
    # and bumper wiring must be verified on the physical robot first; flip these on
    # in the floor-cautious profile once `line_drop_value` matches your sensors.
    cliff_reflex_enabled: bool = False
    bumper_reflex_enabled: bool = False
    # Digital line-sensor value that means "no reflection / no floor" (edge/drop).
    # Polarity is hardware-specific; verify with `cleo-rover sensors` over a real edge.
    line_drop_value: int = 1
    bench_safe_no_motors: bool = True


class AudioConfig(BaseModel):
    mic: str = "usb"
    speaker_amp: str = "max98357a-i2s"


class VisionConfig(BaseModel):
    """On-Pi camera perception. Advisory only; never relaxes the reflexes.

    With the optional `vision` extra installed and a model file present, a
    lightweight INT8 detector runs on captures; otherwise a low-confidence
    placeholder keeps the perception->brain pipeline alive.
    """

    enabled: bool = True
    model_path: str | None = None
    labelmap_path: str | None = None
    conf_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    hazard_max_age_s: float = Field(default=120.0, ge=5.0, le=3600.0)


class VoiceConfig(BaseModel):
    """Offline-first voice input. Wake word + STT run on the Pi; talking never
    enables movement (movement stays gated by grants + armed motors)."""

    enabled: bool = True
    wakeword: str = "hey pip"
    stt_backend: str = "auto"  # auto | whisper_cpp | vosk
    stt_model_path: str | None = None
    mic_device: str | None = None  # ALSA card; falls back to $ALSA_CARD
    utterance_seconds: float = Field(default=4.0, ge=1.0, le=15.0)
    sample_rate: int = Field(default=16000, ge=8000, le=48000)


class MindConfig(BaseModel):
    """The deliberative LLM mind. Enhancement over local autonomy; the API
    endpoint/key/model come from env (HERMES_*/MIND_*), never committed."""

    enabled: bool = True
    max_tokens: int = Field(default=220, ge=16, le=1024)
    timeout_s: float = Field(default=30.0, ge=1.0, le=120.0)


class OdometryConfig(BaseModel):
    """Open-loop motion-model coefficients (no encoders/IMU; calibrated guesses).

    Calibrate on hardware with a tape measure + UMBmark square; defaults reproduce
    the existing move_step feel so behavior is unchanged until measured.
    """

    cm_s_per_duty: float = 33.0
    duty_deadband: float = Field(default=0.08, ge=0.0, le=0.5)
    deg_s_per_turn_duty: float = 200.0
    turn_deadband: float = Field(default=0.10, ge=0.0, le=0.5)
    dead_time_ms: float = Field(default=60.0, ge=0.0, le=400.0)
    distance_sigma_frac: float = Field(default=0.30, ge=0.0, le=1.0)
    heading_sigma_frac: float = Field(default=0.45, ge=0.0, le=1.0)
    range_samples: int = Field(default=5, ge=1, le=15)


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
    # Internal heartbeat: how often Pip refreshes energy from battery, injects an
    # idle tick (mood/attention/curiosity decay), and evolves on its own without
    # an external poker. 0 disables. Only auto-starts on hardware.
    heartbeat_seconds: int = Field(default=20, ge=0, le=600)
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
    camera: CameraConfig = Field(default_factory=CameraConfig)
    rgb: RGBConfig = Field(default_factory=RGBConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    odometry: OdometryConfig = Field(default_factory=OdometryConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)
    mind: MindConfig = Field(default_factory=MindConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
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
