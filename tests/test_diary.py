"""Tests for Pip's diary (truthful narrated inner life)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from rover.diary import compose_diary
from rover.service import app

client = TestClient(app)


def test_diary_reflects_mood_and_energy():
    d = compose_diary(feelings={"mood": "curious", "energy": 0.8}, recent_events=[], facts=[], place_count=0)
    assert "curious" in d["mood_line"]
    assert "80%" in d["mood_line"]


def test_diary_narrates_recent_behaviors():
    events = [{"label": "arbiter:patrol"}, {"label": "arbiter:patrol"}, {"label": "arbiter:socialize"}]
    d = compose_diary(feelings={"mood": "happy", "energy": 0.6}, recent_events=events, facts=[], place_count=2)
    text = d["summary"].lower()
    assert "wander" in text or "curious" in text  # patrol phrasing
    assert "hello" in text  # socialize phrasing
    assert "2 places" in text


def test_diary_surfaces_learned_facts():
    facts = [{"subject": "charger", "object": "office", "confidence": 0.9, "detail": "near north wall"}]
    d = compose_diary(feelings={"mood": "calm", "energy": 0.5}, recent_events=[], facts=facts, place_count=1)
    assert "charger" in d["summary"] and "office" in d["summary"]


def test_diary_mentions_low_battery():
    d = compose_diary(feelings={"mood": "low_power", "energy": 0.2}, recent_events=[], facts=[], place_count=0, battery_percent=18.0)
    assert "charger" in d["summary"].lower()


def test_diary_charging_line():
    d = compose_diary(feelings={"mood": "calm", "energy": 0.5}, recent_events=[], facts=[], place_count=0, charging=True)
    assert "charging" in d["summary"].lower()


def test_diary_quiet_when_nothing_happened():
    d = compose_diary(feelings={"mood": "calm", "energy": 0.6}, recent_events=[], facts=[], place_count=0)
    assert len(d["lines"]) >= 2  # mood line + a "quiet stretch" line


def test_diary_endpoint():
    data = client.get("/life/diary").json()
    assert data["ok"] is True
    assert "summary" in data and isinstance(data["lines"], list) and data["lines"]
