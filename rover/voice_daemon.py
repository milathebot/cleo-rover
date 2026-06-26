"""Offline-first voice: hear a wake word, capture an utterance, transcribe it
on-device, and route the text through the existing /pip/command intent router.

Pipeline (research-backed, all on a Pi 4B, CPU-only):
  always-on wake word (openWakeWord)  ->  VAD-gated capture (silero-vad / webrtcvad)
  ->  offline STT (faster-whisper / whisper.cpp / vosk)  ->  /hearing/listen -> /pip/command

Everything degrades gracefully: if a stage's library/model is not installed it is
skipped, the daemon reports the gap instead of crashing, and typed/relayed
commands still work via the router. Talking NEVER enables movement: voice routes
with allow_movement=False, and movement stays gated by grants + armed motors.

Setup (on the Pi, never committed):
  pip install '.[voice]'                 # sounddevice + openwakeword + faster-whisper + silero-vad
  # pick an STT backend (auto tries them in order: faster-whisper -> whisper.cpp -> vosk):
  #  - faster-whisper (default, pure-python): CLEO_ROVER_FW_MODEL=base.en  (downloads once, ~150MB)
  #  - whisper.cpp built: CLEO_ROVER_WHISPER_BIN + CLEO_ROVER_WHISPER_MODEL (ggml .bin)
  #  - vosk: pip install vosk + CLEO_ROVER_VOSK_MODEL (model dir)
  # train a "Hey Pip" wake word (openWakeWord colab) and point CLEO_ROVER_OWW_MODEL at it.
See docs/VOICE_SETUP.md for the full walkthrough.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
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
    """Which voice stages are actually installed/available on this host."""
    return {
        "arecord": shutil.which("arecord") is not None,
        "sounddevice": _module_available("sounddevice"),
        "openwakeword": _module_available("openwakeword"),
        "faster_whisper": _module_available("faster_whisper"),
        "vosk": _module_available("vosk"),
        "whisper_cpp_bin": _whisper_bin(),
        "silero_vad": _module_available("silero_vad"),
        "webrtcvad": _module_available("webrtcvad"),
    }


def stt_ready(backends: dict[str, Any] | None = None) -> bool:
    b = backends or voice_backends()
    return bool(b["faster_whisper"] or b["whisper_cpp_bin"] or b["vosk"])


def wake_ready(backends: dict[str, Any] | None = None) -> bool:
    b = backends or voice_backends()
    return bool(b["sounddevice"] and b["openwakeword"])


# --- mic health ---------------------------------------------------------------


def mic_status(device: str | None = None) -> dict[str, Any]:
    """Probe the capture side of ALSA so an operator/health view can confirm the
    USB mic is actually present before relying on the voice loop. Heuristic but
    cheap: `arecord -l` lists capture cards; if a specific card is configured we
    check it appears. No-op-safe when arecord is absent (dev hosts)."""
    card = device if device is not None else os.getenv("ALSA_CARD")
    if not shutil.which("arecord"):
        return {"ready": False, "card": card, "detail": "arecord not found", "cards": []}
    try:
        devices = peripherals.audio_devices()
    except Exception as exc:  # pragma: no cover - hardware dependent
        return {"ready": False, "card": card, "detail": f"probe failed: {exc!r}", "cards": []}
    capture = devices.get("capture", {})
    stdout = str(capture.get("stdout", ""))
    cards = [line.strip() for line in stdout.splitlines() if line.strip().lower().startswith("card ")]
    has_any = bool(cards)
    if card is not None and has_any:
        token = f"card {card}".lower()
        found = any(token in line.lower() for line in cards) or any(str(card).lower() in line.lower() for line in cards)
        return {"ready": found, "card": card, "detail": "configured card present" if found else "configured card not found in arecord -l", "cards": cards}
    return {"ready": has_any, "card": card, "detail": "capture device present" if has_any else "no capture device found", "cards": cards}


# --- speech to text -----------------------------------------------------------

_FW_MODELS: dict[str, Any] = {}


def _faster_whisper_transcribe(wav: Path, model_path: str | None) -> dict[str, Any] | None:
    """faster-whisper (CTranslate2) — pure-python, best accuracy/effort on a Pi 4.

    The model is a NAME (e.g. base.en) via CLEO_ROVER_FW_MODEL, kept warm across
    calls. The shared stt_model_path is for whisper.cpp/vosk and is ignored here so
    a ggml path can't accidentally be loaded as a faster-whisper model."""
    if not _module_available("faster_whisper"):
        return None
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception:  # pragma: no cover - import/runtime dependent
        return None
    name = os.getenv("CLEO_ROVER_FW_MODEL", "base.en")
    try:  # pragma: no cover - model load + transcription needs the model + audio
        model = _FW_MODELS.get(name)
        if model is None:
            compute = os.getenv("CLEO_ROVER_FW_COMPUTE", "int8")
            threads = int(os.getenv("CLEO_ROVER_FW_THREADS", "4"))
            model = WhisperModel(name, device="cpu", compute_type=compute, cpu_threads=threads)
            _FW_MODELS[name] = model
        segments, _info = model.transcribe(str(wav), language="en", beam_size=1, vad_filter=False)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return {"ok": bool(text), "available": True, "backend": "faster_whisper", "text": text}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "available": True, "backend": "faster_whisper", "error": repr(exc)}


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


