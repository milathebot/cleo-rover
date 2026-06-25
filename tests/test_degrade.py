"""Tests for the graceful-degradation matrix."""

from __future__ import annotations

from rover.degrade import (
    LEVEL_FULL,
    LEVEL_SCAN_ONLY,
    LEVEL_STOPPED,
    LEVEL_TURRET_ONLY,
    assess_degradation,
)


def test_all_good_is_full():
    d = assess_degradation(motors_armed=True, bench_safe=False, ultrasonic_ready=True)
    assert d.level == LEVEL_FULL
    assert d.allow_drive and d.allow_scan and d.allow_turret


def test_disarmed_is_scan_only():
    d = assess_degradation(motors_armed=False, bench_safe=True, ultrasonic_ready=True)
    assert d.level == LEVEL_SCAN_ONLY
    assert d.allow_drive is False
    assert d.allow_scan is True and d.allow_turret is True


def test_battery_critical_blocks_drive():
    d = assess_degradation(motors_armed=True, bench_safe=False, ultrasonic_ready=True, battery_critical=True)
    assert d.allow_drive is False
    assert "battery critical" in d.reasons


def test_dead_ultrasonic_is_turret_only():
    d = assess_degradation(motors_armed=True, bench_safe=False, ultrasonic_ready=False)
    assert d.level == LEVEL_TURRET_ONLY
    assert d.allow_scan is False and d.allow_drive is False
    assert d.allow_turret is True  # can still pan to look around


def test_reflex_active_stops_everything():
    d = assess_degradation(motors_armed=True, bench_safe=False, ultrasonic_ready=True, reflex_active=True)
    assert d.level == LEVEL_STOPPED
    assert not (d.allow_drive or d.allow_scan or d.allow_turret)


def test_thermal_and_required_mind_block_drive():
    d = assess_degradation(motors_armed=True, bench_safe=False, ultrasonic_ready=True, thermal_hot=True, mind_required=True, mind_ok=False)
    assert d.level == LEVEL_SCAN_ONLY
    assert any("thermal" in r for r in d.reasons)
    assert any("mind offline" in r for r in d.reasons)


def test_reasons_never_empty():
    d = assess_degradation(motors_armed=True, bench_safe=False, ultrasonic_ready=True)
    assert d.reasons  # at least "all systems nominal"
