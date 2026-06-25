> ⚠️ **HISTORICAL (as-was audit).** This documents the *original* broken state and
> the plan that motivated the rebuild — the "STUBBED / DISCONNECTED" architecture
> and defects D1–D23 below are what was fixed, not the current system. Phases 0–9 +
> Tier 1/2/3 are all implemented. For the current state read [`../handover.md`](../handover.md)
> (operating manual) and [`../README.md`](../README.md). Kept for design rationale + lineage.

# Pip (cleo-rover) — Decision-Grade Audit & Path to an Embodied AI Agent

**Author:** Lead robotics architect (synthesis of 5 subsystem audits + 5 research briefs)
**Date:** 2026-06-25
**Hardware reality:** Pi 4B 4GB · Freenove FNK0043 4WD · turret HC-SR04 (pan/tilt, pan-only driven) · 3 digital IR line sensors · Pi camera (CSI) · USB mic · PCA9685 PWM · PCF8591 ADC · **no encoders, no IMU** (confirmed: `drivers.py:212 imu:None`, `config.py:53` placeholder).
**Non-negotiables honored throughout:** Pi-local safety stays authoritative; software-only (no new hardware); every change sim- and unit-testable now; LLM mind is a pluggable OpenAI-compatible *enhancement* over always-on local autonomy (Pip must run offline); voice is offline-first.

---

## 1. Executive Summary

**What is actually wrong.** Pip is a well-engineered *body* with a layered, genuinely Pi-local safety system (30ms watchdog + 20ms drive-monitor + per-pulse guarded_drive), wrapped around a navigation policy and a "mind/soul" that are largely disconnected from reality:

1. **The headline "cuts off ~20cm before the doorway" bug is real and has three compounding root causes**, all confirmed in source:
   - **Stale `last_reflex_stop` is sticky and re-counted every cycle.** It is set with a `time` field (`drivers.py:90-97`) and *never reset anywhere*. The scout's `if body.state.last_reflex_stop:` check (`service.py:1752`) has **no freshness comparison**, so the same old dict is counted on all ~30 cycles, inflating `blocked_streak` and forcing a `recovery-turn` roughly every 3 cycles forever.
   - **A single raw front sample vetoes the fresh centered scan.** Raw `front_value` is checked *before* `center_distance` (`service.py:1687, 1693`), so an off-axis/transient ping turns the robot even when the scan center is clear.
   - **The 45cm reflex floor collides with the operator's `blocked_cm`, and the creep band starts at `blocked_cm + 10`.** `_reflex_threshold_cm()` returns `max(45.0, front_stop_distance_cm)` (`drivers.py:76`); the creep branch only creeps when `center_distance > command.blocked_cm + 10.0` (`service.py:1706`). With `--blocked-cm 45`, anything 45–55cm scan-turns and anything <45cm hard-stops — **approaching a doorway (which requires closing to <45cm) is structurally impossible.**

2. **The "mind" is not in the loop.** Hermes is called exactly once, as a chat fallback in `/pip/command` (`service.py:1220`); it never returns a navigation intent and never touches motors. All movement is deterministic ultrasonic rule-cascades.

3. **Perception never reaches the brain.** The capture path emits `camera_snapshot` events; the brain reads only `vision_analysis` events — which nothing in the autonomous path ever produces. `latest_vision` is structurally always null after a run.

4. **Emotions and memory are decorative.** Two rival emotion systems exist (`AutonomyEngine` vs `pip_state['boredom']`); the live life-loop ignores the richer one. Memory is written prolifically but read only for dashboards — no decision consults it.

5. **Voice input does not exist.** Only `arecord -l` enumeration; the senses daemon ships without `--simulate` and is a silent no-op.

**Highest-leverage path to the owner's vision** (emotional, surroundings-aware, independently thinking but obedient, soul + memory, offline-first with pluggable LLM): a **dual-process embodied-agent architecture** — keep the Pi-local reactive+safety tier authoritative, add a small **doorway state machine with hysteresis** (fixes the headline bug), turn perception into a real in-loop vision service, wire a **schema-constrained, Pi-validated LLM intent** as an *enhancement* layer that can never relax a safety guard, unify the emotion model so it actually selects behavior, make memory consulted before moving, and add an **offline-first voice daemon** (openWakeWord → Silero VAD → whisper.cpp tiny.en → existing `/pip/command` router). Phase 1 — the doorway fixes — is fully sim-testable today and unblocks everything.

---

## 2. Architecture As-It-Is

