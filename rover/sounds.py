"""R2-D2-style emotion chirps. Pip has a voice (TTS) but little wordless beeps are
a huge personality multiplier and read instantly across a room. Each emotion maps
to a short sequence of (frequency_hz, duration_ms) tones played through the same
USB speaker as TTS. The patterns are pure data (testable); playback uses
peripherals.play_tone and is a graceful no-op without an audio device."""

from __future__ import annotations

from typing import Any

from . import peripherals

# emotion -> [(hz, ms), ...]. Rising = positive, falling = sad, fast triplet = alert.
CHIRPS: dict[str, list[tuple[int, int]]] = {
    "happy": [(784, 90), (1047, 90), (1319, 130)],
    "greet": [(659, 80), (988, 80), (1319, 120)],
    "curious": [(659, 90), (988, 110)],
    "cat": [(1047, 70), (1319, 70), (1047, 90)],
    "alert": [(1568, 70), (1568, 70), (1568, 90)],
    "confused": [(740, 90), (523, 90), (740, 90)],
    "sad": [(659, 140), (440, 220)],
    "sleep": [(523, 160), (392, 240)],
    "proud": [(784, 90), (1047, 90), (1319, 90), (1568, 140)],
}

DEFAULT_EMOTION = "curious"


def chirp_pattern(emotion: str) -> list[tuple[int, int]]:
    """The (hz, ms) sequence for an emotion (falls back to a neutral chirp)."""
    return CHIRPS.get(str(emotion).lower(), CHIRPS[DEFAULT_EMOTION])


def play_chirp(emotion: str) -> dict[str, Any]:  # pragma: no cover - needs an audio device
    """Play an emotion chirp through the speaker. No-op-safe (returns ok=False) when
    aplay/the speaker isn't available, so it's harmless in sim/tests."""
    pattern = chirp_pattern(emotion)
    results = []
    for hz, ms in pattern:
        results.append(peripherals.play_tone(seconds=max(0.05, ms / 1000.0), hz=int(hz)))
    return {"ok": any(r.get("ok") for r in results), "emotion": emotion, "notes": len(pattern)}
