"""A 'day in the life' of Pip: the arbiter narrative that proves the being LIVES.

Drives the pure decision core (arbitrate) through a scripted day so the full
behavior progression is verified deterministically: wake -> calm presence ->
curious patrol -> greet a person -> obey quiet hours -> low battery returns home
-> docked/charging stays put -> sleep. Plus one real in-sim tick to prove the
wiring runs end to end.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from rover.arbiter import (
    BEHAVIOR_OBSERVE,
    BEHAVIOR_PATROL,
    BEHAVIOR_REST,
    BEHAVIOR_RETURN_TO_CHARGER,
    BEHAVIOR_SOCIALIZE,
    arbitrate,
)
from rover import service

client = TestClient(service.app)


def _ctx(**over):
    base = dict(
        mode="social", awake=True, battery_recommendation="ok", battery_percent=80.0,
        battery_charging=False, energy=0.7, curiosity=0.3, boredom=0.2, has_goal=False,
        person_present=False, hazards_present=False, quiet=False, do_not_disturb=False,
        movement_allowed=True, dock_known=True, return_to_charger_min_battery=35.0,
    )
    base.update(over)
    return base


def test_morning_wakes_to_calm_presence():
    assert arbitrate(_ctx())["behavior"] == BEHAVIOR_OBSERVE


def test_gets_curious_and_patrols():
    assert arbitrate(_ctx(curiosity=0.8))["behavior"] == BEHAVIOR_PATROL


def test_greets_a_person():
    assert arbitrate(_ctx(person_present=True, curiosity=0.9))["behavior"] == BEHAVIOR_SOCIALIZE


def test_obeys_quiet_hours_over_curiosity():
    # Even curious, during quiet hours Pip only observes (obeys the owner).
    assert arbitrate(_ctx(curiosity=0.95, quiet=True))["behavior"] == BEHAVIOR_OBSERVE


def test_low_battery_returns_home():
    d = arbitrate(_ctx(battery_percent=20.0))
    assert d["behavior"] == BEHAVIOR_RETURN_TO_CHARGER


def test_critical_battery_returns_even_without_dock_known():
    d = arbitrate(_ctx(battery_recommendation="charge_before_movement", dock_known=False, movement_allowed=False))
    assert d["behavior"] == BEHAVIOR_RETURN_TO_CHARGER  # asks for help if it can't get there


def test_charging_stays_put_not_chasing_charger():
    # Docked + charging: do NOT drive off to "find" the charger even if % is low.
    d = arbitrate(_ctx(battery_percent=20.0, battery_charging=True))
    assert d["behavior"] != BEHAVIOR_RETURN_TO_CHARGER


def test_night_sleep_rests():
    assert arbitrate(_ctx(mode="sleep"))["behavior"] == BEHAVIOR_REST


def test_hazard_holds_before_any_motion():
    from rover.arbiter import BEHAVIOR_HOLD

    assert arbitrate(_ctx(hazards_present=True, curiosity=0.9))["behavior"] == BEHAVIOR_HOLD


def test_real_tick_runs_end_to_end_in_sim():
    # The wiring (context -> decision -> safe primitive -> history) actually runs.
    out = client.post("/pip/arbiter/tick?allow_movement=false").json()
    assert out["ok"] is True
    assert "decision" in out and "behavior" in out["decision"]
