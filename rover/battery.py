"""Honest battery state-of-charge + health for the Freenove 2S Li-ion pack.

Replaces the old linear 6.4-8.4V -> % guess (which both misreads the flat middle
of a Li-ion curve and browns out the Pi when voltage sags under motor load) with:

* the **verified ADS7830 front-end** (audit): pack volts = (raw/255 * coeff) * mult,
  where (coeff, mult) are **PCB-version paired** -- v1 = (3.3, x3), v2 = (5.2, x2).
  Hard-coding the v2 pair silently misread a v1 board by ~33% (audit HIGH-2), so
  the two are bound together here and selected by ``sensors.pcb_version``.
* a real **resting-voltage -> SOC curve** for 2S 18650 Li-ion (flat in the middle).
* a **sag-aware estimator**: SOC is only trusted from idle samples (the pack
  relaxes ~300ms after a drive pulse); in-motion readings are advisory, and the
  low-battery trip is **debounced** so a single in-motion dip never strands Pip.

Pure + no hardware imports; fully unit-tested. The estimator holds a little state
(EMA, charging trend, low-run counter) and is fed by the service heartbeat.
"""

from __future__ import annotations

from dataclasses import dataclass

# pcb_version -> (pin coefficient, divider multiplier). MUST be used as a pair.
ADC_PAIRS: dict[int, tuple[float, float]] = {1: (3.3, 3.0), 2: (5.2, 2.0)}

# Resting (no-load) pack-voltage -> SOC% for 2S 18650 Li-ion (descending volts).
SOC_CURVE: list[tuple[float, float]] = [
    (8.40, 100.0), (8.16, 90.0), (7.92, 75.0), (7.74, 60.0), (7.50, 50.0),
    (7.36, 40.0), (7.16, 30.0), (7.00, 20.0), (6.80, 10.0), (6.40, 5.0), (6.00, 0.0),
]

WARN_VOLTAGE = 7.0  # Freenove low-power beep point (NOT 6.4)
CRITICAL_VOLTAGE = 6.6  # debounced shutdown-protection trip


def adc_pair(pcb_version: int) -> tuple[float, float]:
    """(coeff, mult) for the ADS7830 battery channel, paired by PCB version."""
    return ADC_PAIRS.get(int(pcb_version), ADC_PAIRS[2])


def pack_voltage(pin_voltage: float | None, pcb_version: int) -> float | None:
    """Convert the ADS7830 channel-2 pin voltage (raw/255*coeff) to pack volts.

    ``pin_voltage`` must have been read with the matching ``coeff`` (see
    :func:`adc_pair`); this applies the divider multiplier. None passes through.
    """
    if pin_voltage is None:
        return None
    return round(float(pin_voltage) * adc_pair(pcb_version)[1], 2)


def voltage_to_soc(pack_v: float | None) -> float | None:
    """Interpolate the resting Li-ion curve. None on no reading (never fake 0)."""
    if pack_v is None:
        return None
    pts = SOC_CURVE
    if pack_v >= pts[0][0]:
        return 100.0
    if pack_v <= pts[-1][0]:
        return 0.0
    for (v_hi, p_hi), (v_lo, p_lo) in zip(pts, pts[1:]):
        if v_lo <= pack_v <= v_hi:
            frac = (pack_v - v_lo) / (v_hi - v_lo)
            return round(p_lo + frac * (p_hi - p_lo), 1)
    return None


@dataclass(frozen=True)
class BatteryReading:
    voltage: float | None  # measured pack volts (may be sagging)
    resting_voltage: float | None  # sag-compensated estimate
    soc_percent: float | None  # smoothed state of charge
    instantaneous_soc: float | None  # this-sample SOC (resting curve)
    charging: bool
    warn: bool  # at/below the low-power warn point
    critical: bool  # debounced critical trip -> return/charge now
    trusted: bool  # True only for idle samples (in-motion = advisory)
    note: str


class BatteryEstimator:
    """Stateful SOC/health tracker fed (voltage, motors_active, now) over time."""

    def __init__(
        self,
        *,
        warn_v: float = WARN_VOLTAGE,
        critical_v: float = CRITICAL_VOLTAGE,
        ema: float = 0.2,
        sag_k: float = 0.0,  # resting ~= measured + sag_k*|duty|; calibrate per pack
        low_debounce: int = 3,
        charge_rise_v: float = 0.05,
    ) -> None:
        self.warn_v = warn_v
        self.critical_v = critical_v
        self.ema = ema
        self.sag_k = sag_k
        self.low_debounce = low_debounce
        self.charge_rise_v = charge_rise_v
        self._ema_soc: float | None = None
        self._last_idle_v: float | None = None
        self._low_run = 0
        self._charging = False

    def update(self, *, voltage: float | None, motors_active: bool, duty: float = 0.0) -> BatteryReading:
        if voltage is None:
            # Don't advance debounce on a missing read; report unknown.
            return BatteryReading(None, None, self._ema_soc, None, self._charging, False, False, False, "no battery reading")

        # Sag compensation: under load the measured voltage dips; estimate the
        # resting voltage so SOC isn't pessimistic while driving.
        resting = voltage + (self.sag_k * abs(duty) if motors_active else 0.0)
        inst_soc = voltage_to_soc(resting)
        trusted = not motors_active

        if trusted and inst_soc is not None:
            self._ema_soc = inst_soc if self._ema_soc is None else (1 - self.ema) * self._ema_soc + self.ema * inst_soc
            if self._last_idle_v is not None:
                self._charging = (voltage - self._last_idle_v) > self.charge_rise_v
            self._last_idle_v = voltage

        # Debounced critical: only idle samples below the trip advance the counter.
        if trusted and resting is not None and resting < self.critical_v:
            self._low_run += 1
        else:
            self._low_run = 0
        critical = self._low_run >= self.low_debounce
        warn = resting is not None and resting < self.warn_v

        smoothed = round(self._ema_soc, 1) if self._ema_soc is not None else inst_soc
        note = "charging" if self._charging else ("critical" if critical else ("low" if warn else "ok"))
        if not trusted:
            note = f"in-motion (advisory); {note}"
        return BatteryReading(
            voltage=round(voltage, 2),
            resting_voltage=round(resting, 2) if resting is not None else None,
            soc_percent=smoothed,
            instantaneous_soc=inst_soc,
            charging=self._charging,
            warn=warn,
            critical=critical,
            trusted=trusted,
            note=note,
        )


def estimator_from(nav_or_life, *, sag_k: float = 0.0) -> BatteryEstimator:
    """Build an estimator (defaults are sensible; sag_k is calibrated on HW)."""
    return BatteryEstimator(sag_k=sag_k)
