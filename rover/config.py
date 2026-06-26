from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator


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
    # A 4WD scrub-turn in place needs real torque; tiny turn commands stall (buzz). When
    # >0, a pure in-place turn (|linear|~0) is boosted to at least this magnitude so a
    # commanded rotation actually rotates. Arc-steering while moving is untouched.
    # Per-robot (measured on hardware).
    min_inplace_turn: float = Field(default=0.0, ge=0.0, le=1.0)
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
    # Mechanical pan-center trim (degrees), added to the PHYSICAL pulse only -- NOT to
    # the reported pan_deg -- so a logical 0deg points dead ahead. Per-robot; measured
    # on hardware (calibration step 6). Negative = trim left.
    pan_trim_deg: float = 0.0
    # Pan slew: ease the servo to a target in steps of <=pan_slew_deg (with a short
    # settle each step) instead of snapping. A hard wide-angle jump slams the servo
    # and vibrates the pan-mount screws loose. 0 = snap (old behavior). Mirrors the
    # wheel _ramp_to that smoothed body motion.
    pan_slew_deg: float = Field(default=12.0, ge=0.0, le=90.0)
    pan_slew_settle_ms: float = Field(default=15.0, ge=0.0, le=200.0)


class SensorConfig(BaseModel):
    front_tof: str = "hc-sr04"
    imu: str = "bno055_or_mpu6050"
    bumper_left_pin: int | None = None
    bumper_right_pin: int | None = None
    battery_monitor: str = "ads7830-channel-2"
    adc_i2c_address: str = "0x48"
    # FNK0043 PCB revision selects a PAIRED ADC (coeff, divider-multiplier): v2 =
    # (5.2, x2), v1 = (3.3, x3). A wrong version silently misreads the battery by
    # ~33%. Verify via silkscreen / params.json (a multimeter cross-check is in the
    # calibration checklist). adc_voltage_coefficient is kept for back-compat but
    # the battery path derives both from pcb_version so they can't drift apart.
    pcb_version: int = Field(default=2, ge=1, le=2)
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
    # Liveness backstop: the persistent watchdog force-stops a drive that should
    # have ended (its pulse + this slack) but didn't (e.g. a stalled drive monitor).
    motion_deadline_slack_ms: int = Field(default=400, ge=50, le=3000)
    # How long a recent good front-range read is reused when the HC-SR04 drops out
    # (common right after a turret move, under motor noise). Below this the reflex
    # tolerates the dropout; beyond it (with no median re-read) it fails CLOSED.
    # Raise toward 350ms if scans cause stutter-stops; lower for snappier blinding.
    range_hold_ms: int = Field(default=250, ge=50, le=1500)
    # Thermal back-off (fanless Pi running autonomy for hours). cpu_temp from doctor.
    thermal_warn_c: float = Field(default=75.0, ge=50.0, le=90.0)
    thermal_hard_c: float = Field(default=82.0, ge=55.0, le=95.0)
    # Cliff (downward IR) + bumper reflexes. OFF by default because the IR polarity
    # and bumper wiring must be verified on the physical robot first; flip these on
    # in the floor-cautious profile once `line_drop_value` matches your sensors.
    cliff_reflex_enabled: bool = False
    bumper_reflex_enabled: bool = False
    # Digital line-sensor value that means "no reflection / no floor" (edge/drop).
    # Polarity is hardware-specific; verify with `cleo-rover sensors` over a real edge.
    line_drop_value: int = 1
    # Bearing guard: forward motion is refused (reflex stop) while the turret sonar
    # is panned more than this off centre, so a clear *side* reading can never be
    # mistaken for a clear path ahead. Underpins safe continuous motion.
    forward_cone_guard_deg: float = Field(default=5.0, ge=1.0, le=45.0)
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


