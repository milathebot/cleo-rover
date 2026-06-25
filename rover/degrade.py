"""Graceful-degradation matrix: one authority for "what can Pip safely do now?".

Each advisory/safety layer can independently stop Pip, but nothing aggregated the
*why* into a single capability level. This pure module maps the current fault/
state flags to a capability tier so the composite health view, the operator UI,
and the RGB affect all agree on one answer (and Pip degrades gracefully instead of
silently freezing). It NEVER grants capability the safety floor wouldn't — it can
only ever reduce what Pip will attempt.

Levels (most-capable first):
* ``full``        drive + scan + turret (all good).
* ``scan_only``   may pan + ultrasonic-scan, but not drive (e.g. disarmed/critical).
* ``turret_only`` may pan to look, but the ultrasonic is unreliable -> no scan-nav.
* ``stopped``     do nothing right now (a fresh reflex / emergency).
"""

from __future__ import annotations

from dataclasses import dataclass

LEVEL_FULL = "full"
LEVEL_SCAN_ONLY = "scan_only"
LEVEL_TURRET_ONLY = "turret_only"
LEVEL_STOPPED = "stopped"


@dataclass(frozen=True)
class Degradation:
    level: str
    allow_drive: bool
    allow_scan: bool
    allow_turret: bool
    reasons: list[str]

    def as_dict(self) -> dict:
        return {
            "level": self.level,
            "allow_drive": self.allow_drive,
            "allow_scan": self.allow_scan,
            "allow_turret": self.allow_turret,
            "reasons": self.reasons,
        }


def assess_degradation(
    *,
    motors_armed: bool,
    bench_safe: bool,
    ultrasonic_ready: bool,
    battery_critical: bool = False,
    reflex_active: bool = False,
    thermal_hot: bool = False,
    mind_required: bool = False,
    mind_ok: bool = True,
) -> Degradation:
    """Reduce the current state to a single capability tier + the reasons for it."""
    reasons: list[str] = []
    allow_drive = True
    allow_scan = True
    allow_turret = True

    # A fresh reflex / emergency -> stop everything this instant.
    if reflex_active:
        reasons.append("reflex stop active")
        return Degradation(LEVEL_STOPPED, False, False, False, reasons)

    # Things that forbid DRIVING but still allow looking/scanning.
    if bench_safe or not motors_armed:
        allow_drive = False
        reasons.append("motors disarmed / bench-safe")
    if battery_critical:
        allow_drive = False
        reasons.append("battery critical")
    if thermal_hot:
        allow_drive = False
        reasons.append("cpu thermal limit")
    if mind_required and not mind_ok:
        allow_drive = False
        reasons.append("required mind offline")

    # The ultrasonic is the forward sense AND the scanner: if it's down, no scan
    # and no driving (Pip can still pan the turret to look around).
    if not ultrasonic_ready:
        allow_scan = False
        allow_drive = False
        reasons.append("ultrasonic not ready")

    if not allow_scan:
        level = LEVEL_TURRET_ONLY
    elif not allow_drive:
        level = LEVEL_SCAN_ONLY
    else:
        level = LEVEL_FULL
    if not reasons:
        reasons.append("all systems nominal")
    return Degradation(level, allow_drive, allow_scan, allow_turret, reasons)
