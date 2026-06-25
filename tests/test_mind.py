"""Tests for the deliberative LLM mind: parsing, clamping, and the Pi-validated
/mind/step loop with deterministic fallback. The LLM call is always mocked."""

from __future__ import annotations

from fastapi.testclient import TestClient

from rover import mind
from rover.models import BodyIntentCommand
from rover.service import app
from rover.supervisor import validate_intent

client = TestClient(app)


def test_move_step_rejected_when_turret_panned():
    cmd = BodyIntentCommand(intent="move_step", params={"forward_cm": 8})
    sensors = {"front_distance_cm": 200, "front_stop_distance_cm": 30}
    movement = {"active": True}
    panned = {"motors_armed": True, "safety": {"bench_safe_no_motors": False}, "turret": {"pan_deg": 40}}
    ok, reason = validate_intent(cmd, status=panned, sensors=sensors, movement=movement)
    assert ok is False and "turret" in reason
    centered = {"motors_armed": True, "safety": {"bench_safe_no_motors": False}, "turret": {"pan_deg": 0}}
    ok2, _ = validate_intent(cmd, status=centered, sensors=sensors, movement=movement)
    assert ok2 is True


def test_parse_intent_variants():
    assert mind.parse_intent('{"intent": "scan"}')["intent"] == "scan"
    assert mind.parse_intent("```json\n{\"intent\": \"stop\"}\n```")["intent"] == "stop"
    assert mind.parse_intent('Sure! {"intent": "look", "params": {"pan_deg": 20}} done')["intent"] == "look"
    assert mind.parse_intent("no json at all") is None


def test_clamp_intent_bounds_and_allowlist():
    moved = mind.clamp_intent({"intent": "move_step", "params": {"forward_cm": 999}})
    assert moved["intent"] == "move_step" and moved["params"]["forward_cm"] == 12.0
    rot = mind.clamp_intent({"intent": "rotate_step", "params": {"deg": -999}})
    assert rot["params"]["deg"] == -35.0
    assert mind.clamp_intent({"intent": "launch_rockets"})["intent"] == "idle"
    assert mind.clamp_intent({"intent": "mood", "mood": "NOPE"})["mood"] is None
    # Unknown param keys are dropped.
    looked = mind.clamp_intent({"intent": "look", "params": {"pan_deg": 30, "danger": 1}})
    assert "danger" not in looked["params"]


def test_mind_status_endpoint():
    r = client.get("/mind/status")
    assert r.status_code == 200
    assert "move_step" in r.json()["allowed_intents"]


def test_mind_step_deterministic_when_unconfigured(monkeypatch):
    monkeypatch.setattr(mind, "mind_configured", lambda: False)
    data = client.post("/mind/step?zone=office").json()
    assert data["mind_used"] is False
    assert data["source"] == "deterministic"
    assert data["ok"] is True


def test_mind_step_accepts_safe_mind_intent(monkeypatch):
    monkeypatch.setattr(mind, "mind_configured", lambda: True)
    monkeypatch.setattr(
        mind,
        "ask_mind_for_intent",
        lambda **_: {"ok": True, "intent": {"intent": "mood", "mood": "focused", "speech": "thinking", "params": {}}},
    )
    data = client.post("/mind/step?zone=office").json()
    assert data["source"] == "mind"
    assert data["mind_used"] is True
    assert data["result"]["accepted"] is True


def test_mind_step_refused_intent_falls_back_to_deterministic(monkeypatch):
    monkeypatch.setattr(mind, "mind_configured", lambda: True)
    # move_step is refused in the bench profile (no grant + motors unarmed), so the
    # Pi safety gate rejects the mind's intent and Pip uses the deterministic policy.
    monkeypatch.setattr(
        mind,
        "ask_mind_for_intent",
        lambda **_: {"ok": True, "intent": {"intent": "move_step", "params": {"forward_cm": 10}}},
    )
    data = client.post("/mind/step?zone=office").json()
    assert data["source"] == "deterministic_fallback"
    assert data["mind_used"] is True
    assert "mind_refused" in data


def test_mind_step_falls_back_on_mind_error(monkeypatch):
    monkeypatch.setattr(mind, "mind_configured", lambda: True)
    monkeypatch.setattr(mind, "ask_mind_for_intent", lambda **_: {"ok": False, "error": "boom"})
    data = client.post("/mind/step?zone=office").json()
    assert data["source"] == "deterministic_fallback"
    assert data["mind_error"] == "boom"


def test_mind_env_fallback_precedence(monkeypatch):
    # The project-prefixed CLEO_ROVER_HERMES_* names (same ones the Telegram agent +
    # vision-label use) configure the mind, so one cred set wires the whole rover.
    for var in (
        "MIND_API_BASE", "MIND_API_KEY", "MIND_MODEL",
        "HERMES_API_BASE", "HERMES_API_KEY", "HERMES_MODEL",
        "CLEO_ROVER_HERMES_API_BASE", "CLEO_ROVER_HERMES_API_KEY", "CLEO_ROVER_HERMES_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)

    assert mind.mind_configured() is False

    monkeypatch.setenv("CLEO_ROVER_HERMES_API_BASE", "http://pi-host:8642/v1")
    monkeypatch.setenv("CLEO_ROVER_HERMES_API_KEY", "k-cleo")
    monkeypatch.setenv("CLEO_ROVER_HERMES_MODEL", "cleo-model")  # distinct from the "hermes-agent" default
    assert mind.mind_configured() is True
    base, key, model = mind._endpoint()
    assert base == "http://pi-host:8642/v1" and key == "k-cleo" and model == "cleo-model"

    # HERMES_* and MIND_* take precedence over CLEO_ROVER_HERMES_* when present.
    monkeypatch.setenv("HERMES_API_BASE", "http://hermes:9000/v1")
    monkeypatch.setenv("HERMES_API_KEY", "k-hermes")
    monkeypatch.setenv("HERMES_MODEL", "hermes-model")
    assert mind._endpoint() == ("http://hermes:9000/v1", "k-hermes", "hermes-model")
    monkeypatch.setenv("MIND_API_BASE", "http://gateway:7000/v1")
    monkeypatch.setenv("MIND_API_KEY", "k-mind")
    monkeypatch.setenv("MIND_MODEL", "mind-model")
    assert mind._endpoint() == ("http://gateway:7000/v1", "k-mind", "mind-model")