_STT_BACKENDS = {
    "faster_whisper": _faster_whisper_transcribe,
    "whisper_cpp": _whisper_cpp_transcribe,
    "vosk": _vosk_transcribe,
}


def transcribe_wav(path: str | Path, *, backend: str = "auto", model_path: str | None = None) -> dict[str, Any]:
    """Transcribe a WAV with an offline engine. Graceful when none is installed.

    auto: try faster-whisper -> whisper.cpp -> vosk, skipping any not installed and
    falling through a backend that is installed but errors/returns empty."""
    wav = Path(path)
    if not wav.exists():
        return {"ok": False, "available": True, "error": "wav not found"}
    explicit = backend in _STT_BACKENDS
    order = [backend] if explicit else ["faster_whisper", "whisper_cpp", "vosk"]
    last: dict[str, Any] | None = None
    for name in order:
        result = _STT_BACKENDS[name](wav, model_path)
        if result is None:
            continue  # backend not installed/configured -> next
        last = result
        if result.get("ok") or explicit:
            return result
        # auto mode: this backend is present but errored/empty -> try the next one
    if last is not None:
        return last
    return {"ok": False, "available": False, "error": "no offline STT backend (install faster-whisper, whisper.cpp, or vosk)"}


# --- capture ------------------------------------------------------------------


def _vad_capture_available() -> bool:
    return _module_available("sounddevice") and (_module_available("silero_vad") or _module_available("webrtcvad"))


def _capture_with_vad(  # pragma: no cover - real-time mic + VAD, hardware only
    *, mic_device: str | None, rate: int, max_seconds: float, silence_ms: int, preroll_ms: int = 240
) -> dict[str, Any] | None:
    """Record until the speaker stops (trailing silence) instead of a fixed window,
    so short commands return fast and long ones aren't clipped. Returns None on any
    setup failure so the caller can fall back to a fixed-length capture."""
    try:
        import numpy as np  # type: ignore
        import sounddevice as sd  # type: ignore
        import wave
        import time as _time
    except Exception:
        return None

    frame_ms = 30
    frame_len = int(rate * frame_ms / 1000)
    preroll_frames = max(1, int(preroll_ms / frame_ms))
    silence_frames_needed = max(1, int(silence_ms / frame_ms))
    max_frames = int(max_seconds * 1000 / frame_ms)

    is_speech = None
    if _module_available("silero_vad"):
        try:
            from silero_vad import load_silero_vad  # type: ignore
            import torch  # type: ignore

            model = load_silero_vad(onnx=True)

            def is_speech(frame_i16):  # noqa: ANN001
                audio = torch.from_numpy(frame_i16.astype("float32") / 32768.0)
                return float(model(audio, rate).item()) >= 0.5
        except Exception:
            is_speech = None
    if is_speech is None and _module_available("webrtcvad"):
        try:
            import webrtcvad  # type: ignore

            vad = webrtcvad.Vad(2)

            def is_speech(frame_i16):  # noqa: ANN001
                return vad.is_speech(frame_i16.tobytes(), rate)
        except Exception:
            is_speech = None
    if is_speech is None:
        return None

    device = mic_device or os.getenv("ALSA_CARD")
    sd_device = f"plughw:{device},0" if device else None
    collected: list[Any] = []
    preroll: list[Any] = []
    started = False
    silent_run = 0
    try:
        with sd.RawInputStream(samplerate=rate, channels=1, dtype="int16", blocksize=frame_len, device=sd_device) as stream:
            for _ in range(max_frames):
                buf, _ovf = stream.read(frame_len)
                frame = np.frombuffer(bytes(buf), dtype=np.int16)
                speaking = bool(is_speech(frame))
                if not started:
                    preroll.append(frame)
                    if len(preroll) > preroll_frames:
                        preroll.pop(0)
                    if speaking:
                        started = True
                        collected.extend(preroll)
                        collected.append(frame)
                else:
                    collected.append(frame)
                    silent_run = 0 if speaking else silent_run + 1
                    if silent_run >= silence_frames_needed:
                        break
    except Exception as exc:
        return {"ok": False, "available": True, "error": f"vad capture failed: {exc!r}"}

    if not collected:
        return {"ok": False, "available": True, "text": None, "detail": "no speech captured"}
    path = Path(os.getenv("CLEO_ROVER_TTS_CACHE_DIR", "/tmp")) / f"cleo-rover-listen-{int(_time.time() * 1000)}.wav"
    audio = np.concatenate(collected)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(audio.tobytes())
    return {"ok": True, "available": True, "path": str(path), "seconds": round(len(audio) / rate, 2), "rate": rate, "vad": True}


