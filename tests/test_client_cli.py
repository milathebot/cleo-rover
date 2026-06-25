"""Tests for the operator CLI argument -> HTTP payload mapping.

The CLI (`rover/client.py`) is the layer real operators drive over SSH, and it
had no coverage. These tests monkeypatch the network `request()` so we can assert
exactly which path/payload each subcommand sends, especially the hallway-scout
flags that the audit flagged as the buggy doorway path.
"""

from __future__ import annotations

import pytest

from rover import client as cli


def run_cli(monkeypatch, argv):
    """Run the CLI with the network call stubbed; return the recorded requests."""
    calls: list[dict] = []

    def fake_request(base, method, path, payload=None, timeout=5):
        calls.append({"base": base, "method": method, "path": path, "payload": payload, "timeout": timeout})
        return {"ok": True}

    monkeypatch.setattr(cli, "request", fake_request)
    rc = cli.main(argv)
    assert rc == 0
    return calls


def test_hallway_scout_flags_map_to_payload(monkeypatch):
    calls = run_cli(
        monkeypatch,
        [
            "hallway-scout",
            "--allow-movement",
            "--cycles", "12",
            "--vision-every", "2",
            "--blocked-cm", "42",
            "--clear-cm", "80",
            "--min-step-cm", "3",
            "--max-step-cm", "30",
            "--stride-chunk-cm", "8",
            "--scan-angles=-30,0,30",
            "--speak",
        ],
    )
    assert len(calls) == 1
    call = calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/tasks/hallway-scout"
    payload = call["payload"]
    assert payload["allow_movement"] is True
    assert payload["cycles"] == 12
    assert payload["vision_every"] == 2
    assert payload["blocked_cm"] == 42
    assert payload["clear_cm"] == 80
    assert payload["min_step_cm"] == 3
    assert payload["max_step_cm"] == 30
    assert payload["stride_chunk_cm"] == 8
    assert payload["scan_angles"] == [-30.0, 0.0, 30.0]
    assert payload["speak"] is True
    # Defaults that should hold unless explicitly disabled.
    assert payload["scan_before_move"] is True
    assert payload["adaptive_step"] is True
    assert payload["compact"] is True


def test_hallway_scout_disable_flags(monkeypatch):
    calls = run_cli(
        monkeypatch,
        ["hallway-scout", "--no-scan-before-move", "--fixed-step", "--verbose"],
    )
    payload = calls[0]["payload"]
    assert payload["allow_movement"] is False  # not passed
    assert payload["scan_before_move"] is False
    assert payload["adaptive_step"] is False
    assert payload["compact"] is False  # --verbose


def test_move_step_and_rotate_step_payloads(monkeypatch):
    move = run_cli(monkeypatch, ["move-step", "--forward-cm", "12"])[0]
    assert move["path"] == "/movement/move-step"
    assert move["payload"] == {"forward_cm": 12.0, "require_permission": True}

    move2 = run_cli(monkeypatch, ["move-step", "--forward-cm", "5", "--no-permission-required"])[0]
    assert move2["payload"]["require_permission"] is False

    rotate = run_cli(monkeypatch, ["rotate-step", "--deg", "20"])[0]
    assert rotate["path"] == "/movement/rotate-step"
    assert rotate["payload"] == {"deg": 20.0, "require_permission": True}


def test_body_intent_payload(monkeypatch):
    call = run_cli(monkeypatch, ["body-intent", "move_step", "--forward-cm", "10", "--mood", "focused"])[0]
    assert call["path"] == "/supervisor/intent"
    payload = call["payload"]
    assert payload["intent"] == "move_step"
    assert payload["mood"] == "focused"
    assert payload["params"]["forward_cm"] == 10.0
    assert payload["source"] == "cli"


def test_map_scan_angle_parsing(monkeypatch):
    call = run_cli(monkeypatch, ["map-scan", "--zone", "office", "--angles=-45,0,45", "--settle-ms", "200"])[0]
    assert call["path"] == "/map/scan"
    payload = call["payload"]
    assert payload["zone"] == "office"
    assert payload["angles"] == [-45.0, 0.0, 45.0]
    assert payload["settle_ms"] == 200


def test_say_payload_is_url_encoded_query(monkeypatch):
    call = run_cli(monkeypatch, ["say", "hello there pip"])[0]
    assert call["method"] == "POST"
    assert call["path"].startswith("/speech/say?text=")
    assert "hello" in call["path"]
