# Voice setup — giving Pip ears ("Hey Pip")

Pip's offline voice pipeline turns the (until now unused) USB microphone into a
hands-free command channel:

```
always-on wake word          VAD-gated capture            offline STT                 existing router
  (openWakeWord)      ->   (silero-vad: stop on    ->   (faster-whisper ->     ->   /hearing/listen
  "Hey Pip"                  trailing silence)           whisper.cpp -> vosk)         -> /pip/command
```

Everything runs **on the Pi, CPU-only** and **offline**. Every stage degrades
gracefully: if a library or model is missing, that stage is skipped and reported
(via `/voice/status`) instead of crashing.

**Safety invariant:** talking can never move Pip. Voice routes through
`/pip/command` with `allow_movement=False`; movement stays gated by an explicit
movement grant + armed motors, exactly like every other command source.

---

## 0. Hardware

- USB microphone on **ALSA card slot 2** (the Pip mic). Confirm with `arecord -l`
  — you should see `card 2: ... [USB Audio Device]`.
- The same USB speaker used for TTS is unaffected; capture (mic) and playback
  (speaker) are independent ALSA devices.

## 1. Install the voice extra

```bash
cd ~/cleo-rover
.venv/bin/pip install '.[voice]'
```

This pulls `sounddevice`, `openwakeword` (Pi only), `faster-whisper`, and
`silero-vad`. On a Pi 4 these are all CPU/NEON friendly. `webrtcvad` is an optional
lighter-weight VAD fallback (`pip install webrtcvad`) if you'd rather not use
silero.

## 2. Pick an STT backend

`auto` (the default) tries them in order and uses the first that works:

| Backend | How to enable | Notes |
|---|---|---|
| **faster-whisper** (recommended) | `CLEO_ROVER_FW_MODEL=base.en` | Pure-python, best accuracy/effort. Downloads the model once (~150 MB for `base.en`). `~1–2 s` per short command on a Pi 4 at `int8`. |
| **whisper.cpp** | `CLEO_ROVER_WHISPER_BIN=…/whisper-cli` + `CLEO_ROVER_WHISPER_MODEL=…/ggml-base.en.bin` | A single C binary if you'd rather not carry the CTranslate2 dependency. |
| **vosk** | `pip install vosk` + `CLEO_ROVER_VOSK_MODEL=…/model-small-en` | Streaming + lowest footprint; lower accuracy. |

faster-whisper tuning (optional): `CLEO_ROVER_FW_COMPUTE=int8`,
`CLEO_ROVER_FW_THREADS=4`.

## 3. Train a "Hey Pip" wake word

The built-in openWakeWord models (`alexa`, `hey jarvis`, …) work for a quick smoke
test. For a real **"Hey Pip"** wake word, train one (free) from synthetic speech
using the [openWakeWord training colab](https://github.com/dscripka/openWakeWord)
(≈1 hour, produces a ~200 KB `.onnx`). Drop it on the Pi and point at it:

```bash
CLEO_ROVER_OWW_MODEL=/home/cleo/cleo-rover/models/hey_pip.onnx
```

(The pre-trained openWakeWord models are CC-BY-NC; a model you train yourself is
unrestricted — fine either way for a personal robot.)

## 4. Smoke test before running the loop

```bash
.venv/bin/cleo-rover-voice --backends     # what's installed + stt/wake readiness
.venv/bin/cleo-rover-voice --mic-status   # is the configured mic visible to ALSA?
.venv/bin/cleo-rover-voice --once         # capture one utterance, transcribe, route
```

`--once` (and the wake loop) capture with VAD when available — they stop when you
stop talking, instead of a fixed window. Use `--no-vad` to force a fixed-length
capture.

## 5. Run it as a service

```bash
sudo scripts/install_voice_daemon_systemd.sh   # writes /etc/cleo-rover/voice.env + the unit
sudo nano /etc/cleo-rover/voice.env            # set ALSA_CARD=2, STT model, wake word
sudo systemctl start cleo-rover-voice
journalctl -u cleo-rover-voice -f
```

The unit starts **after** `cleo-rover-body.service` and restarts on failure. A
wedged mic/STT/route never kills the always-on loop — each utterance is caught and
the loop keeps listening.

## 6. Watch it on the console

The operator dashboard (`GET /`) shows a **Hearing** panel: listening indicator,
wake count, last-heard transcripts, mic/STT/wake readiness. Programmatically:

```bash
curl -s localhost:8099/voice/status | python3 -m json.tool
```

`wake_word` and `speech` events are written to the event log, so Pip's diary and
autonomy see that it was spoken to.

---

## How it routes (for the curious)

1. openWakeWord scores the mic stream; crossing the threshold fires a wake.
2. The daemon posts `POST /voice/event?phase=wake` → the console lights up
   "listening" and a `wake_word` event is logged.
3. It captures one utterance (VAD-gated), transcribes it offline, and posts the
   text to `POST /hearing/listen?text=…`.
4. `/hearing/listen` logs a `speech` event, records the transcript for the console,
   and routes the text through `/pip/command` (the same router the CLI and Telegram
   use) with `allow_movement=False`.
5. The daemon posts `phase=idle`; the loop returns to listening.

## Troubleshooting

- **`--backends` shows `wake_ready: false`** → `pip install '.[voice]'` didn't get
  `sounddevice`/`openwakeword` (openwakeword is Pi-only by marker).
- **`--mic-status` shows `ready: false`** → wrong `ALSA_CARD`; check `arecord -l`.
- **Transcripts are empty** → no STT backend; set `CLEO_ROVER_FW_MODEL=base.en`
  (downloads on first use) or configure whisper.cpp/vosk.
- **Speaker went quiet / wrong device** → mic and speaker are separate ALSA cards;
  the mic config (`ALSA_CARD` for capture) does not change TTS playback routing.