def capture_utterance(
    *, seconds: float = 4.0, mic_device: str | None = None, rate: int = 16000, vad: bool = True, max_seconds: float = 8.0, silence_ms: int = 700
) -> dict[str, Any]:
    """Record one utterance. Prefers VAD (stop on trailing silence) and falls back
    to a fixed-length `arecord` capture when sounddevice/VAD aren't installed."""
    if vad and _vad_capture_available():
        result = _capture_with_vad(mic_device=mic_device, rate=rate, max_seconds=max_seconds, silence_ms=silence_ms)
        if result is not None and result.get("ok"):
            return result
        # VAD configured but produced nothing/failed -> fall back to fixed capture
    return peripherals.capture_mic(seconds, device=mic_device, rate=rate)


def capture_and_transcribe(
    *,
    seconds: float = 4.0,
    mic_device: str | None = None,
    rate: int = 16000,
    backend: str = "auto",
    model_path: str | None = None,
    vad: bool = True,
) -> dict[str, Any]:
    capture = capture_utterance(seconds=seconds, mic_device=mic_device, rate=rate, vad=vad)
    if not capture.get("ok"):
        return {"ok": False, "available": capture.get("available", False), "capture": capture, "text": None}
    try:
        stt = transcribe_wav(capture["path"], backend=backend, model_path=model_path)
        return {
            "ok": bool(stt.get("ok")),
            "available": stt.get("available", False),
            "text": stt.get("text"),
            "backend": stt.get("backend"),
            "capture": capture,
            "stt": stt,
        }
    finally:
        # Avoid leaking /tmp on the always-on loop: drop the WAV + any whisper .txt.
        try:
            wav = Path(capture["path"])
            wav.unlink(missing_ok=True)
            wav.with_suffix(".txt").unlink(missing_ok=True)
        except Exception:
            pass


# --- routing back to the body service ----------------------------------------


