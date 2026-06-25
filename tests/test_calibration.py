"""Tests for the bring-up calibration helper + readiness gates."""

from __future__ import annotations

from fastapi.testclient import TestClient

from rover.calibration import CHECKLIST, autonomy_gates
from rover.service import app

client = TestClient(app)


def _sensors(*, us=True, line=True, adc=True):
    return {"ultrasonic_ready": us, "line_sensors_ready": line, "adc_ready": adc}


def test_checklist_is_ordered_and_covers_key_steps():
    steps = [c["step"] for c in CHECKLIST]
    assert steps == sorted(steps)
    titles = " ".join(c["title"].lower() for c in CHECKLIST)
    assert "pcb version" in titles and "turret pan" in titles and "ir line" in titles


def test_gates_pass_when_sensors_ready_and_battery_plausible():
    g = autonomy_gates(sensors=_sensors(), battery_voltage=7.6, pcb_version=2)
    assert g["ready_for_supervised_drive"] is True
    assert all(g["gates"].values())


def test_implausible_battery_blocks_drive():
    g = autonomy_gates(sensors=_sensors(), battery_voltage=12.4, pcb_version=2)  # wrong divider
    assert g["gates"]["battery_plausible"] is False
    assert g["ready_for_supervised_drive"] is False


def test_dead_ultrasonic_blocks_drive():
    g = autonomy_gates(sensors=_sensors(us=False), battery_voltage=7.6)
    assert g["ready_for_supervised_drive"] is False


def test_none_battery_is_not_plausible():
    g = autonomy_gates(sensors=_sensors(), battery_voltage=None)
    assert g["gates"]["battery_plausible"] is False


def test_calibration_endpoint_serves_checklist_and_gates():
    data = client.get("/calibration").json()
    assert data["ok"] is True
    assert len(data["checklist"]) >= 10
    assert "ready_for_supervised_drive" in data
    assert "gates" in data


def test_battery_endpoint_reports_soc():
    data = client.get("/battery").json()
    assert data["ok"] is True
    assert "soc_percent" in data and "critical" in data


def test_rgb_affect_endpoint_returns_a_frame():
    data = client.get("/pip/rgb-affect").json()
    assert data["ok"] is True
    assert len(data["color"]) == 3
    assert data["pattern"] in ("solid", "breathe", "pulse", "flash")


def test_return_home_plan_only_without_movement():
    data = client.post("/tasks/return-home", params={"goal": "charger", "allow_movement": False}).json()
    # No topo nodes yet in a fresh store may make this unrouTable; either way it's graceful.
    assert "ok" in data
