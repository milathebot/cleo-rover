#!/usr/bin/env bash
set -euo pipefail

# Installs the offline voice daemon (wake word -> VAD -> STT -> /pip/command) as a
# systemd service that starts after the body. See docs/VOICE_SETUP.md for the full
# walkthrough (installing the .[voice] extra, picking an STT model, training a
# "Hey Pip" wake word). Talking never moves Pip: voice routes with
# allow_movement=False; motion stays gated by grants + armed motors.

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
SERVICE=/etc/systemd/system/cleo-rover-voice.service
ENV_FILE=/etc/cleo-rover/voice.env

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo scripts/install_voice_daemon_systemd.sh" >&2
  exit 1
fi

mkdir -p /etc/cleo-rover
if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<'EOF'
# Body service the daemon talks to (wake -> /voice/event, transcript -> /hearing/listen).
CLEO_ROVER_BASE=http://127.0.0.1:8099
# USB mic ALSA card (number or name). The Pip mic is on card slot 2.
ALSA_CARD=2
# --- STT backend (auto tries: faster-whisper -> whisper.cpp -> vosk) ---
# faster-whisper (default, recommended): downloads the model once (~150MB for base.en).
CLEO_ROVER_FW_MODEL=base.en
CLEO_ROVER_FW_COMPUTE=int8
CLEO_ROVER_FW_THREADS=4
# whisper.cpp (alternative): set both to use a built binary + ggml model.
#CLEO_ROVER_WHISPER_BIN=/home/cleo/whisper.cpp/build/bin/whisper-cli
#CLEO_ROVER_WHISPER_MODEL=/home/cleo/whisper.cpp/models/ggml-base.en.bin
# vosk (alternative): a model directory.
#CLEO_ROVER_VOSK_MODEL=/home/cleo/vosk/model-small-en
# --- wake word ---
# openWakeWord model file for "Hey Pip" (train via the openWakeWord colab). Omit to
# use the built-in models (alexa/hey jarvis/etc) for a quick smoke test.
#CLEO_ROVER_OWW_MODEL=/home/cleo/cleo-rover/models/hey_pip.onnx
EOF
  chmod 600 "$ENV_FILE"
  chown root:root "$ENV_FILE"
fi

cat > "$SERVICE" <<EOF
[Unit]
Description=Cleo Rover offline voice (wake word -> STT -> /pip/command)
After=network-online.target sound.target cleo-rover-body.service
Wants=network-online.target
Requires=cleo-rover-body.service

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/.venv/bin/cleo-rover-voice
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cleo-rover-voice.service

echo "Installed cleo-rover-voice.service."
echo "1) Install voice deps:  $APP_DIR/.venv/bin/pip install '$APP_DIR'[voice]"
echo "2) Edit config:         sudo nano $ENV_FILE   (mic card, STT model, wake word)"
echo "3) Smoke test backends: $APP_DIR/.venv/bin/cleo-rover-voice --backends"
echo "4) Check the mic:       $APP_DIR/.venv/bin/cleo-rover-voice --mic-status"
echo "5) One-shot listen:     $APP_DIR/.venv/bin/cleo-rover-voice --once"
echo "Start: sudo systemctl start cleo-rover-voice"
echo "Logs:  journalctl -u cleo-rover-voice -f"
