"""Power-up bring-up + calibration helper for the FNK0043.

Turns the hardware-audit checklist into something Pip can self-report: the ordered
manual steps the owner does once, plus the subset that can be auto-checked from
the running service (sensor readiness, plausible battery, ADC) to gate autonomy.

Pure data + a pure ``autonomy_gates`` evaluator (unit-tested); the service exposes
it at ``/calibration``.
"""

from __future__ import annotations

from typing import Any

# Ordered bring-up checklist (from the FNK0043 audit). Each step has the manual
# action and which automatable gate (if any) confirms it.
CHECKLIST: list[dict[str, Any]] = [
    {"step": 1, "title": "I2C presence", "how": "i2cdetect -y 1 -> expect 0x40 (PCA9685) and 0x48 (ADS7830)", "gate": "adc_ready"},
    {"step": 2, "title": "PCB version", "how": "read silkscreen / params.json Pcb_Version; set sensors.pcb_version (v1=>coeff3.3/x3, v2=>5.2/x2)", "gate": None},
    {"step": 3, "title": "Battery divider", "how": "multimeter the pack at idle vs /battery voltage; if API reads ~33% high you are on v1", "gate": "battery_plausible"},
    {"step": 4, "title": "Motor direction", "how": "command forward; confirm all 4 wheels roll forward (else channel-pair wiring swapped)", "gate": None},
    {"step": 5, "title": "Turret pan direction", "how": "command pan +30deg; sonar must rotate to the RIGHT (confirms the inverted-pan fix)", "gate": None},
    {"step": 6, "title": "Turret center + clearance", "how": "pan/tilt 0deg = forward; hand-cycle to +/-70deg, confirm no cable/chassis binding", "gate": None},
    {"step": 7, "title": "Ultrasonic latency", "how": "time 50 .distance reads; set ping_latency_ms/cruise_react_ms from measured latency", "gate": "ultrasonic_ready"},
    {"step": 8, "title": "IR line polarity", "how": "read over white floor (0), black tape (1), table-edge void (record) -> set safety.line_drop_value", "gate": "line_sensors_ready"},
    {"step": 9, "title": "Coast distance", "how": "duty 0.3, let it coast to stop, measure cm -> set nav.cruise_coast_cm", "gate": None},
    {"step": 10, "title": "Odometry", "how": "UMBmark square + tape measure -> tune odometry.cm_s_per_duty (~33) + deg_s_per_turn_duty (~200)", "gate": None},
    {"step": 11, "title": "RGB", "how": "confirm dtparam=spi=on; set a red frame -> strip lights red (GRB order)", "gate": None},
    {"step": 12, "title": "Enable reflexes LAST", "how": "after 5 & 8 pass, set cliff_reflex_enabled=true (measured line_drop_value); leave bumper_reflex off until switches verified", "gate": None},
]


def autonomy_gates(*, sensors: dict[str, Any], battery_voltage: float | None, pcb_version: int = 2) -> dict[str, Any]:
    """Evaluate the auto-checkable readiness gates from a live sensor snapshot.

    These are necessary-not-sufficient: the manual steps (motor/turret direction,
    coast, IR polarity) still gate a real drive, but these catch dead/missing
    sensors before Pip is trusted to move.
    """
    ultrasonic_ready = bool(sensors.get("ultrasonic_ready"))
    line_ready = bool(sensors.get("line_sensors_ready"))
    adc_ready = bool(sensors.get("adc_ready"))
    # A 2S pack at rest sits ~6.0-8.6V; outside that the divider/pcb_version is wrong.
    battery_plausible = battery_voltage is not None and 5.8 <= float(battery_voltage) <= 8.7
    gates = {
        "ultrasonic_ready": ultrasonic_ready,
        "line_sensors_ready": line_ready,
        "adc_ready": adc_ready,
        "battery_plausible": battery_plausible,
    }
    # Drive readiness needs the senses that keep Pip safe; battery just needs to read.
    ready_for_supervised_drive = ultrasonic_ready and adc_ready and battery_plausible
    return {
        "gates": gates,
        "ready_for_supervised_drive": ready_for_supervised_drive,
        "pcb_version": pcb_version,
        "note": "Auto gates are necessary, not sufficient: complete the manual checklist (esp. turret pan direction + IR polarity) before enabling reflexes/cruise.",
    }
