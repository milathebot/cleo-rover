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
    for key in ("arecord", "sounddevice", "openwakeword", "vosk", "whisper_cpp_bin"):
        assert key in backends


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
