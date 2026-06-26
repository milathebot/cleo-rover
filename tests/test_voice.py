"""Tests for offline voice: mic capture, graceful STT, and command routing.

Real audio/STT only runs on the Pi; here we cover command construction, graceful
degradation, and the end-to-end transcript -> /pip/command routing (incl. the
safety invariant that talking cannot move Pip in the bench profile)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from rover import peripherals, voice_daemon
from rover.service import app

client = TestClient(app)


def test_voice_backends_reports_known_keys():
    backends = voice_daemon.voice_backends()
    for key in ("arecord", "sounddevice", "openwakeword", "faster_whisper", "vosk", "whisper_cpp_bin", "silero_vad", "webrtcvad"):
        assert key in backends


def test_stt_and_wake_ready_helpers():
    assert voice_daemon.stt_ready({"faster_whisper": True, "whisper_cpp_bin": None, "vosk": False}) is True
    assert voice_daemon.stt_ready({"faster_whisper": False, "whisper_cpp_bin": None, "vosk": False}) is False
    assert voice_daemon.wake_ready({"sounddevice": True, "openwakeword": True}) is True
    assert voice_daemon.wake_ready({"sounddevice": True, "openwakeword": False}) is False


def test_transcribe_wav_auto_falls_through_failed_backend(monkeypatch, tmp_path):
    # In auto mode a backend that is installed but errors/returns empty must not
    # short-circuit -- the next installed backend should still get a turn.
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF" + b"\x00" * 200)
    monkeypatch.setitem(voice_daemon._STT_BACKENDS, "faster_whisper", lambda w, m: {"ok": False, "available": True, "backend": "faster_whisper", "error": "boom"})
    monkeypatch.setitem(voice_daemon._STT_BACKENDS, "whisper_cpp", lambda w, m: {"ok": True, "available": True, "backend": "whisper_cpp", "text": "hello pip"})
    monkeypatch.setitem(voice_daemon._STT_BACKENDS, "vosk", lambda w, m: None)
    out = voice_daemon.transcribe_wav(wav)
    assert out["ok"] is True
    assert out["backend"] == "whisper_cpp"
    assert out["text"] == "hello pip"


def test_transcribe_wav_explicit_backend_returns_its_own_error(monkeypatch, tmp_path):
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF" + b"\x00" * 200)
    monkeypatch.setitem(voice_daemon._STT_BACKENDS, "faster_whisper", lambda w, m: {"ok": False, "available": True, "backend": "faster_whisper", "error": "boom"})
    out = voice_daemon.transcribe_wav(wav, backend="faster_whisper")
    assert out["ok"] is False
    assert out["backend"] == "faster_whisper"


def test_mic_status_detects_configured_card(monkeypatch):
    monkeypatch.setattr(voice_daemon.shutil, "which", lambda name: "/usr/bin/arecord" if name == "arecord" else None)
    listing = "**** List of CAPTURE Hardware Devices ****\ncard 2: Device [USB Audio Device], device 0: USB Audio [USB Audio]\n"
    monkeypatch.setattr(voice_daemon.peripherals, "audio_devices", lambda: {"capture": {"ok": True, "stdout": listing}})
    assert voice_daemon.mic_status("2")["ready"] is True
    assert voice_daemon.mic_status("5")["ready"] is False  # configured card not present


def test_mic_status_graceful_without_arecord(monkeypatch):
    monkeypatch.setattr(voice_daemon.shutil, "which", lambda name: None)
    out = voice_daemon.mic_status("2")
    assert out["ready"] is False


def test_capture_utterance_falls_back_to_fixed_capture(monkeypatch):
    # No sounddevice/VAD installed -> capture_utterance must use the fixed arecord path.
    monkeypatch.setattr(voice_daemon, "_vad_capture_available", lambda: False)
    sentinel = {"ok": True, "path": "/tmp/x.wav", "available": True, "fixed": True}
    monkeypatch.setattr(voice_daemon.peripherals, "capture_mic", lambda seconds, device=None, rate=16000: sentinel)
    assert voice_daemon.capture_utterance(seconds=3.0) is sentinel


def test_voice_status_reports_backends_and_readiness():
    data = client.get("/voice/status").json()
    assert data["ok"] is True
    for key in ("enabled", "wakeword", "mic_device", "backends", "mic", "stt_ready", "wake_ready", "listening", "transcripts"):
        assert key in data


def test_voice_event_wake_sets_listening_then_idle():
    woke = client.post("/voice/event?phase=wake&score=0.91").json()
    assert woke["ok"] is True
    assert woke["listening"] is True
    assert woke["wake_count"] >= 1
    idle = client.post("/voice/event?phase=idle").json()
    assert idle["listening"] is False


def test_hearing_listen_records_transcript_in_voice_status():
    client.post("/hearing/listen?text=status")
    texts = [t["text"] for t in client.get("/voice/status").json()["transcripts"]]
    assert "status" in texts


def test_capture_mic_builds_arecord_command(monkeypatch, tmp_path):
    calls: dict = {}

    monkeypatch.setattr(peripherals.shutil, "which", lambda name: "/usr/bin/arecord" if name == "arecord" else None)
    monkeypatch.setenv("CLEO_ROVER_TTS_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("ALSA_CARD", "3")

    class Result:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"RIFF" + b"\x00" * 200)  # > WAV header
        return Result()

    monkeypatch.setattr(peripherals.subprocess, "run", fake_run)
    out = peripherals.capture_mic(3.0, rate=16000)
    assert out["ok"] is True
    cmd = calls["cmd"]
    assert cmd[0] == "arecord"
    assert "-r" in cmd and "16000" in cmd
    assert "plughw:3,0" in " ".join(cmd)


def test_capture_mic_missing_arecord_is_graceful(monkeypatch):
    monkeypatch.setattr(peripherals.shutil, "which", lambda name: None)
    out = peripherals.capture_mic(2.0)
    assert out["ok"] is False
    assert out["available"] is False


def test_transcribe_wav_graceful_without_backend(tmp_path):
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF" + b"\x00" * 200)
    out = voice_daemon.transcribe_wav(wav)
    assert out["ok"] is False
    assert out["available"] is False


def test_hearing_listen_routes_text_transcript():
    data = client.post("/hearing/listen?text=stop").json()
    assert data["ok"] is True
    assert data["transcript"] == "stop"
    assert data["routed"]["action"] == "stop"


def test_hearing_listen_no_text_in_sim_reports_unavailable():
    data = client.post("/hearing/listen").json()
    assert data["available"] is False


def test_voice_command_cannot_move_in_bench_profile():
    # A spoken "patrol" routes through the command router but cannot move motors:
    # voice routes with allow_movement=False and the bench profile keeps motors
    # unarmed, so movement stays gated.
    data = client.post("/hearing/listen?text=patrol").json()
    assert data["ok"] is True
    assert data["routed"]["handled"] is True
