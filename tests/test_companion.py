"""Tests for the household-companion features: stairs safety (cliff-reflex
ask-to-be-carried), cat mode, proactive personality content + chirps, and the voice
mini-interactions + daily digest. Pure content/logic here; speech/RGB/Telegram are
side effects exercised only for graceful behavior."""

from __future__ import annotations

from fastapi.testclient import TestClient

from rover import arbiter, companion, notify, sounds
from rover.service import app

client = TestClient(app)


# --- pure personality content -------------------------------------------------


def test_carry_and_cat_lines_rotate():
    assert companion.carry_request_line(0) != companion.carry_request_line(1)
    assert isinstance(companion.cat_reaction_line(0), str) and companion.cat_reaction_line(0)


def test_proactive_line_is_context_sensitive():
    assert "cat" in companion.proactive_line(0, pet=True).lower()
    assert companion.proactive_line(0, person=True) == companion.PROACTIVE_PERSON
    assert "office" in companion.proactive_line(0, place="office").lower()
    # generic fallback rotates and ignores unknown places
    assert companion.proactive_line(0, place="unmapped") in companion.PROACTIVE_GENERIC


def test_greeting_line_is_time_aware():
    assert companion.greeting_line(8).startswith("Good morning")
    assert companion.greeting_line(14).startswith("Good afternoon")
    assert companion.greeting_line(19).startswith("Good evening")
    assert "Noot" in companion.greeting_line(8, name="Noot")


def test_cat_report_empty_and_present():
    assert "haven't" in companion.compose_cat_report([]).lower()
    report = companion.compose_cat_report([{"zone": "hallway", "age_s": 40}])
    assert "hallway" in report


def test_compose_digest_includes_real_signals():
    digest = companion.compose_digest({"summary": "A calm day."}, cat_sightings=2, places=3, battery_percent=77)
    assert "Pip's day" in digest
    assert "Cat sightings: 2" in digest
    assert "77%" in digest


def test_chirp_patterns_known_and_fallback():
    assert sounds.chirp_pattern("happy") == sounds.CHIRPS["happy"]
    assert sounds.chirp_pattern("totally-unknown") == sounds.CHIRPS[sounds.DEFAULT_EMOTION]


def test_notify_unavailable_without_creds(monkeypatch):
    monkeypatch.delenv("CLEO_ROVER_TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("CLEO_ROVER_TELEGRAM_ALLOWED_USER_ID", raising=False)
    assert notify.notify_available() is False
    out = notify.notify_owner("hi")
    assert out["ok"] is False and out["available"] is False


# --- arbiter: stairs behavior -------------------------------------------------


def test_edge_detected_requests_assist_over_everything_else():
    # Even with a person present and a goal, a detected edge wins (hold + ask).
    d = arbiter.arbitrate({"edge_detected": True, "person_present": True, "has_goal": True, "movement_allowed": True, "battery_percent": 90})
    assert d["behavior"] == arbiter.BEHAVIOR_REQUEST_ASSIST


# --- service wiring -----------------------------------------------------------


def test_voice_mini_interactions_are_handled():
    for text, action in [
        ("come here", "come"),
        ("what did you see today", "diary"),
        ("where are the cats", "cat_report"),
        ("tell me a joke", "joke"),
    ]:
        data = client.post("/pip/command", json={"text": text, "source": "test"}).json()
        assert data["handled"] is True, text
        assert data["action"] == action, text


def test_daily_digest_builds_without_sending():
    data = client.post("/pip/digest?send=false").json()
    assert data["ok"] is True
    assert "Pip's day" in data["digest"]
