"""Offline-first voice: capture an utterance, transcribe it on-device, and route
the text through the existing /pip/command intent router.

Design (research-backed): a wake word gates an utterance capture; the utterance is
transcribed by an OFFLINE engine (whisper.cpp or Vosk) and the text is handed to
the same command router the CLI/Telegram use. Everything degrades gracefully: if
the mic/STT backends are not installed, this reports unavailable instead of
crashing, and simple commands ("stop", "come here") still work via the router.

Talking NEVER enables movement: voice routes to /pip/command with
allow_movement=False, and movement remains gated by grants + armed motors.

Setup (on the Pi, never committed):
  pip install '.[voice]'            # sounddevice + openwakeword (+ numpy)
  # offline STT, either:
  #  - whisper.cpp built, with CLEO_ROVER_WHISPER_BIN + CLEO_ROVER_WHISPER_MODEL, or
  #  - pip install vosk + a model dir (CLEO_ROVER_VOSK_MODEL)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

from . import peripherals

DEFAULT_BASE = "http://127.0.0.1:8099"


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _whisper_bin() -> str | None:
    return os.getenv("CLEO_ROVER_WHISPER_BIN") or shutil.which("whisper-cli")


def voice_backends() -> dict[str, Any]:
    return {
        "arecord": shutil.which("arecord") is not None,
        "sounddevice": _module_available("sounddevice"),
        "openwakeword": _module_available("openwakeword"),
        "vosk": _module_available("vosk"),
        "whisper_cpp_bin": _whisper_bin(),
    }


def _whisper_cpp_transcribe(wav: Path, model_path: str | None) -> dict[str, Any] | None:
    binary = _whisper_bin()
    model = model_path or os.getenv("CLEO_ROVER_WHISPER_MODEL")
    if not binary or not model or not Path(model).exists():
        return None
    out_prefix = wav.with_suffix("")
    cmd = [binary, "-m", str(model), "-f", str(wav), "-nt", "-otxt", "-of", str(out_prefix)]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except Exception as exc:  # pragma: no cover - hardware/binary dependent
        return {"ok": False, "available": True, "backend": "whisper_cpp", "error": repr(exc)}
    txt = out_prefix.with_suffix(".txt")
    if not txt.exists():
        return {"ok": False, "available": True, "backend": "whisper_cpp", "error": "no transcript output"}
    text = txt.read_text(encoding="utf-8", errors="replace").strip()
    return {"ok": bool(text), "available": True, "backend": "whisper_cpp", "text": text}


def _vosk_transcribe(wav: Path, model_path: str | None) -> dict[str, Any] | None:  # pragma: no cover - needs vosk + model
    if not _module_available("vosk"):
        return None
    model_dir = model_path or os.getenv("CLEO_ROVER_VOSK_MODEL")
    if not model_dir or not Path(model_dir).exists():
        return None
    import wave

    from vosk import KaldiRecognizer, Model  # type: ignore

    model = Model(str(model_dir))
    with wave.open(str(wav), "rb") as wf:
        rec = KaldiRecognizer(model, wf.getframerate())
        rec.SetWords(False)
        while True:
            data = wf.readframes(4000)
            if not data:
                break
            rec.AcceptWaveform(data)
        final = json.loads(rec.FinalResult())
    text = str(final.get("text", "")).strip()
    return {"ok": bool(text), "available": True, "backend": "vosk", "text": text}


def transcribe_wav(path: str | Path, *, backend: str = "auto", model_path: str | None = None) -> dict[str, Any]:
    """Transcribe a WAV with an offline engine. Graceful when none is installed."""
    wav = Path(path)
    if not wav.exists():
        return {"ok": False, "available": True, "error": "wav not found"}
    order = [backend] if backend in {"whisper_cpp", "vosk"} else ["whisper_cpp", "vosk"]
    for name in order:
        result = _whisper_cpp_transcribe(wav, model_path) if name == "whisper_cpp" else _vosk_transcribe(wav, model_path)
        if result is not None:
            return result
    return {"ok": False, "available": False, "error": "no offline STT backend (install whisper.cpp or vosk)"}


def capture_and_transcribe(
    *, seconds: float = 4.0, mic_device: str | None = None, rate: int = 16000, backend: str = "auto", model_path: str | None = None
) -> dict[str, Any]:
    capture = peripherals.capture_mic(seconds, device=mic_device, rate=rate)
    if not capture.get("ok"):
        return {"ok": False, "available": capture.get("available", False), "capture": capture, "text": None}
    stt = transcribe_wav(capture["path"], backend=backend, model_path=model_path)
    return {
        "ok": bool(stt.get("ok")),
        "available": stt.get("available", False),
        "text": stt.get("text"),
        "backend": stt.get("backend"),
        "capture": capture,
        "stt": stt,
    }


def route_command(base: str, text: str, *, source: str = "voice", timeout: float = 60.0) -> dict[str, Any]:
    payload = {"text": text, "source": source, "allow_movement": False}
    req = urllib.request.Request(
        base.rstrip("/") + "/pip/command", data=json.dumps(payload).encode(), method="POST", headers={"content-type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def run_wake_loop(base: str, *, seconds: float, mic_device: str | None, model_path: str | None, threshold: float = 0.6) -> int:  # pragma: no cover - hardware loop
    """Always-on wake-word loop. Requires sounddevice + openwakeword on a Pi."""
    backends = voice_backends()
    if not (backends["sounddevice"] and backends["openwakeword"]):
        print(json.dumps({"ok": False, "error": "voice loop needs sounddevice + openwakeword", "backends": backends}), file=sys.stderr)
        return 2
    import numpy as np  # type: ignore
    import sounddevice as sd  # type: ignore
    from openwakeword.model import Model  # type: ignore

    oww = Model()
    print(json.dumps({"ok": True, "event": "voice_loop_started", "backends": backends}))
    with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=1280) as stream:
        while True:
            block, _ = stream.read(1280)
            scores = oww.predict(np.frombuffer(block, dtype=np.int16))
            if any(score >= threshold for score in scores.values()):
                heard = capture_and_transcribe(seconds=seconds, mic_device=mic_device, model_path=model_path)
                text = heard.get("text")
                if text:
                    try:
                        routed = route_command(base, text)
                        print(json.dumps({"ok": True, "heard": text, "action": routed.get("action")}))
                    except Exception as exc:
                        print(json.dumps({"ok": False, "heard": text, "error": repr(exc)}), file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cleo Rover offline voice (wake word -> STT -> /pip/command)")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--seconds", type=float, default=4.0, help="Utterance capture length")
    parser.add_argument("--mic-device", default=os.getenv("ALSA_CARD"))
    parser.add_argument("--model", default=None, help="STT model path (whisper.cpp ggml or vosk dir)")
    parser.add_argument("--threshold", type=float, default=0.6)
    parser.add_argument("--once", action="store_true", help="Capture+transcribe+route a single utterance and exit")
    parser.add_argument("--backends", action="store_true", help="Print backend availability and exit")
    args = parser.parse_args(argv)

    if args.backends:
        print(json.dumps({"ok": True, "backends": voice_backends()}, indent=2))
        return 0
    if args.once:
        heard = capture_and_transcribe(seconds=args.seconds, mic_device=args.mic_device, model_path=args.model)
        result: dict[str, Any] = {"heard": heard}
        if heard.get("text"):
            result["routed"] = route_command(args.base, heard["text"])
        print(json.dumps(result, indent=2))
        return 0
    return run_wake_loop(args.base, seconds=args.seconds, mic_device=args.mic_device, model_path=args.model, threshold=args.threshold)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