```
Operator surfaces                Body service (FastAPI :8099)                 Hardware
─────────────────                ─────────────────────────────               ────────
CLI rover/client.py ─┐
Telegram (→CLI) ─────┼──HTTP──▶  /pip/command (intent router)                 PCA9685 motors/servos
sim UI rover/ui.py ──┘           /tasks/hallway-scout ─▶ _hallway_scout_task   HC-SR04 (turret pan)
                                 /vision/analysis  (manual only)               3 IR line sensors (READ-ONLY)
                                 /hearing/simulate (fake events)               PCF8591 ADC (battery/LDR)
                                 /autonomy/tick                                Pi camera (capture only)
                                                                              USB mic (enumerate only)
        ┌──────────────── AUTHORITATIVE & CONNECTED ────────────────┐
        │ 30ms watchdog + 20ms drive_monitor + guarded_drive         │  ← real, layered, Pi-local
        │ movement grants, bench_safe gate, supervisor.validate_intent│
        └────────────────────────────────────────────────────────────┘

        ┌──────────────── STUBBED / DISCONNECTED ───────────────────┐
        │ Hermes "mind"     → chat fallback only, never an intent     │
        │ Vision            → capture events ≠ vision_analysis events │  → latest_vision == null
        │ AutonomyEngine    → only /autonomy/tick; life-loop ignores it│
        │ Memory (SQLite)   → write-only for decisions                │
        │ Voice input       → simulated; senses daemon = no-op        │
        │ IR line sensors   → read into telemetry, zero consumers     │
        │ Bumpers, tilt servo, USB mic → configured, never used       │
        └────────────────────────────────────────────────────────────┘
```

**Body vs brain today:** there is effectively only a body. The "brain" (`brain.py choose_body_intent`, `pip_brain.py` packet) produces deterministic heuristics or advisory English strings that dead-end in a JSON response. Safety being LLM-independent is a genuine strength — the current disconnection is *fail-safe, not fail-dangerous*.

---

## 3. Confirmed Defects, Prioritized (merged & deduped)

The doorway early-cutoff is defects **D1–D4** and is the front-line fix.

