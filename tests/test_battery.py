"""Tests for the battery SOC curve + sag-aware estimator + PCB-paired ADC."""

from __future__ import annotations

from rover.battery import (
    BatteryEstimator,
    adc_pair,
    pack_voltage,
    voltage_to_soc,
)


def test_adc_pair_is_version_bound():
    assert adc_pair(2) == (5.2, 2.0)
    assert adc_pair(1) == (3.3, 3.0)
    assert adc_pair(99) == (5.2, 2.0)  # unknown -> safe v2 default


def test_pack_voltage_applies_paired_multiplier():
    # pin voltage already = raw/255*coeff; pack = pin * multiplier.
    assert pack_voltage(4.0, 2) == 8.0   # v2 x2
    assert pack_voltage(2.6, 1) == 7.8   # v1 x3
    assert pack_voltage(None, 2) is None


def test_soc_curve_endpoints_and_midpoint():
    assert voltage_to_soc(8.5) == 100.0   # clamp high
    assert voltage_to_soc(5.5) == 0.0     # clamp low
    assert voltage_to_soc(7.5) == 50.0    # exact breakpoint
    assert voltage_to_soc(None) is None


def test_soc_curve_is_nonlinear_flat_middle():
    # The Li-ion curve is flat in the middle: a 0.4V drop high vs low yields very
    # different SOC deltas (unlike the old linear map).
    high_delta = voltage_to_soc(8.40) - voltage_to_soc(8.00)
    mid_delta = voltage_to_soc(7.60) - voltage_to_soc(7.20)
    assert mid_delta != high_delta


def test_soc_interpolates_between_breakpoints():
    soc = voltage_to_soc(8.04)  # between 8.16(90) and 7.92(75)
    assert 75.0 < soc < 90.0


def test_estimator_trusts_idle_not_in_motion():
    est = BatteryEstimator()
    moving = est.update(voltage=7.4, motors_active=True)
    assert moving.trusted is False
    assert "advisory" in moving.note
    idle = est.update(voltage=7.4, motors_active=False)
    assert idle.trusted is True
    assert idle.soc_percent is not None


def test_estimator_debounces_critical():
    est = BatteryEstimator(critical_v=6.6, low_debounce=3)
    # One in-motion dip below critical must NOT trip.
    assert est.update(voltage=6.4, motors_active=True).critical is False
    # Idle samples below critical accumulate; trips on the 3rd.
    assert est.update(voltage=6.4, motors_active=False).critical is False
    assert est.update(voltage=6.4, motors_active=False).critical is False
    assert est.update(voltage=6.4, motors_active=False).critical is True


def test_estimator_resets_low_run_on_recovery():
    est = BatteryEstimator(critical_v=6.6, low_debounce=3)
    est.update(voltage=6.4, motors_active=False)
    est.update(voltage=6.4, motors_active=False)
    est.update(voltage=7.6, motors_active=False)  # recovered
    assert est.update(voltage=6.4, motors_active=False).critical is False  # counter reset


def test_estimator_detects_sustained_charging():
    est = BatteryEstimator(charge_rise_v=0.03, charge_confirm=3)
    r = None
    for v in (7.0, 7.2, 7.4, 7.6, 7.8):  # a real charging ramp
        r = est.update(voltage=v, motors_active=False)
    assert r.charging is True


def test_estimator_no_charging_on_single_sag_rebound():
    # A low pack that rebounds once after a drive must NOT read as charging, or it
    # would suppress return-to-charger and strand Pip (safety bug from review).
    est = BatteryEstimator(charge_rise_v=0.03, charge_confirm=3, critical_v=6.6)
    est.update(voltage=6.5, motors_active=False)
    est.update(voltage=6.2, motors_active=True)   # drive (sag, ignored)
    r = est.update(voltage=6.6, motors_active=False)  # single rebound rise
    assert r.charging is False


def test_estimator_not_charging_while_low_even_if_rising():
    est = BatteryEstimator(charge_rise_v=0.03, charge_confirm=2, critical_v=6.6)
    r = None
    for v in (6.0, 6.2, 6.4):  # rising but still below critical
        r = est.update(voltage=v, motors_active=False)
    assert r.charging is False  # never "charging" while genuinely low


def test_estimator_none_voltage_is_unknown_not_zero():
    est = BatteryEstimator()
    r = est.update(voltage=None, motors_active=False)
    assert r.soc_percent is None
    assert r.critical is False
