from __future__ import annotations

import os

from fastapi import FastAPI

from .drivers import RoverBody
from .models import DriveCommand, ExpressionCommand, RoverStatus, TurretCommand

ROVER_MODE = os.getenv("CLEO_ROVER_MODE", "sim")
body = RoverBody(mode=ROVER_MODE)

app = FastAPI(title="Cleo Rover Mk1 Body Service", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "mode": body.mode, "name": "cleo-rover-mk1"}


@app.get("/status", response_model=RoverStatus)
def status() -> RoverStatus:
    return RoverStatus(
        mode=body.mode,
        online=True,
        stopped=body.state.stopped,
        expression=body.state.expression,
        last_drive=body.state.last_drive,
        turret=body.state.turret,
        camera_ready=False,
        mic_ready=False,
        speaker_ready=False,
    )


@app.post("/drive")
async def drive(command: DriveCommand) -> dict:
    await body.drive(command)
    return {"ok": True, "stopped": body.state.stopped, "command": command.model_dump()}


@app.post("/stop")
async def stop() -> dict:
    await body.stop()
    return {"ok": True, "stopped": True}


@app.post("/expression")
async def expression(command: ExpressionCommand) -> dict:
    await body.set_expression(command)
    return {"ok": True, "expression": command.model_dump()}


@app.post("/turret")
async def turret(command: TurretCommand) -> dict:
    await body.set_turret(command)
    return {"ok": True, "turret": command.model_dump()}


@app.get("/sensors")
def sensors() -> dict:
    return body.sensors()