def route_command(base: str, text: str, *, source: str = "voice", timeout: float = 60.0) -> dict[str, Any]:
    """Route a transcript straight to /pip/command (allow_movement always False)."""
    payload = {"text": text, "source": source, "allow_movement": False}
    req = urllib.request.Request(
        base.rstrip("/") + "/pip/command", data=json.dumps(payload).encode(), method="POST", headers={"content-type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def route_through_hearing(base: str, text: str, *, timeout: float = 60.0) -> dict[str, Any]:
    """Route via /hearing/listen?text= so the speech event + dashboard transcript
    ring are recorded (single source of truth), then on to /pip/command."""
    q = urllib.parse.urlencode({"text": text})
    req = urllib.request.Request(base.rstrip("/") + "/hearing/listen?" + q, data=b"", method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def report_voice_event(base: str, phase: str, *, text: str | None = None, score: float | None = None, error: str | None = None, timeout: float = 5.0) -> dict[str, Any] | None:
    """Tell the body service the hearing state (wake / idle / error) so the operator
    console can show a live 'listening' indicator. Best-effort; never raises."""
    params: dict[str, str] = {"phase": phase}
    if text is not None:
        params["text"] = text
    if score is not None:
        params["score"] = f"{float(score):.3f}"
    if error is not None:
        params["error"] = error[:200]
    req = urllib.request.Request(base.rstrip("/") + "/voice/event?" + urllib.parse.urlencode(params), data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def run_wake_loop(  # pragma: no cover - hardware loop (mic + models)
    base: str,
    *,
    seconds: float,
    mic_device: str | None,
    model_path: str | None,
    backend: str = "auto",
    threshold: float = 0.6,
    vad: bool = True,
    oww_model: str | None = None,
) -> int:
    """Always-on wake-word loop. Requires sounddevice + openwakeword on a Pi."""
    backends = voice_backends()
    if not wake_ready(backends):
        print(json.dumps({"ok": False, "error": "voice loop needs sounddevice + openwakeword", "backends": backends}), file=sys.stderr)
        return 2
    import numpy as np  # type: ignore
    import sounddevice as sd  # type: ignore
    from openwakeword.model import Model  # type: ignore

    oww = Model(wakeword_models=[oww_model]) if oww_model else Model()
    report_voice_event(base, "idle")
    print(json.dumps({"ok": True, "event": "voice_loop_started", "backends": backends, "stt_ready": stt_ready(backends)}))
    device = mic_device or os.getenv("ALSA_CARD")
    sd_device = f"plughw:{device},0" if device else None
    with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=1280, device=sd_device) as stream:
        while True:
            block, _ = stream.read(1280)
            scores = oww.predict(np.frombuffer(block, dtype=np.int16))
            top = max(scores.values()) if scores else 0.0
            if top >= threshold:
                report_voice_event(base, "wake", score=top)
                # A wedged mic/STT/route must never kill the always-on loop -> Pip
                # would go silently deaf until restart. Catch everything and continue.
                try:
                    heard = capture_and_transcribe(seconds=seconds, mic_device=mic_device, backend=backend, model_path=model_path, vad=vad)
                    text = heard.get("text")
                    if text:
                        routed = route_through_hearing(base, text)
                        print(json.dumps({"ok": True, "heard": text, "action": (routed.get("routed") or {}).get("action")}))
                except Exception as exc:
                    report_voice_event(base, "error", error=repr(exc))
                    print(json.dumps({"ok": False, "error": repr(exc)}), file=sys.stderr)
                finally:
                    report_voice_event(base, "idle")
                    try:
                        oww.reset()  # avoid an immediate re-trigger on the same phrase
                    except Exception:
                        pass


def _voice_config_defaults() -> Any:
    try:
        from .config import load_config

        return load_config().voice
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    cfg = _voice_config_defaults()
    parser = argparse.ArgumentParser(description="Cleo Rover offline voice (wake word -> VAD -> STT -> /pip/command)")
    parser.add_argument("--base", default=os.getenv("CLEO_ROVER_BASE", DEFAULT_BASE))
    parser.add_argument("--seconds", type=float, default=(cfg.utterance_seconds if cfg else 4.0), help="Fixed-capture fallback length (VAD overrides when available)")
    parser.add_argument("--mic-device", default=(cfg.mic_device if (cfg and cfg.mic_device) else os.getenv("ALSA_CARD")))
    parser.add_argument("--backend", default=(cfg.stt_backend if cfg else "auto"), choices=["auto", "faster_whisper", "whisper_cpp", "vosk"])
    parser.add_argument("--model", default=(cfg.stt_model_path if cfg else None), help="STT model path (whisper.cpp ggml or vosk dir)")
    parser.add_argument("--oww-model", default=os.getenv("CLEO_ROVER_OWW_MODEL"), help="openWakeWord model file ('Hey Pip'); default = built-in models")
    parser.add_argument("--threshold", type=float, default=0.6)
    parser.add_argument("--no-vad", action="store_true", help="Disable VAD; use a fixed-length capture")
    parser.add_argument("--once", action="store_true", help="Capture+transcribe+route a single utterance and exit")
    parser.add_argument("--backends", action="store_true", help="Print backend availability and exit")
    parser.add_argument("--mic-status", action="store_true", help="Probe the configured mic and exit")
    args = parser.parse_args(argv)

    if args.backends:
        print(json.dumps({"ok": True, "backends": voice_backends(), "stt_ready": stt_ready(), "wake_ready": wake_ready()}, indent=2))
        return 0
    if args.mic_status:
        print(json.dumps({"ok": True, "mic": mic_status(args.mic_device)}, indent=2))
        return 0
    if args.once:
        heard = capture_and_transcribe(seconds=args.seconds, mic_device=args.mic_device, backend=args.backend, model_path=args.model, vad=not args.no_vad)
        result: dict[str, Any] = {"heard": heard}
        if heard.get("text"):
            result["routed"] = route_through_hearing(args.base, heard["text"])
        print(json.dumps(result, indent=2))
        return 0
    return run_wake_loop(
        args.base,
        seconds=args.seconds,
        mic_device=args.mic_device,
        backend=args.backend,
        model_path=args.model,
        threshold=args.threshold,
        vad=not args.no_vad,
        oww_model=args.oww_model,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
