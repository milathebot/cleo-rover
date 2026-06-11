from fastapi.testclient import TestClient

from rover.service import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_expression_and_status():
    r = client.post("/expression", json={"mode": "listening", "text": "yes?", "brightness": 0.4})
    assert r.status_code == 200
    status = client.get("/status").json()
    assert status["expression"]["mode"] == "listening"
    assert status["expression"]["text"] == "yes?"


def test_drive_validation():
    r = client.post("/drive", json={"linear": 2, "turn": 0, "duration_ms": 250})
    assert r.status_code == 422


def test_stop():
    client.post("/drive", json={"linear": 0.2, "turn": 0, "duration_ms": 500})
    r = client.post("/stop")
    assert r.status_code == 200
    assert r.json()["stopped"] is True
