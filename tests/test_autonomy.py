from fastapi.testclient import TestClient

from rover.service import app

client = TestClient(app)


def test_phase_a_event_model_records_recent_events():
    r = client.post("/events", json={"kind": "sound", "source": "test", "value": 0.7, "label": "clap"})
    assert r.status_code == 200
    assert r.json()["event"]["kind"] == "sound"

    recent = client.get("/events/recent?limit=1")
    assert recent.status_code == 200
    assert recent.json()["events"][0]["label"] == "clap"


def test_phase_b_autonomy_state_changes_from_stimulus():
    client.post("/events", json={"kind": "wake_word", "source": "test", "label": "cleo"})
    state = client.get("/autonomy/state").json()["state"]
    assert state["attention"] > 0.25
    assert state["mood"] in {"listening", "curious"}


def test_phase_c_behavior_library_reacts_to_wake_word():
    client.post("/heartbeat")
    client.post("/events", json={"kind": "wake_word", "source": "test", "label": "cleo"})
    r = client.post("/autonomy/tick", json={"allow_movement": False, "inject_idle_tick": False})
    assert r.status_code == 200
    data = r.json()
    assert data["decision"]["behavior"] in {"wake_response", "react_to_sound", "idle_presence", "hold"}
    if data["decision"]["behavior"] == "wake_response":
        assert "expression" in data["applied"]
        assert data["decision"]["speech"] == "I'm here."


def test_phase_d_hearing_simulation_hook():
    r = client.post("/hearing/simulate", json={"kind": "speech", "source": "sim_mic", "label": "voice", "value": 0.8})
    assert r.status_code == 200
    assert r.json()["event"]["kind"] == "speech"
    assert r.json()["state"]["attention"] >= 0.0


def test_phase_e_vision_snapshot_hook():
    r = client.post("/vision/snapshot", json={"kind": "motion", "source": "sim_camera", "payload": {"motion_seen": True}})
    assert r.status_code == 200
    data = r.json()
    assert data["event"]["kind"] == "motion"
    assert data["analysis_stub"]["motion_seen"] is True
    assert data["analysis_stub"]["needs_external_vision"] is True


def test_phase_f_limited_movement_stays_safely_unarmed_in_bench_mode():
    client.post("/hearing/simulate", json={"kind": "sound", "source": "sim_mic", "label": "tap", "value": 0.9})
    r = client.post("/autonomy/tick", json={"allow_movement": True, "inject_idle_tick": False})
    assert r.status_code == 200
    data = r.json()
    # Default config has bench_safe_no_motors true, so autonomy may decide to
    # react but must not apply real drive in bench mode.
    assert "drive" not in data["applied"]
    assert data["state"]["enabled"] is True
