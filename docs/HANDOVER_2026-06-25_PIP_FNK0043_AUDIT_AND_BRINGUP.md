# Handover: FNK0043 hardware audit + bring-up (battery, return-home, RGB expression)

A multi-agent audit verified every pin / I2C address / PCA9685 channel / ADC chip
/ divider our code assumes against the **real Freenove FNK0043** (official docs +
Freenove's own source as ground truth). It found real bugs — all fixed below —
then three autonomy features were built on the verified facts. No display is
owned yet, so **RGB is Pip's expression channel**.

All changes are default-safe and sim-tested (`python -m pytest -q`, **316 passing**).

---

## 1. Audit verdict + fixes landed

| Subsystem | Verdict | Action |
|---|---|---|
| Motors / PCA9685 | MATCH (bench-verified) | none |
| **Turret / pan servo** | **MISMATCH (HIGH)** | **FIXED** — pan was using the non-inverted pulse formula; the FNK0043 pan channel (servo '0', ch8) is **inverted** (`2500-(angle+10)/0.09`). Every pan was mirrored, so VFH/cruise/weave steered *toward* gaps' opposites. Now `freenove.pan_pulse_us` + unit test. |
| **IR line sensors** | pins MATCH / **pull-up MISMATCH (HIGH)** | **FIXED** — `DigitalInputDevice(pull_up=True)` fought the driven LM393 output (floating channel biased to 1 → false cliff). Now `pull_up=None, active_state=True`. |
| **Ultrasonic** | pins MATCH / **read-path MISMATCH (HIGH)** | **FIXED** — gpiozero `DistanceSensor` background-smooths over `queue_len`, so the "median of 5" re-read the same buffer and the negative filter never fired. Now `queue_len=1, partial=True` → true single pings. |
| **ADC / battery** | **MISMATCH (HIGH)** | **FIXED** — coeff/multiplier were hard-coded for **PCB v2**; a v1 board misreads ~33%. Now `sensors.pcb_version` selects the **paired** (coeff, mult): v1=(3.3,×3), v2=(5.2,×2). |
| Cruise drive ramp | MED | **FIXED** — the 90 ms PWM ramp ran on every re-issued cruise pulse → never reached steady speed. Now skipped when the target duty is ~unchanged (`_duty_close`). |
| Bumpers | UNVERIFIED | left disabled (FNK0043 has no bump switches; pins are guesses). Do not enable `bumper_reflex_enabled` until metered. |
| RGB / camera | MATCH for Pip (Connect-v2 + Pi 4) | works; a Connect-v1/Pi-5 SPI fallback is a noted portability follow-up. |

**Must-verify-on-HW (code is fixed, physical check remains):** turret pan now goes
*right* on +pan (calibration step 5); IR polarity over a real void (step 8);
confirm PCB version (step 2/3). If your board is **PCB v1**, set
`sensors.pcb_version: 1` in the config.

---

## 2. New features (the "top 3", RGB swapped in for the face)

### Battery SOC + health — `rover/battery.py`, `GET /battery`
Replaces the old linear 6.4–8.4 V → % guess (which misread the flat middle of the
Li-ion curve and browned out the Pi under load) with:
- the verified ADS7830 front-end + PCB-paired divider;
- a real **2S Li-ion resting-voltage → SOC curve**;
- a **sag-aware, idle-gated estimator**: SOC is trusted only from idle samples
  (the pack relaxes after a drive pulse); in-motion reads are advisory; the
  critical-low trip is **debounced** (3 idle samples < 6.6 V) so a single
  in-motion dip never strands Pip; plus charging-trend detection.
- Fed each heartbeat; `None` on read failure (never a fake 0 %).
- *Calibrate later:* `BatteryEstimator(sag_k=…)` for load compensation (compare
  idle vs full-throttle voltage). Warn point is 7.0 V (Freenove's beep), not 6.4.

### Return-home executor — `rover/topo_executor.py`, `POST /tasks/return-home`
Pip can now **traverse** the topological place-graph to a goal (default the
charger), not just orient toward it. It executes each edge (turn + bounded
forward), then **relocalizes** by re-fingerprinting the place — so open-loop drift
never compounds across the route. If it can't recognize the next place after
N tries it **aborts and asks for help** instead of driving blind. `allow_movement`
gates real motion; without it the endpoint plans + reports only.

### RGB expression — `rover/rgb_affect.py`, `GET /pip/rgb-affect`
With no display, the 8-LED WS2812 strip is Pip's "aliveness" channel. A pure
`affect_to_frame` maps **mood → colour** and **energy → animation** (calm =
slow breathe, excited = pulse), with priority overrides: low-battery amber pulse >
red alert flash > charging green breathe > sleeping. A small ~5 Hz loop
(`life_loop.rgb_expression_enabled`, hardware-only auto-start) animates it; the
strip now also supports per-LED frames (`set_rgb_pixels`) for directional "looking
that way" cues.

---

## 3. Power-up autonomy path — `GET /calibration`

`GET /calibration` returns the ordered bring-up checklist **plus auto-checkable
readiness gates** (ultrasonic/ADC ready, plausible battery) and a
`ready_for_supervised_drive` flag. The minimal calibration to be autonomous on the
next powered run:

1. `i2cdetect -y 1` → 0x40 + 0x48 present.
2. Confirm PCB version → set `sensors.pcb_version` (1 or 2).
3. Multimeter the pack vs `/battery` voltage (catches a wrong divider).
4. Forward → all 4 wheels roll forward.
5. **Pan +30° → sonar rotates RIGHT** (confirms the inverted-pan fix).
6. Turret centre + ±70° clearance.
7. Time ultrasonic reads → set `ping_latency_ms` / `cruise_react_ms`.
8. IR over white/black/void → set `safety.line_drop_value`.
9. Coast distance at duty 0.3 → set `nav.cruise_coast_cm`.
10. UMBmark square → tune odometry.
11. `dtparam=spi=on` → RGB lights red.
12. **Enable reflexes last** (`cliff_reflex_enabled` after 5 & 8 pass).

Gate: steps 1–8 before any powered drive; 9–12 before continuous cruise. Then the
heartbeat, RGB expression, and (when you enable them) the arbiter/cruise give Pip
self-directed, self-expressing, self-preserving operation.

## Follow-ups (tracked)
- Battery `sag_k` load-compensation calibration (needs idle-vs-load measurement).
- RGB Connect-v1 / Pi-5 driver fallback (portability; Pip's board is fine).
- Bumper hardware verification before enabling the bump reflex.
- Wire the battery `critical` flag into the arbiter's return-to-charger trigger
  (currently uses battery %; the debounced critical is a stronger signal).
