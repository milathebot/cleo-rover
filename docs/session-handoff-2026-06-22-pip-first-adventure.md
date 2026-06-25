> ⚠️ **HISTORICAL session handoff** (2026-06-22, pre-overhaul). Superseded by the
> current system — see [`../handover.md`](../handover.md) + [`../README.md`](../README.md).

# Pip first-adventure handoff — 2026-06-22

## Status

Pip is in a good bench/charging state and is close to first supervised floor adventure readiness.

Confirmed working:

- Body API via `cleo-rover-body.service`.
- Telegram command agent via `cleo-rover-telegram-agent.service`.
- Motors remain unarmed in presence/bench-safe mode unless explicitly switched/armed.
- Camera capture works with `rpicam-still` at 1296x972.
- Ultrasonic, line sensors, RGB, mic status, speaker status report healthy.
- USB audio output works on ALSA `plughw:1,0`.
- `cleo-rover say` works through `espeak-ng` with `aplay -D plughw:1,0`.
- Hermes/Pip response bridge works through the Telegram agent.
- Hermes vision-label bridge works and can store `/vision/analysis` results.

Not done / intentionally skipped:

- The loose-wire ST7789 display stayed static and was skipped. Wait for the ribbon-cable display before continuing screen work.
- Pip did not move during the final test. That is expected unless the floor-mode and floor-arm confirmation flow is completed.

## Important services

Real active API service:

```bash
sudo systemctl status cleo-rover-body --no-pager
```

Telegram command agent:

```bash
sudo systemctl status cleo-rover-telegram-agent --no-pager
```

Old `cleo-rover.service` may be inactive/deprecated. The API process that matters is `cleo-rover-body.service`.

## Hermes bridge

Current bridge path uses a Cloudflare quick tunnel from the PC/WSL Hermes gateway to the Pi:

```text
CLEO_ROVER_HERMES_API_BASE=https://tent-exchange-brunswick-eyed.trycloudflare.com/v1
CLEO_ROVER_HERMES_MODEL=hermes-agent
```

The key is stored only in systemd env override as `CLEO_ROVER_HERMES_API_KEY`.

Check from Pi:

```bash
curl https://tent-exchange-brunswick-eyed.trycloudflare.com/health
systemctl show cleo-rover-telegram-agent -p Environment
```

The quick tunnel is not durable across PC restarts. If it dies, start a new tunnel on WSL/PC and update `CLEO_ROVER_HERMES_API_BASE` in the Telegram agent override.

## New commands added this session

### Pip Hermes response bridge

From Telegram:

```text
/rover pip how are you feeling?
/rover pip what do you notice around you?
```

Flow:

1. Telegram agent runs `cleo-rover pip ...`.
2. If Pip returns `relay_to_hermes`, the agent calls Hermes API.
3. Hermes responds as Pip.
4. Pi speaks the line via `cleo-rover say`.
5. Telegram receives `Pip/Hermes: ... spoken`.

A fallback voice response was added if Hermes provider fails.

### Vision-label bridge

From SSH:

```bash
cleo-rover vision-label --zone office --speak --compact
```

From Telegram:

```text
/rover vision-label --zone office --speak --compact
```

Flow:

1. Captures a fresh snapshot with `/vision/snapshot`.
2. Sends the image as a data URL to Hermes vision through the API bridge.
3. Requests JSON with `summary`, `labels`, `objects`, `hazards`, `clear_path`, `adventure_readiness`, and `confidence`.
4. Posts result back to `/vision/analysis`.
5. Stores spatial/semantic labels in rover memory.
6. Optionally speaks a short scene/readiness line.

## Audio notes

`aplay -D plughw:1,0 /tmp/cleo-test-tone.wav` produced sound but quiet. `cleo-rover say` works and reported:

```text
play_cmd: ["aplay", "-D", "plughw:1,0"]
volume: 400
```

The speaker itself is likely the limiting factor. Buy a stronger small speaker/amp later.

## Display notes

Software preflight had previously confirmed the intended ST7789 wiring map:

```text
ST7789 SPI1.0: DIN=GPIO20, CLK=GPIO21, CS=GPIO6, DC=GPIO25, RST=GPIO5, BL=3.3V/manual
```

But the loose-wire display showed static and got warm. Do not continue with that screen. Use a ribbon-cable display later.

## First adventure safety flow

Pip will not move from just `vision-label` or `pip observe`. Movement remains blocked unless the explicit floor flow is completed.

Recommended prechecks:

```text
/rover preflight
/rover floor-precheck --zone office
/rover floor-map-dry-run --zone office --steps 1
/rover vision-label --zone office --speak --compact
```

If clean, first tiny supervised movement:

```text
/rover floor-mode request
/rover floor-mode confirm CODE
/rover floor-precheck --zone office
/rover floor-arm request
/rover floor-arm confirm CODE
/rover floor-map-run --zone office --steps 1
```

Only do this when:

- Pip is on the floor, not on the bench.
- Open area is clear.
- Cats, feet, cables, and stairs are clear.
- `/rover estop` is ready.
- Vision label reports no hazards and either `observe_only` with human judgment or `ready_for_tiny_floor_step`.

## Relevant commits

```text
b691cf5 Add Hermes vision label bridge
8c71114 Add Pip Hermes fallback voice response
0a7dc05 Bridge Pip Telegram prompts to Hermes API
d5d7abd Add Pip Hermes response bridge
4808963 Allow disabling hardware display driver
```