class NavConfig(BaseModel):
    """Tier 3 mapping/navigation backbone: a body-frame rolling occupancy grid,
    VFH+ steering, wall-following, optical-flow stall confirmation, a topological
    place graph, and memory consolidation.

    All of this is ADVISORY -- it informs *where/how* to move; it never relaxes
    the Pi-local reflex/cliff/bumper stops. Behaviour-changing flags ship OFF so
    the branch merges 'dark' and is enabled per the hardware handover after light
    supervised testing. The read-only planning endpoints (/nav/plan, /topo/*,
    /memory/*) work regardless of the flags.
    """

    # --- behaviour flags (default OFF; flip after supervised testing) ---
    use_vfh_steering: bool = False  # reactive-explore picks turns via VFH+ instead of widest-gap
    mapping_enabled: bool = False  # accumulate the persistent occupancy grid across moves
    wall_follow_enabled: bool = False  # allow the wall-follow task to drive
    # Room-to-room roaming: when on, autonomous movement is NOT restricted to
    # `approved_zones` -- Pip may wander through doorways into other rooms and the
    # arbiter may navigate to any named place it has learned. Physical safety is the
    # closed baby gate at the stairs + the downward cliff reflex (both authoritative);
    # this only relaxes the soft zone-permission gate, never a reflex. OFF by default.
    cross_zone_roam_enabled: bool = False
    flow_stall_enabled: bool = False  # consult camera optical flow to confirm stalls (needs cv2)
    topo_enabled: bool = True  # build/serve the topological place graph (no movement)
    consolidation_enabled: bool = True  # distill episodic memory into facts on heartbeat
    consolidation_interval_heartbeats: int = Field(default=30, ge=1, le=1000)
    consolidation_promote_n: int = Field(default=3, ge=1, le=50)

    # --- rolling occupancy grid (sonar inverse sensor model) ---
    grid_cell_cm: float = Field(default=10.0, ge=2.0, le=50.0)
    grid_size_cells: int = Field(default=41, ge=11, le=121)
    grid_l_occ: float = 0.90
    grid_l_free: float = -0.50
    grid_l_clamp: float = 3.5
    grid_occ_threshold: float = 0.85
    grid_free_threshold: float = -0.40
    grid_beta_free_deg: float = Field(default=28.0, ge=5.0, le=60.0)
    grid_beta_occ_deg: float = Field(default=12.0, ge=2.0, le=40.0)
    grid_alpha_cm: float = Field(default=12.0, ge=2.0, le=40.0)
    grid_z_max_cm: float = Field(default=300.0, ge=50.0, le=500.0)

    # --- VFH+ steering ---
    vfh_fov_deg: float = Field(default=90.0, ge=30.0, le=180.0)
    vfh_sector_deg: float = Field(default=12.0, ge=3.0, le=30.0)
    vfh_a: float = 4.0
    vfh_d_max_cm: float = Field(default=180.0, ge=40.0, le=400.0)
    vfh_tau_low: float = 1.5
    vfh_tau_high: float = 3.0
    vfh_s_max_sectors: int = Field(default=6, ge=2, le=20)
    vfh_robot_radius_cm: float = Field(default=12.0, ge=3.0, le=40.0)
    vfh_safety_cm: float = Field(default=12.0, ge=0.0, le=40.0)
    vfh_mu_target: float = 5.0
    vfh_mu_current: float = 2.0
    vfh_mu_previous: float = 2.0

    # --- wall following ---
    wall_setpoint_cm: float = Field(default=25.0, ge=8.0, le=80.0)
    wall_kp: float = 2.0
    wall_kd: float = 8.0
    wall_deadband_cm: float = Field(default=3.0, ge=0.5, le=15.0)
    wall_max_turn: float = Field(default=0.5, ge=0.1, le=1.0)
    wall_base_linear: float = Field(default=0.18, ge=0.0, le=0.5)
    wall_inside_corner_front_cm: float = Field(default=35.0, ge=10.0, le=120.0)
    wall_outside_corner_jump_cm: float = Field(default=40.0, ge=10.0, le=150.0)

    # --- frontier-driven exploration + costmap inflation ---
    # When mapping + VFH steering are on, patrol heads toward the nearest open
    # frontier (edge of the unknown) instead of wandering. Obstacles are inflated by
    # inflation_radius_cells so frontiers hugging a wall aren't chosen (clearance).
    inflation_radius_cells: int = Field(default=1, ge=0, le=5)
    frontier_min_cluster: int = Field(default=4, ge=1, le=50)
    frontier_max_abs_bearing_deg: float = Field(default=120.0, ge=30.0, le=180.0)

    # --- topological place graph ---
    topo_sonar_thresh: float = Field(default=0.6, ge=0.1, le=1.0)
    topo_hist_thresh: float = Field(default=0.8, ge=0.1, le=1.0)
    topo_min_votes: int = Field(default=2, ge=1, le=3)

    # --- optical-flow stall confirmation ---
    flow_move_thresh_px: float = Field(default=1.2, ge=0.1, le=20.0)
    flow_min_tracks: int = Field(default=8, ge=3, le=100)
    flow_stall_hysteresis: int = Field(default=3, ge=1, le=10)

    # --- continuous ("cruise") motion: smooth, non-stop driving ---
    # Master flag OFF by default; the wheels only cruise after the coast distance is
    # calibrated on hardware and this is flipped on (see the Tier 3 / cruise handover).
    continuous_motion_enabled: bool = False
    cruise_max_linear: float = Field(default=0.20, ge=0.0, le=0.5)  # normalized duty cap (~today's crawl)
    cruise_side_angles: list[float] = Field(default_factory=lambda: [-20, 20, -45, 45, -70, 70], max_length=12)
    forward_cone_deg: float = Field(default=20.0, ge=5.0, le=60.0)
    weave_settle_ms: float = Field(default=90.0, ge=30.0, le=400.0)
    ping_latency_ms: float = Field(default=50.0, ge=5.0, le=200.0)
    fwd_stale_ms: float = Field(default=700.0, ge=150.0, le=3000.0)
    slowdown_start_cm: float = Field(default=60.0, ge=20.0, le=200.0)
    cruise_coast_cm: float = Field(default=8.0, ge=0.0, le=60.0)  # measured PWM-cut coast (calibrate on HW)
    cruise_margin_cm: float = Field(default=4.0, ge=0.0, le=40.0)
    cruise_react_ms: float = Field(default=70.0, ge=10.0, le=400.0)
    cruise_max_turn: float = Field(default=0.5, ge=0.1, le=1.0)
    cruise_cornered_confirm: int = Field(default=2, ge=1, le=6)
    cruise_pulse_ms: int = Field(default=200, ge=80, le=600)


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
    # Behavior-arbitration daemon: the top-level "decide what to do and do it"
    # loop. OFF by default; flip on (on hardware) for self-directed operation.
    arbiter_enabled: bool = False
    arbiter_interval_seconds: int = Field(default=15, ge=2, le=600)
    # Autonomous-drive rhythm (the "living being" loop, all only active when the
    # arbiter is enabled). Boredom grows once it's been quiet this long, by this much
    # per heartbeat, until it crosses the arbiter's patrol bar -- then a patrol runs
    # and boredom resets, so the urge to roam ebbs and flows. patrol_min_gap stops
    # back-to-back loops from thrashing even when Pip is very curious.
    boredom_quiet_seconds: float = Field(default=90.0, ge=0.0, le=3600.0)
    boredom_growth_per_tick: float = Field(default=0.03, ge=0.0, le=0.5)
    patrol_min_gap_seconds: float = Field(default=120.0, ge=0.0, le=3600.0)
    # Auto self-preservation: at/below this battery %, the arbiter heads for the
    # charger (return-to-landmark) instead of exploring; critically low still asks.
    return_to_charger_min_battery: float = Field(default=35.0, ge=5.0, le=80.0)
    # RGB-as-expression (Pip has no display yet): a small loop animates the 8-LED
    # strip to reflect mood/energy (breathe/pulse) + charging/low-battery/alert.
    # Auto-starts only on hardware. The strip is Pip's primary "aliveness" channel.
    rgb_expression_enabled: bool = True
    rgb_expression_hz: int = Field(default=5, ge=1, le=30)
    rgb_max_brightness: int = Field(default=28, ge=1, le=120)
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
    nav: NavConfig = Field(default_factory=NavConfig)
    life_loop: LifeLoopConfig = Field(default_factory=LifeLoopConfig)

    @model_validator(mode="after")
    def _cruise_braking_invariant(self) -> "RoverConfig":
        # The continuous-motion speed cap relies on being able to brake within the
        # reflex distance: coast + margin must stay under the hard reflex floor, or
        # a hand-edited profile silently breaks braking (audit P-2).
        reflex = max(float(self.safety.reflex_hard_cm), float(self.safety.front_stop_distance_cm))
        if self.nav.cruise_coast_cm + self.nav.cruise_margin_cm >= reflex:
            raise ValueError(
                f"cruise_coast_cm ({self.nav.cruise_coast_cm}) + cruise_margin_cm ({self.nav.cruise_margin_cm}) "
                f"must be < reflex floor ({reflex}cm) so Pip can brake within the reflex distance"
            )
        return self

    def public_summary(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


def default_config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config" / "rover.default.json"


@lru_cache(maxsize=1)
def load_config() -> RoverConfig:
    path = Path(os.getenv("CLEO_ROVER_CONFIG", str(default_config_path()))).expanduser()
    data = json.loads(path.read_text(encoding="utf-8"))
    config = RoverConfig.model_validate(data)
    # Warn (don't fail) if a profile that can arm motors ships without the
    # downward-IR cliff reflex: the horizontal ultrasonic cannot see a stair/table
    # edge. Enable safety.cliff_reflex_enabled after verifying line_drop_value on
    # the real floor (see docs handover).
    if not config.safety.bench_safe_no_motors and not config.safety.cliff_reflex_enabled:
        logging.getLogger("cleo_rover").warning(
            "Profile %s can arm motors (bench_safe_no_motors=false) but cliff_reflex_enabled=false: "
            "no stair/edge protection. Verify line_drop_value polarity on hardware, then enable it.",
            config.profile,
        )
    # Catch a hand-edited reflex floor so high it makes a normal ~80cm doorway
    # impassable: Pip would silently refuse to approach (audit REL-5).
    reflex_floor = max(float(config.safety.reflex_hard_cm), float(config.safety.front_stop_distance_cm))
    if reflex_floor >= 70.0:
        logging.getLogger("cleo_rover").warning(
            "Reflex floor is %.0fcm (reflex_hard_cm/front_stop_distance_cm) -- that may make a "
            "standard doorway impassable; Pip will refuse to approach. Lower it unless intentional.",
            reflex_floor,
        )
    return config
