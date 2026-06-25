"""Tests for the RGB emotion-expression mapper."""

from __future__ import annotations

from rover.rgb_affect import (
    CHARGING_COLOR,
    MOOD_COLORS,
    PATTERN_BREATHE,
    PATTERN_FLASH,
    PATTERN_PULSE,
    PATTERN_SOLID,
    affect_color,
    affect_to_frame,
    directional_pixels,
)


def test_mood_maps_to_its_color():
    assert affect_to_frame("happy", energy=0.5).color == MOOD_COLORS["happy"]
    assert affect_color("curious") == MOOD_COLORS["curious"]
    assert affect_color("unknown-mood") == MOOD_COLORS["calm"]  # safe default


def test_low_battery_overrides_everything():
    f = affect_to_frame("happy", energy=0.9, charging=True, alert=True, low_battery=True)
    assert f.color == MOOD_COLORS["low_power"]
    assert f.label == "low battery"


def test_alert_beats_charging_and_mood():
    f = affect_to_frame("calm", alert=True, charging=True)
    assert f.color == MOOD_COLORS["alert"]
    assert f.pattern == PATTERN_FLASH


def test_charging_shows_charging_color():
    f = affect_to_frame("calm", charging=True)
    assert f.color == CHARGING_COLOR
    assert f.pattern == PATTERN_BREATHE


def test_energy_selects_pattern():
    assert affect_to_frame("curious", energy=0.9).pattern == PATTERN_PULSE   # excited
    assert affect_to_frame("curious", energy=0.2).pattern == PATTERN_BREATHE  # low
    assert affect_to_frame("curious", energy=0.55).pattern == PATTERN_SOLID   # mid


def test_brightness_envelope_animates_with_phase():
    # A breathing frame should change brightness across the phase cycle.
    b_low = affect_to_frame("calm", energy=0.2, max_brightness=28, phase=0.75).brightness   # trough
    b_high = affect_to_frame("calm", energy=0.2, max_brightness=28, phase=0.25).brightness   # peak
    assert b_high > b_low
    assert 0 <= b_low <= 28 and 0 <= b_high <= 28


def test_solid_is_full_brightness_regardless_of_phase():
    a = affect_to_frame("curious", energy=0.55, max_brightness=20, phase=0.1).brightness
    b = affect_to_frame("curious", energy=0.55, max_brightness=20, phase=0.9).brightness
    assert a == b == 20


def test_directional_pixels_lights_toward_bearing():
    px = directional_pixels((0, 200, 0), bearing_deg=80, count=8)
    assert len(px) == 8
    # Rightmost LEDs should be bright; leftmost dim.
    assert sum(px[-1]) > sum(px[0])