| # | Sev | Subsystem | File:line | Root cause | Fix |
|---|-----|-----------|-----------|-----------|-----|
| **D1** | **High** | Nav (doorway) | `drivers.py:90-97`, `service.py:1752-1758` | `last_reflex_stop` is retained state set with `time` and **never reset**; scout's truthy check has no freshness compare → re-counted every cycle, `blocked_streak` never settles, recovery-turn every ~3 cycles | Make reflex **event-based**: track `last_handled_reflex_time`, act only if `rs['time'] > last_handled`; add `consume_reflex_stop()` on `RoverBody`. Apply same to `reactive_explore` (`service.py:1381`) |
| **D2** | **High** | Nav (doorway) | `service.py:1664-1699`, `peripherals.py:90-106` | Raw single-sample `front_value` checked *before* `center_distance`; gives a noisy off-axis ping veto over a fresh scan | Use **scan-center as primary** forward-clearance; treat raw front only as hard-emergency floor (<30cm). On conflict, recenter turret + median-of-5. Log `raw_front_cm`/`scan_center_cm`/`decision_front_cm` |
| **D3** | **High** | Nav (doorway) | `drivers.py:75-76`, `service.py:1706`, `config/...floor.cautious.json:66` | Reflex floor pinned at `max(45, …)`; creep starts at `blocked_cm+10` → 45–55cm dead-zone, doorway approach impossible | Introduce ordered **bands** (emergency 25–30 / blocked ~42 / creep blocked..clear / clear). Make reflex floor configurable; creep band starts at `blocked_cm` not `+10` |
| **D4** | **Med** | Nav (doorway) | `service.py:1728 vs 1752-1754`, `1687-1758` | `blocked_streak=0` reset runs *before* the unconditioned reflex increment; no doorway phase/hysteresis → stateless per-cycle oscillation | Reorder: handle reflex at top of cycle, gated on freshness. Add minimal **doorway FSM** (approach→creep→align→exit→recover) with N-consecutive-sample confirmation |
| **D5** | **High** | Sensors | `peripherals.py:90-106`, `awareness.py:147`, `service.py:542` | Ultrasonic is a single raw `gpiozero` read; `range_state_from_samples` is fed a 1-element list so median collapses | Median-of-N (5 reads, ~40ms spacing) inside `read_front_distance_cm`; reject negatives + max-distance saturation |
| **D6** | **High** | Perception | `service.py:1416-1423` vs `pip_brain.py:31-32` | Capture emits `camera_snapshot`; brain reads only `vision_analysis` → produced by nothing in-loop | Server-side vision analysis (mirror `client.hermes_vision_analysis`) → emit real `vision_analysis` via same path as `/vision/analysis`; degrade to low-confidence placeholder offline |
| **D7** | **High** | Perception | `service.py:951` (40-event window), `590-616`, `persistence.py:105-118` | Even a real `vision_analysis` is evicted by hundreds of per-angle `map_observation`/scan/speech events | Add **kind-filtered** lookup `recent_events(kind=vision_analysis, limit=1)`; throttle `map_observation` writes |
| **D8** | **High** | Mind | `service.py:1219-1228`, `brain.py:96-152`, `autonomy.py:91-160` | LLM never in decision loop; `choose_body_intent` is pure if/elif despite its name | Add brain-assisted intent step at uncertainty points; LLM returns constrained JSON, validated Pi-side; deterministic policy is default + fallback |
| **D9** | **Med** | Mind/safety | `service.py:1219-1237`, `hermes_bridge.py:28-78` | No intent schema, no allow-list, no clamps — safety relies on Hermes simply never being asked | Define strict intent schema + `validate_intent()` clamping step/bearing and refusing on front<blocked / low battery / unapproved zone |
| **D10** | **High** | Voice | `senses.py:23-30`, `service.py:420-428`, `peripherals.py:152-159`, `cleo-rover-senses.service:9` | No capture/STT anywhere; "hearing" is synthetic; daemon ships without `--simulate` = silent no-op | Real ALSA capture + offline STT (whisper.cpp); `/hearing/listen` endpoint + `cleo-rover listen`; fix systemd unit |
| **D11** | **High** | Autonomy | `service.py:1067-1132` vs `autonomy.py:91-179` | Two rival emotion systems; life-loop uses `boredom` scalar and ignores `AutonomyEngine` | Route `pip_life_tick` through `AutonomyEngine.decide()`; single mood source; delete duplicate `boredom` |
| **D12** | **High** | Memory | `pip_brain.py:116-155`, `service.py:1096-1132` | Memory is write-only for decisions; nothing consults spatial/event memory before moving | Pre-move memory consult: bias scan order / step / refuse-and-ask from remembered hazards + recently-blocked bearings |
| **D13** | **Med** | Memory | `pip_brain.py:46-66`, `persistence.py:120-145` | Hazards derived from never-expiring spatial memory; ~6040s-old cat still flagged | Age-gate hazards (last_seen < 60–120s); add `age_seconds` + fresh flag; decay/prune spatial items |
| **D14** | **Med** | Sensors/safety | `peripherals.py:78-88`, `drivers.py:207-208` | 3 IR line sensors read but **zero consumers** — no cliff/edge protection | Wire downward IR as **floor drop-off reflex** in `drive_safety` (cheapest open-loop safety win) |
| **D15** | **Med** | Sensors | `service.py:109-110`, `config/rover.default.json:37-38` | Bumper pins configured but never instantiated/read | Add `read_bumpers()` + bump reflex, or remove pins from config |
| **D16** | **Med** | Sensors | `freenove.py:201-205`, `models.py:258-259` | Tilt servo (ch 9) configured + advertised but never driven | Add `tilt_deg` to `TurretCommand` and drive ch 9, or remove dead config |
| **D17** | **High** | Tests | `tests/*`, `client.py:187-204,417-447` | Zero coverage of CLI arg layer and the flagged-buggy hallway-scout task | Add CLI→payload tests + service-level hallway-scout tests **before** any motion tuning |
| **D18** | **Med** | Autonomy | `autonomy.py:160-179` | Only `curiosity`/`energy` gate behavior; mood/attention/confidence are decorative | Make confidence→step size, attention→turret orient, mood→cadence load-bearing |
| **D19** | **Med** | Autonomy | `autonomy.py:85-89`, `service.py:1841-1844` | Idle decay only runs when external client pokes endpoint; no internal heartbeat | FastAPI lifespan asyncio task: inject idle ticks, refresh energy from battery, apply decay |
| **D20** | **Med** | Distance | `service.py:666-701, 630-639` | `travelled_cm` = sum of *requested* chunks; reflex-cut pulses counted as full | Derive `est_travelled_cm` from front-ultrasonic delta per chunk; detect stall; label all distances "requested, unverified" |
| **D21** | **Low** | Sensors | `peripherals.py:49-58,143-146` | Battery: single ADC read, magic `*2`, `0.0` default masks missing channel | Average N reads; return `None` not `0.0` on missing; verify divider |
| **D22** | **Low** | Ops | `telegram_agent.py:19-41,315-321` | `say` invoked internally but absent from allowlist → `/rover say` rejected | Add `say` to `SAFE_PREFIX_COMMANDS` + test |
| **D23** | **Low** | Ops | `deploy/systemd/*.service` | Three mismatched/non-existent home dirs across units | Normalize to install-script-generated paths; fix stale `brain.service` |

---

## 4. Capability Gaps vs the Vision

