from fastapi.testclient import TestClient

from rover.models import ExpressionCommand, ExpressionMode
from rover.renderer import render_expression
from rover.service import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_operator_panel():
    r = client.get("/")
    assert r.status_code == 200
    assert "Cleo Rover Mk1" in r.text
    assert "/expression/preview.png" in r.text


def test_expression_and_status():
    r = client.post("/expression", json={"mode": "listening", "text": "yes?", "brightness": 0.4})
    assert r.status_code == 200
    status = client.get("/status").json()
    assert status["expression"]["mode"] == "listening"
    assert status["expression"]["text"] == "yes?"


def test_expression_preview_png():
    client.post("/expression", json={"mode": "thinking", "text": "boot", "brightness": 0.5})
    r = client.get("/expression/preview.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")


def test_renderer_size():
    frame = render_expression(ExpressionCommand(mode=ExpressionMode.idle, text="Cleo", brightness=0.6), t=1.0)
    assert frame.image.size == (240, 320)
    assert frame.png_bytes().startswith(b"\x89PNG")


def test_drive_validation():
    r = client.post("/drive", json={"linear": 2, "turn": 0, "duration_ms": 250})
    assert r.status_code == 422


def test_stop():
    client.post("/drive", json={"linear": 0.2, "turn": 0, "duration_ms": 500})
    r = client.post("/stop")
    assert r.status_code == 200
    assert r.json()["stopped"] is True
