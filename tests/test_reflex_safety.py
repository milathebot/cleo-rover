"""Tests for the cliff (downward IR) and bumper reflexes.

These are extra Pi-local emergency stops, peers of the ultrasonic reflex. They
are OFF by default (polarity/wiring must be verified on the robot) and must never
false-trigger on a normal floor.
"""

from __future__ import annotations

import asyncio

from rover.config import RoverConfig
from rover.drivers import RoverBody, should_bump_stop, should_cliff_stop
from rover.models import DriveCommand


def test_cliff_and_bump_disabled_by_default():
    edge = {"line_sensors": {"left": 1, "center": 1, "right": 1}}
    pressed = {"bumpers": {"left": 1, "right": 0}}
    assert should_cliff_stop(edge, enabled=False, drop_value=1) == (False, None)
    assert should_bump_stop(pressed, enabled=False) == (False, None)


def test_cliff_requires_all_sensors_to_read_drop():
    on_floor = {"line_sensors": {"left": 0, "center": 0, "right": 0}}
    one_dark_line = {"line_sensors": {"left": 0, "center": 1, "right": 0}}
    over_edge = {"line_sensors": {"left": 1, "center": 1, "right": 1}}
    assert should_cliff_stop(on_floor, enabled=True, drop_value=1)[0] is False
    # A single dark line under one sensor (line-following) is NOT a cliff.
    assert should_cliff_stop(one_dark_line, enabled=True, drop_value=1)[0] is False
    triggered, reason = should_cliff_stop(over_edge, enabled=True, drop_value=1)
    assert triggered is True and "cliff" in reason


def test_bump_triggers_on_press():
    assert should_bump_stop({"bumpers": {"left": 0, "right": 0}}, enabled=True)[0] is False
    triggered, reason = should_bump_stop({"bumpers": {"left": 1, "right": 0}}, enabled=True)
    assert triggered is True and "left" in reason


def test_forward_reflex_fires_on_cliff_when_enabled(monkeypatch):
    import rover.drivers as drivers

    class DummyHardware:
        def __init__(self, config):
            self.stopped = False

        def stop(self):
            self.stopped = True

        def drive(self, command):
            pass

    monkeypatch.setattr(drivers, "FreenoveHardware", DummyHardware)
    cfg = RoverConfig.model_validate(
        {"safety": {"bench_safe_no_motors": False, "cliff_reflex_enabled": True, "line_drop_value": 1}}
    )
    body = RoverBody(mode="hardware", config=cfg)
    assert body.motors_armed is True
    # Front is clear (ultrasonic would not stop), but the floor has dropped away.
    monkeypatch.setattr(
        body,
        "_sensor_snapshot",
        lambda: {"front_distance_cm": None, "line_sensors": {"left": 1, "center": 1, "right": 1}, "bumpers": None},
    )
    fired = asyncio.run(body._check_forward_reflex(DriveCommand(linear=0.3, turn=0, duration_ms=200), source="test"))
    assert fired is True
    assert body.state.last_reflex_stop["kind"] == "cliff"
    assert body.state.stopped is True


def test_forward_reflex_fails_closed_on_unknown_range(monkeypatch):
    import rover.drivers as drivers

    class DummyHardware:
        def __init__(self, config):
            pass

        def stop(self):
            pass

        def drive(self, command):
            pass

    monkeypatch.setattr(drivers, "FreenoveHardware", DummyHardware)
    body = RoverBody(mode="hardware", config=RoverConfig.model_validate({"safety": {"bench_safe_no_motors": False}}))
    monkeypatch.setattr(body, "_sensor_snapshot", lambda: {"front_distance_cm": None, "line_sensors": None, "bumpers": None})
    cmd = DriveCommand(linear=0.3, turn=0, duration_ms=200)
    # Tolerate brief dropouts, then fail CLOSED (default _max_none_range = 3).
    r1 = asyncio.run(body._check_forward_reflex(cmd, source="t"))
    r2 = asyncio.run(body._check_forward_reflex(cmd, source="t"))
    r3 = asyncio.run(body._check_forward_reflex(cmd, source="t"))
    assert (r1, r2) == (False, False)
    assert r3 is True
    assert body.state.last_reflex_stop["kind"] == "range_unknown"
    assert body.state.stopped is True


def test_forward_reflex_does_not_fire_on_normal_floor(monkeypatch):
    import rover.drivers as drivers

    class DummyHardware:
        def __init__(self, config):
            pass

        def stop(self):
            pass

        def drive(self, command):
            pass

    monkeypatch.setattr(drivers, "FreenoveHardware", DummyHardware)
    cfg = RoverConfig.model_validate(
        {"safety": {"bench_safe_no_motors": False, "cliff_reflex_enabled": True, "bumper_reflex_enabled": True, "line_drop_value": 1}}
    )
    body = RoverBody(mode="hardware", config=cfg)
    monkeypatch.setattr(
        body,
        "_sensor_snapshot",
        lambda: {"front_distance_cm": 150.0, "line_sensors": {"left": 0, "center": 0, "right": 0}, "bumpers": {"left": 0, "right": 0}},
    )
    fired = asyncio.run(body._check_forward_reflex(DriveCommand(linear=0.3, turn=0, duration_ms=200), source="test"))
    assert fired is False