| Capability | Current state | Gap | Vision need |
|---|---|---|---|
| **Sensor utilization** | Ultrasonic single-shot; IR/bumpers/tilt/mic configured but unused | No filtering, no cliff safety, no contact safety, no vertical aim, no hearing | "Surroundings-aware" requires every existing sensor doing work |
| **Perception-in-loop** | Capture ≠ analysis; `latest_vision` always null | No camera→labels in any autonomous task; vision never gates a move | Sees a cat / open door / cable and reacts |
| **Distance/odometry** | Open-loop time pulses; `travelled_cm` asserted | No measurement; stalls counted as travel; no heading feedback | Honest pose estimate with uncertainty for planning |
| **Voice** | Enumerate-only; synthetic events | No capture, VAD, wake-word, STT | Offline-first "talk to Pip and it acts" |
| **Explore/map** | Per-cycle reactive; turret-pan-relative landmarks; confidence inflates on repeats | No doorway FSM, no pose, no decaying landmark cache | Walks the home, remembers rooms |
| **LLM-mind** | Chat fallback only | No structured intent, no Pi-side validator, no fallback contract | "Independently thinking but obedient" enhancement over local autonomy |
| **Emotions** | Two rival systems; only curiosity/energy gate anything | Mood/attention/confidence decorative; life-loop ignores engine | "Emotional" — feelings change behavior |
| **Memory** | Write-only for decisions; hazards never expire | No pre-move consult; stale sightings dominate | "Soul + memory" — past experience shapes action |

---

## 5. Research-Backed Design Decisions

