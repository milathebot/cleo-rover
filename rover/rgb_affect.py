"""Emotion -> RGB expression for the 8-LED WS2812 strip.

With no display yet, the RGB strip is Pip's PRIMARY expression channel -- the
"is it alive?" signal. This maps Pip's affect (mood + energy/arousal + a few
状态 flags) to a colour + an animated brightness envelope (breathe / pulse /
flash), so the strip slowly breathes when calm and pulses when excited, flashes
on alert, and shows a steady low-battery amber that preempts everything.

Pure + side-effect-free: ``affect_to_frame`` returns a colour + a per-tick
brightness given a phase (0..1); the thin RGB loop in ``service.py`` advances the
phase and pushes frames to the hardware via ``set_rgb``. Verified hardware facts
(audit): WS2812, 8 LEDs, GRB order, brightness 0..255 (keep <= ~28 indoors), each
LED independently addressable (used for directional cues).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Base colour (full 0..255 RGB) per mood. Brightness is applied separately.
MOOD_COLORS: dict[str, tuple[int, int, int]] = {
    "calm": (0, 120, 160),       # teal
    "curious": (200, 120, 0),    # amber
    "happy": (0, 190, 70),       # green
    "playful": (170, 0, 170),    # magenta
    "excited": (255, 90, 0),     # hot orange
    "alert": (255, 30, 0),       # red
    "sad": (0, 40, 170),         # blue
    "lonely": (40, 0, 130),      # indigo
    "sleeping": (10, 0, 24),     # dim violet
    "low_power": (255, 120, 0),  # warning amber (audit override colour)
    "focused": (0, 80, 210),     # focused blue
    "proud": (120, 170, 0),      # lime
    "shy": (130, 40, 120),       # dusty pink
    "watching": (0, 140, 130),
}

PATTERN_SOLID = "solid"
PATTERN_BREATHE = "breathe"  # slow, calm
PATTERN_PULSE = "pulse"      # faster, energetic
PATTERN_FLASH = "flash"      # alert blink
CHARGING_COLOR = (0, 170, 50)


@dataclass(frozen=True)
class AffectFrame:
    color: tuple[int, int, int]  # full-scale RGB; brightness applied by the strip
    brightness: int              # this-tick brightness (0..max_brightness)
    pattern: str
    label: str


def affect_color(mood: str) -> tuple[int, int, int]:
    return MOOD_COLORS.get(str(mood), MOOD_COLORS["calm"])


def _envelope(pattern: str, phase: float, max_brightness: int) -> int:
    """Brightness for this tick given the pattern + phase (0..1 loops)."""
    p = phase % 1.0
    if pattern == PATTERN_BREATHE:
        frac = 0.35 + 0.65 * 0.5 * (1 + math.sin(2 * math.pi * p))
    elif pattern == PATTERN_PULSE:
        frac = 0.45 + 0.55 * 0.5 * (1 + math.sin(2 * math.pi * (p * 2)))  # ~2x faster
    elif pattern == PATTERN_FLASH:
        frac = 1.0 if p < 0.5 else 0.12
    else:  # solid
        frac = 1.0
    return max(0, min(max_brightness, int(round(max_brightness * frac))))


def affect_to_frame(
    mood: str,
    *,
    energy: float = 0.6,
    arousal: float | None = None,
    charging: bool = False,
    low_battery: bool = False,
    alert: bool = False,
    asleep: bool = False,
    max_brightness: int = 28,
    phase: float = 0.0,
) -> AffectFrame:
    """Map affect -> a colour + animated brightness + pattern. Priority overrides
    (low battery > alert > charging > sleep > mood) so safety/energy states win."""
    if low_battery:
        color, pattern, label = MOOD_COLORS["low_power"], PATTERN_PULSE, "low battery"
    elif alert:
        color, pattern, label = MOOD_COLORS["alert"], PATTERN_FLASH, "alert"
    elif charging:
        color, pattern, label = CHARGING_COLOR, PATTERN_BREATHE, "charging"
    elif asleep or mood == "sleeping":
        color, pattern, label = MOOD_COLORS["sleeping"], PATTERN_BREATHE, "sleeping"
    else:
        color = affect_color(mood)
        a = energy if arousal is None else arousal
        pattern = PATTERN_PULSE if a > 0.7 else PATTERN_BREATHE if a < 0.4 else PATTERN_SOLID
        label = str(mood)
    return AffectFrame(color=color, brightness=_envelope(pattern, phase, max_brightness), pattern=pattern, label=label)


def directional_pixels(
    color: tuple[int, int, int], bearing_deg: float, *, count: int = 8, brightness: int = 28, fov_deg: float = 90.0
) -> list[tuple[int, int, int]]:
    """Light the LEDs toward a bearing (a 'looking that way' cue) and dim the rest.

    Maps bearing in [-fov, +fov] across the strip; the nearest 3 LEDs glow, others
    are a dim tint. Each LED gets full RGB (the strip applies global brightness)."""
    idx = int(round((bearing_deg + fov_deg) / (2 * fov_deg) * (count - 1)))
    idx = max(0, min(count - 1, idx))
    bright = color
    dim = tuple(int(c * 0.12) for c in color)
    return [bright if abs(i - idx) <= 1 else dim for i in range(count)]  # type: ignore[misc]
