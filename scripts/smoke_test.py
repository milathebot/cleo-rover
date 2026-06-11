#!/usr/bin/env python3
from __future__ import annotations

import json
import time
import urllib.request

BASE = "http://127.0.0.1:8099"


def request(method: str, path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


print("health", request("GET", "/health"))
print("expression", request("POST", "/expression", {"mode": "thinking", "text": "booting", "brightness": 0.5}))
print("turret", request("POST", "/turret", {"pan_deg": 20}))
print("drive", request("POST", "/drive", {"linear": 0.2, "turn": 0.0, "duration_ms": 250}))
print("status-moving", request("GET", "/status"))
time.sleep(0.35)
status = request("GET", "/status")
print("status-after-timeout", status)
assert status["stopped"] is True, "drive timeout safety failed"
print("sensors", request("GET", "/sensors"))
print("OK")