### 5.1 Distance/heading without encoders → per-side open-loop model + ultrasonic delta + IR/landmark resets, treated as a decaying guess
**Chosen:** calibrate `v_cm_s = a·duty + b` and `deg_s = c·(duty_R − duty_L)` plus dead-time/coast constants; integrate over command time with a **growing uncertainty**; force resets on known features. Aid with **HC-SR04 frame-to-frame range delta** (1–2cm against a flat perpendicular wall) and **IR line crossings** for drift reset. Optionally a sparse Lucas-Kanade "am-I-moving" gate at 320×240. **Never** use `travelled_cm` for decisions. Heading error dominates and is unbounded — spend budget on turn-rate, run UMBmark (CW+CCW square) to trim. Cost on Pi 4: model = negligible; sparse LK ~10–20 FPS. (https://arxiv.org/pdf/1509.02154, https://websites.umich.edu/~johannb/umbmark.htm, https://arxiv.org/pdf/1912.07805, https://www.bridgefusion.com/blog/2019/4/10/robot-localization-dead-reckoning-in-first-tech-challenge-ftc, https://github.com/daisukelab/cv_opt_flow)

### 5.2 Ultrasonic doorway nav → 5-sample median + two-threshold hysteresis FSM + stop-and-scan widest-gap, scan-center as truth, no open-loop maneuvers
**Chosen:** median-of-5 per turret angle; **VFH+-style dual-threshold per-direction state with memory** (blocked only above `τ_high`, free only below `τ_low`); require ~3 consecutive confirmations before any transition; 4 bands EMERGENCY<15 / BLOCKED 15–40 / CREEP 40–70 / CLEAR>70; at CREEP do a −80..+80° sweep in ≤15° steps, aim at the **angular center of the widest gap ≥ robot_width+margin**, recenter turret, re-confirm, then creep; steering deadband (~5°) + rate-limit. Decisions only on the recentered 0° reading; **never** "turn X°/drive Xcm" blind. This is precisely the cure for "random turn ~20cm before a doorway" (single-threshold oscillation + specular dropout). Cost: <1% CPU; FSM or `py_trees`. (https://dlacko.org/blog/2016/01/24/remove-impulse-noise-from-ultrasonic/, https://en.wikipedia.org/wiki/Vector_Field_Histogram, https://www.sciencedirect.com/science/article/pii/S2590123024008806, https://github.com/GaryDyr/HC-SR04-beam-tests, https://py-trees.readthedocs.io/en/devel/introduction.html)

### 5.3 Pi-4 offline voice → openWakeWord → Silero VAD → whisper.cpp tiny.en → `/pip/command`, sounddevice capture, optional cloud fallback
**Chosen:** single systemd daemon, `sounddevice` `InputStream` 16kHz mono int8 80ms blocks (USB mic via explicit index / `plughw`). **openWakeWord** (threshold 0.6, `vad_threshold` on) always-on (~+10–15% one core). On wake: ~400ms pre-roll ring + Silero VAD endpoint (~700ms trailing silence, cap 8s). Transcribe **whisper.cpp tiny.en q5_1, 4 threads** (~2.8× RT, ~1–1.6s for a 3s command) or `faster-whisper tiny int8`. POST transcript → existing `/pip/command` router. Optional online fallback (Groq whisper-large-v3-turbo ≈$0.0007/min) only when network up and local confidence low — **never required**. Do not attempt small/medium streaming; keep STT a per-utterance burst. (https://github.com/dscripka/openWakeWord, https://www.maibornwolff.de/en/know-how/openai-whisper-raspberry-pi/, https://github.com/ggml-org/whisper.cpp/discussions/166, https://rajatpandit.com/agentic-ai/real-time-audio-vad/, https://alphacephei.com/vosk/models)

> If the command set stays fixed, a **Vosk small + constrained JSON grammar** path is a strong near-perfect-recognition alternative for commands specifically.

### 5.4 Pi-4 camera vision → one INT8 TFLite SSD-MobileNet-v2-FPNLite @320 via picamera2 lores + sparse LK looming, compact semantic packet
**Chosen:** capture with **picamera2** main RGB 640×480 + **lores YUV420 320×240** (`capture_array`, ~15% one core); never `cv2.VideoCapture` over libcamera. Primary detector **INT8 TFLite SSD-MobileNet-v2-FPNLite 320** (tflite-runtime, XNNPACK, `num_threads=3`, ~9–11 FPS, ~70% mAP) run at ~5 Hz; sparse **Lucas-Kanade** on lores gray at ~10–15 Hz for forward-progress + flow-divergence looming/TTC. No MiDaS (~1.2 FPS), no dense Farneback. Emit a tiny quantized packet to the brain at 2–4 Hz: `{detections:[{label,conf,bbox_norm,bearing_bucket,size_bucket}], looming:{ttc_s}, forward_progress:{moving}, free_space:{doorway_ahead}, frame_age_ms}`. Active cooling mandatory. Vision is **advisory only** — it can add a stop/scan constraint, never relax the ultrasonic reflex. (https://www.ejtech.io/learn/tflite-object-detection-model-comparison, https://docs.ultralytics.com/guides/raspberry-pi/, https://eureka.patsnap.com/article/optical-flow-with-opencv-lucas-kanade-vs-farneback, https://picamera2.com/can-picamera2-work-with-opencv/)

### 5.5 LLM-in-the-loop → dual-process; PC/cloud OpenAI-compatible brain, Pi-local deterministic gate, schema-constrained intent
**Chosen:** three tiers. Reflex tier (Pi, no LLM, no network) owns ultrasonic stop + command watchdog (halt if no fresh validated command in 300–500ms) + bounded motion budget (open-loop, since no odometry). Skill/validation tier (Pi) accepts a **closed JSON skill contract** (`drive_forward|drive_back|turn_left|turn_right|stop|look|speak|remember`, bounded params), `validate_intent()` clamps/refuses with structured reason (Safety-Chip-style pruning) and translates to bounded timed bursts re-checked against ultrasonic. Brain tier (PC/cloud, 0.2–1 Hz) gets persona + emotion vector + compact world-state/memory packet + schema, uses **grammar-constrained decoding** so it can only emit valid contract JSON. Pluggable OpenAI-compatible base URL (Hermes *or* Claude). **Offline fallback:** deterministic local policy (+ optional ~1B Q4 SLM for canned persona chat only, never navigation). Do **not** run the planner on the Pi (3B ≈ 3–5 tok/s eats the 4GB). Emotion may reorder safe options, never disable a guard. (https://arxiv.org/abs/2410.08328, https://yzylmc.github.io/safety-chip/, https://arxiv.org/abs/2409.14908, https://www.stratosphereips.org/blog/2025/6/5/how-well-do-llms-perform-on-a-raspberry-pi-5, https://mbrenndoerfer.com/writing/constrained-decoding-structured-llm-output)

### 5.6 Line-following → reuse the 3 IR sensors as a downward floor-edge (cliff) interlock first; gentle PD line-follow optional
**Chosen:** **safety-first.** Aim IR at the floor lip, poll ≥20 Hz on a dedicated thread; "no reflection for ≥2 samples" → immediate stop + short back-off + rotate away (hard interlock above all nav). Optional gentle indoor path-follow = smoothed bang-bang / light **PD** on the weighted 3-sensor error (Ki=0; 3 sensors = only 5 states); no competition PID. Battery guard via PCF8591 cutoff. Cost negligible. (https://docs.freenove.com/projects/fnk0043/en/latest/fnk0043/codes/Mecanum/6_Infrared_Car.html, https://www.sciencebuddies.org/science-fair-projects/project-ideas/Robotics_p033/robotics/edge-detecting-arduino-robot, https://www.teachmemicro.com/implementing-pid-for-a-line-follower-robot/)

---

## 6. Target Architecture

```
                    ┌─────────────────────────────────────────────────────────┐
   PLUGGABLE MIND   │  Slow Brain (PC/cloud, OpenAI-compatible: Hermes OR Claude)│  0.2–1 Hz
   (ENHANCEMENT)    │  in: persona + emotion vector + world-state/memory packet  │
                    │  out: schema-constrained JSON intent (closed skill enum)   │
                    └───────────────────────────┬─────────────────────────────┘
                                                 │  intent JSON (advisory)
                    ┌────────────────────────────▼─────────────────────────────┐
   PI — SKILL/      │  validate_intent(): allowlist + param clamps + refuse on    │
   VALIDATION       │  front<blocked / low-batt / unapproved-zone / no-floor.     │
   (AUTHORITATIVE)  │  Structured refusal → brain replans. Falls back to ↓        │
                    └───────────────┬───────────────────────────┬───────────────┘
                                    │ validated bounded burst    │ default (offline / refusal)
                    ┌───────────────▼───────────────┐  ┌─────────▼──────────────────┐
   PI — LOCAL       │  Doorway/Hallway FSM (hysteresis│  │ Deterministic explore policy│
   AUTONOMY         │  bands, median sensing, widest- │  │ (memory-consulting)         │
   (ALWAYS-ON)      │  gap, scan-center truth)        │  └────────────────────────────┘
                    └───────────────┬───────────────┘
                    ┌───────────────▼───────────────────────────────────────────┐
   PI — REFLEX TIER │ 30ms watchdog · 20ms drive_monitor · guarded_drive ·        │  authoritative,
   (NEVER VETOED)   │ ultrasonic reflex · IR floor-drop reflex · bumper reflex ·   │  network-independent
                    │ command watchdog · bounded motion budget · battery cutoff   │
                    └───────────────┬───────────────────────────────────────────┘
                                    │
   PERCEPTION SVC  ◀────────────────┼────────────────▶  VOICE DAEMON
   picamera2 lores → TFLite SSD-    │                   sounddevice → openWakeWord
   MobileNet @320 (5Hz) + sparse LK │                   → Silero VAD → whisper.cpp
   → vision_analysis events (advisory)                  → /pip/command (offline-first)

   MEMORY  SQLite: episodic events + decaying landmark cache; consolidated to semantic
           facts off-board; consulted pre-move; hazards age-gated.
   EMOTION Single AutonomyEngine state (mood/curiosity/energy/attention/confidence) →
           biases step size, scan breadth, cadence, willingness-to-ask, speech tone.
```

**Validated intent contract (canonical):**
```json
{ "skill": "drive_forward|drive_back|turn_left|turn_right|stop|look|speak|remember",
  "params": { "speed": 0-100, "duration_ms": 0-800, "bearing_deg": -90..90, "text": "..." },
  "reason": "string" }
```
**Safety veto rule:** every intent passes `validate_intent()` → unknown skill or out-of-range param or `front<blocked_cm` or `battery=charge_before_movement` or `zone∉approved` → **refuse** with reason (fed back to brain) and fall back to deterministic policy. Emotion/persona influence the *choice among already-safe options and tone only*.

---

## 7. Phased Implementation Plan

> Legend: **[SIM]** fully verifiable in simulator + unit tests now · **[HW]** needs supervised hardware tuning later.

### Phase 0 — Test scaffolding & honesty (do first) **[SIM]**
- **New:** `tests/test_client_cli.py` — monkeypatch `request` in `rover/client.py`, assert `hallway-scout` flag→payload mapping, defaults, `scan_angles` parsing (D17).
- **New:** `tests/test_hallway_scout.py` — service-level harness with injected sensors + monkeypatched `reactive_escape_scan` (template: `test_api.py:190-219`); encodes the *current buggy* behavior as characterization tests so Phase 1 changes are observable.
- **Edit:** `rover/telegram_agent.py:40` add `say` to `SAFE_PREFIX_COMMANDS` (D22) + test in `test_telegram_agent.py`.
- **Edit:** `deploy/systemd/*.service` normalize home dirs (D23).
- **Run:** full `pytest`.

### Phase 1 — Stop the early cutoff (doorway bug) **[SIM]** ← unblocks the vision
- **Edit `rover/drivers.py`:** add `consume_reflex_stop()` returning-and-clearing `last_reflex_stop`; make `_reflex_threshold_cm()` read a new configurable `safety.reflex_hard_cm` (default kept at 45 for legacy, lowered to ~28 in floor-cautious) instead of hardcoded `max(45,…)` (D1, D3).
- **Edit `rover/service.py` `_hallway_scout_task`:**
  - Move reflex handling to **top of cycle**, gate on `consume_reflex_stop()` freshness; only increment `blocked_streak` on a genuinely new event (D1, D4).
  - Run scan first; compute `decision_front_cm = scan_center`; use raw `front_value` only as <30cm hard-emergency; log `raw_front_cm`/`scan_center_cm`/`decision_front_cm` (D2).
  - Introduce ordered **bands** and make the creep band start at `blocked_cm` (delete the `+10`); add **hysteresis** (need 2 consecutive fresh blocked reads before recovery turn; N consecutive clear before exit) (D3, D4).
  - Add minimal doorway FSM state (`approach/creep/align/exit/recover`) held across cycles.
- **Edit `rover/service.py reactive_explore` (`~1381`):** same freshness gate (D1).
- **New config keys:** `safety.reflex_hard_cm`, `nav.creep_band_lo_cm`, `nav.creep_band_hi_cm`, `nav.confirm_samples`, `nav.hysteresis_clear_margin_cm`.
- **Tests:** extend `test_hallway_scout.py` — assert (a) a stale `last_reflex_stop` does **not** inflate `blocked_streak`, (b) raw-front-blocked + scan-center-clear yields creep not scan-turn, (c) a 45–55cm center now creeps (no dead-zone), (d) recovery-turn only after 2 *fresh* blocked reads.

### Phase 2 — Filtered sensing + open-loop distance honesty **[SIM]** (calibration **[HW]**)
- **Edit `rover/peripherals.py`:** median-of-5 in `read_front_distance_cm` (reject negatives + max-distance saturation, distinct "no-return/open-unknown"); tag readings with pan angle + timestamp; average N ADC reads, return `None` not `0.0` (D5, D21).
- **Edit `rover/service.py`:** `est_travelled_cm` from front-ultrasonic delta per chunk; stall detection (commanded forward, range unchanged N chunks → stop/ask); label distances "requested, unverified" (D20).
- **New `rover/odometry.py`:** per-side `v_cm_s(duty)`/`deg_s(duty_diff)` model + dead-time/coast + growing uncertainty (calibration constants in config).
- **Config:** `odometry.cm_s_coeff`, `odometry.deg_s_coeff`, `odometry.dead_time_ms`, `odometry.coast_cm`.
- **Tests:** `test_sensors_filter.py` (median rejects spikes), `test_odometry.py` (stall detection, uncertainty growth). **[HW]** UMBmark square to fit coefficients.

### Phase 3 — Cliff + bumper reflexes **[SIM]**
- **Edit `rover/peripherals.py`:** `read_bumpers()` (D15); IR floor-drop interpretation (D14).
- **Edit `rover/drivers.py`/`drive_safety`:** floor-drop and bump → hard reflex stop, peer of ultrasonic reflex; dedicated fast poll.
- **Config:** `safety.cliff_reflex_enabled`, `safety.bumper_reflex_enabled`.
- **Tests:** `test_reflex_safety.py` — injected "no floor" / bump → motors stop, motion refused.

### Phase 4 — Perception in the loop + vision fix **[SIM]** (tuning **[HW]**)
- **New `rover/vision_service.py`:** picamera2 lores capture, INT8 TFLite SSD-MobileNet-v2-FPNLite @320 (tflite-runtime, XNNPACK, 3 threads, ~5 Hz), sparse LK looming; emits **real `vision_analysis` events** via the `/vision/analysis` code path; degrades to low-confidence placeholder offline (D6).
- **Edit `rover/pip_brain.py`:** kind-filtered latest-vision lookup independent of the 40-event window (D7); age-gate hazards + `age_seconds`/fresh flag (D13).
- **Edit `rover/persistence.py`:** `recent_events(kind=…, limit=…)`; throttle/prune `map_observation` (D7).
- **Edit `rover/service.py`:** vision **adds** stop/scan constraints in `_hallway_scout_task`, never relaxes reflex.
- **Tests:** `test_vision_service.py` (capture→`vision_analysis` emitted, packet shape), `test_pip_brain.py` (latest_vision populated under flood; stale hazard suppressed). **[HW]** model FPS/threshold tuning with cooling.

### Phase 5 — LLM mind in the loop (pluggable enhancement) **[SIM]**
- **New `rover/intent_contract.py`:** schema + `validate_intent()` (clamps/refusals/structured reason).
- **Edit `rover/hermes_bridge.py`:** OpenAI-compatible call returning constrained JSON (grammar/structured-output); pluggable base URL/key (Hermes or Claude).
- **Edit `rover/service.py`:** brain-assisted step at uncertainty points (doorway band / front unknown) — build packet, ask brain, `validate_intent`, dispatch or fall back to deterministic policy; offline default unchanged (D8, D9).
- **Config:** `mind.base_url`, `mind.model`, `mind.enabled`, `mind.timeout_ms`, `mind.invoke_on` (uncertainty triggers).
- **Tests:** `test_intent_contract.py` — unsafe intents refused (unknown skill, oversize step, front<blocked, low battery, unapproved zone); brain timeout/garbage → deterministic fallback; **offline path produces no LLM call and still moves safely.**

### Phase 6 — Offline-first voice **[SIM]** (mic tuning **[HW]**)
- **New `rover/voice_daemon.py`:** sounddevice → openWakeWord (thr 0.6 + Silero VAD) → endpoint → whisper.cpp tiny.en → POST `/pip/command`.
- **Edit `rover/service.py`:** `/hearing/listen` endpoint beside `/hearing/simulate`; **Edit `rover/client.py`:** `cleo-rover listen`; **Edit `peripherals.py`:** real `capture_mic()`; fix `cleo-rover-senses.service` (D10).
- **Config:** `voice.wakeword_model`, `voice.threshold`, `voice.stt_backend`, `voice.cloud_fallback_enabled`.
- **Tests:** `test_voice_pipeline.py` — fixed WAV → transcript → `/pip/command` intent (STT mocked); end-to-end safety test that a voice command cannot move in bench profile without grant + armed motors. **[HW]** USB mic ALSA/level tuning.

### Phase 7 — Gentle line-follow (optional path mode) **[SIM]**
- **New `rover/line_follow.py`:** PD on weighted 3-sensor error (Ki=0), timed line-loss search, junction handling; low base speed.
- **Tests:** `test_line_follow.py` — state→turn mapping, line-loss search, **cliff reflex pre-empts follow.**

### Phase 8 — Explore + map (decaying landmark cache) **[SIM]**
- **Edit `rover/mapping.py`/`persistence.py`:** heading-relative decaying landmark cache; stop inflating localization confidence from repeat counts; store turret pan separately (D-spatial).
- **Edit `rover/service.py`:** explore policy **consults memory** pre-move (bias scan order/step, down-weight recently-blocked bearings) (D12).
- **Tests:** `test_mapping.py` — confidence decays; recently-blocked bearing down-weighted.

### Phase 9 — Emotions + memory deepening (the "soul") **[SIM]**
- **Edit `rover/service.py pip_life_tick`:** route through `AutonomyEngine.decide()`; delete `boredom` scalar; one mood source (D11).
- **Edit `rover/autonomy.py`:** make confidence→step, attention→turret orient, mood→cadence/tone load-bearing (D18); FastAPI lifespan heartbeat injects idle/battery events + decay (D19); emit battery event each tick so `energy` tracks reality.
- **Edit `rover/pip_soul.py`:** collapse to one identity source; persona derived from same object as engine baselines.
- **Edit `rover/service.py apply_decision`:** deliver emotion-tinted speech (wire TTS, already implemented in `peripherals.speak_text`).
- **Tests:** `test_autonomy.py` — mood/confidence change step/cadence; heartbeat decays state with no external client; persona cannot relax a safety guard.

---

## 8. Risks & Test Strategy

**What could regress**
- **Doorway tuning swings the other way** (Pip noses into doorframes). Mitigation: keep the reflex hard-stop authoritative; only the *soft* bands move; characterization tests in Phase 0 pin both old and new behavior.
- **Lowering `reflex_hard_cm`** narrows the physical safety margin. Mitigation: it is *configurable and floor-profile-scoped*; default legacy 45 unchanged; cliff + bumper reflexes (Phase 3) add independent stops; **[HW]** supervised tuning before lowering in production.
- **Vision/voice CPU contention** starving the control loop. Mitigation: detection at 5 Hz, STT as per-utterance burst, voice daemon as a separate `nice`-d service; vision/voice are advisory and the reflex tier is network/CPU-spike independent.
- **LLM proposing unsafe intents.** Mitigation: `validate_intent()` is a pure function with exhaustive unit tests; refusal falls back to deterministic policy; emotion firewalled from safety.
- **Memory decay tuning** hiding real hazards or surfacing stale ones. Mitigation: age-gate thresholds in config; tests assert both fresh-surfaced and stale-suppressed.

**How the suite + sim guard it**
- Every phase ships its tests *first* (Phase 0 builds the missing CLI + hallway-scout coverage the maintainers explicitly requested). The existing `TestClient` suite (~35 endpoints, safety refusals) plus `test_supervised_brain.py` (intent contract) are the regression backbone.
- Hard invariants asserted by tests across phases: (1) **no operator/voice/LLM input can move in bench profile** without grant + armed motors + cleared `bench_safe`; (2) **reflex/cliff/bumper stops fire independently of the high-level loop and the LLM**; (3) **brain timeout/garbage/offline → deterministic safe fallback**; (4) **emotion/persona never relaxes a guard, extends a motion budget, or overrides the ultrasonic stop.**
- **[SIM]-now vs [HW]-later:** all logic/policy/contract/event-flow changes (Phases 0,1,3,4-logic,5,7,8,9 and the sim halves of 2,4,6) are fully verifiable now in simulator + unit tests. Only physical *calibration* needs supervised hardware: odometry UMBmark coefficients (Phase 2), vision FPS/threshold + cooling (Phase 4), and USB-mic ALSA/level + wake-word false-fire tuning (Phase 6). None of those hardware steps are on the safety-critical path — the reflex tier and `validate_intent` are proven in sim first.