from pathlib import Path

from rover import peripherals


def test_cloud_tts_uses_openai_compatible_speech_endpoint(monkeypatch, tmp_path):
    captured = {}

    class DummyResp:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"RIFF" + b"0" * 256

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["data"] = req.data
        captured["timeout"] = timeout
        return DummyResp()

    monkeypatch.setenv("CLEO_ROVER_TTS_API_BASE", "https://tts.example/v1")
    monkeypatch.setenv("CLEO_ROVER_TTS_API_KEY", "secret-test-key")
    monkeypatch.setenv("CLEO_ROVER_TTS_MODEL", "nice-tts")
    monkeypatch.setenv("CLEO_ROVER_TTS_VOICE", "pip")
    monkeypatch.setenv("CLEO_ROVER_TTS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(peripherals.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(peripherals, "play_audio_file", lambda path, timeout=20: {"ok": True, "path": str(path)})

    result = peripherals.cloud_tts_speech("hi pip")
    assert result is not None
    assert result["ok"] is True
    assert result["tool"] == "cloud_tts"
    assert result["model"] == "nice-tts"
    assert result["voice"] == "pip"
    assert captured["url"] == "https://tts.example/v1/audio/speech"
    assert result["path"].endswith(".wav")
    assert Path(result["path"]).exists()


def test_speak_text_falls_back_when_no_cloud_or_command(monkeypatch):
    monkeypatch.delenv("CLEO_ROVER_TTS_API_BASE", raising=False)
    monkeypatch.delenv("CLEO_ROVER_TTS_API_KEY", raising=False)
    monkeypatch.delenv("CLEO_ROVER_TTS_COMMAND", raising=False)
    monkeypatch.setattr(peripherals.shutil, "which", lambda name: None)
    monkeypatch.setattr(peripherals, "play_tone", lambda seconds, hz: {"ok": True, "tone": hz})

    result = peripherals.speak_text("hello")
    assert result["ok"] is False
    assert result["error"] == "no espeak/espeak-ng found"
    assert result["tone"]["ok"] is True


def test_command_tts_hook_generates_and_plays(monkeypatch, tmp_path):
    def fake_run(cmd, capture_output, text, timeout, check):
        out = Path(cmd[-1])
        out.write_bytes(b"RIFF" + b"1" * 256)
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setenv("CLEO_ROVER_TTS_COMMAND", "fake-tts --text {text} --output {output}")
    monkeypatch.setenv("CLEO_ROVER_TTS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(peripherals.subprocess, "run", fake_run)
    monkeypatch.setattr(peripherals, "play_audio_file", lambda path, timeout=20: {"ok": True, "path": str(path)})

    result = peripherals.command_tts_speech("hello creature")
    assert result is not None
    assert result["ok"] is True
    assert result["tool"] == "command_tts"
    assert "hello creature" in result["cmd"]
