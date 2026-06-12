from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .config import LifeLoopConfig
from .models import AutonomyState, BehaviorDecision, DriveCommand, ExpressionCommand, ExpressionMode, RoverEvent, RoverEventKind, TurretCommand


@dataclass
class EventStore:
    max_events: int = 200
    events: deque[RoverEvent] = field(default_factory=deque)

    def add(self, event: RoverEvent) -> RoverEvent:
        if event.timestamp is None:
            event = event.model_copy(update={"timestamp": time.time()})
        self.events.appendleft(event)
        while len(self.events) > self.max_events:
            self.events.pop()
        return event

    def recent(self, limit: int = 25, since: float | None = None) -> list[RoverEvent]:
        out = []
        for event in self.events:
            if since is not None and (event.timestamp or 0) < since:
                continue
            out.append(event)
            if len(out) >= limit:
                break
        return out


class AutonomyEngine:
    """Safe PC-side autonomy policy for Cleo Rover.

    This is intentionally conservative: it turns events into expressions,
    attention pings, and tiny simulated movements only when allowed. Hardware
    motion remains gated by the body service's motor-arming/safety state.
    """

    def __init__(self, config: LifeLoopConfig | None = None, state: AutonomyState | None = None, cooldowns: dict[str, float] | None = None) -> None:
        self.config = config or LifeLoopConfig()
        p = self.config.personality
        self.state = state or AutonomyState(mood=p.baseline_mood, curiosity=p.curiosity, attention=max(0.05, p.attention_seeking))
        self.last_behavior_at: dict[str, float] = cooldowns or {}

    def _cooldown_ok(self, behavior: str, now: float, seconds: float) -> bool:
        return now - self.last_behavior_at.get(behavior, 0.0) >= seconds

    def _mark(self, behavior: str, now: float) -> None:
        self.last_behavior_at[behavior] = now
        self.state.last_behavior = behavior
        self.state.last_decision_at = now

    def update_from_event(self, event: RoverEvent) -> None:
        now = event.timestamp or time.time()
        self.state.last_stimulus_at = now
        if event.kind in {RoverEventKind.sound, RoverEventKind.speech, RoverEventKind.wake_word}:
            self.state.attention = min(1.0, self.state.attention + 0.18)
            self.state.curiosity = min(1.0, self.state.curiosity + 0.12)
            self.state.mood = "listening" if event.kind != RoverEventKind.sound else "curious"
        elif event.kind in {RoverEventKind.motion, RoverEventKind.camera_snapshot}:
            self.state.curiosity = min(1.0, self.state.curiosity + 0.10)
            self.state.mood = "watching"
        elif event.kind in {RoverEventKind.bump, RoverEventKind.obstacle}:
            self.state.attention = min(1.0, self.state.attention + 0.35)
            self.state.confidence = max(0.0, self.state.confidence - 0.20)
            self.state.mood = "alert"
        elif event.kind == RoverEventKind.battery:
            level = event.value if event.value is not None else event.payload.get("percent")
            if isinstance(level, (int, float)):
                self.state.energy = max(0.0, min(1.0, float(level) / 100.0))
            if self.state.energy < 0.22:
                self.state.mood = "tired"
                self.state.attention = min(1.0, self.state.attention + 0.25)
        elif event.kind == RoverEventKind.network:
            self.state.connected = bool(event.payload.get("connected", True))
            if not self.state.connected:
                self.state.mood = "disconnected"
        elif event.kind == RoverEventKind.manual_control:
            self.state.mood = "manual"
        elif event.kind == RoverEventKind.idle_tick:
            self.state.attention = max(0.0, self.state.attention - 0.02)
            self.state.curiosity = max(0.0, self.state.curiosity - 0.01)
            if self.state.mood not in {"charging", "disconnected", "manual"}:
                self.state.mood = "calm"

    def decide(self, *, recent_events: list[RoverEvent], body_status: dict[str, Any] | None = None, allow_movement: bool = False, now: float | None = None) -> BehaviorDecision:
        now = now or time.time()
        for event in reversed(recent_events):
            self.update_from_event(event)
        body_status = body_status or {}
        latest = recent_events[0] if recent_events else None
        motors_armed = bool(body_status.get("motors_armed"))
        cooldowns = self.config.behavior_cooldowns
        hub = body_status.get("hub") or {}
        if hub.get("quiet_recommended"):
            self.state.do_not_disturb = True
            self.state.current_intent = "protect_focus"
        elif self.state.do_not_disturb and not hub.get("quiet_recommended", False):
            self.state.do_not_disturb = False

        if self.state.do_not_disturb and latest and latest.kind not in {RoverEventKind.bump, RoverEventKind.obstacle, RoverEventKind.battery, RoverEventKind.network, RoverEventKind.wake_word}:
            return BehaviorDecision(behavior="hold", reason="restraint: do-not-disturb or Cleo Hub focus is active", attention_level=0)

        if not self.state.connected:
            self._mark("show_disconnected", now)
            return BehaviorDecision(
                behavior="show_disconnected",
                reason="body/brain link marked disconnected",
                attention_level=2,
                expression=ExpressionCommand(mode=ExpressionMode.disconnected, text="link lost", brightness=0.45),
            )

        if self.state.energy < 0.22 and self._cooldown_ok("request_charge", now, cooldowns.request_charge_seconds):
            self._mark("request_charge", now)
            return BehaviorDecision(
                behavior="request_charge",
                reason="battery/energy state is low",
                attention_level=3,
                expression=ExpressionCommand(mode=ExpressionMode.low_power, text="low power", brightness=0.55),
                speech="Battery is getting low. I should be parked soon.",
            )

        if latest and latest.kind == RoverEventKind.wake_word and self._cooldown_ok("wake_response", now, cooldowns.wake_response_seconds):
            self._mark("wake_response", now)
            return BehaviorDecision(
                behavior="wake_response",
                reason="wake word heard",
                attention_level=2,
                expression=ExpressionCommand(mode=ExpressionMode.listening, text="yes?", brightness=0.7),
                speech="I'm here.",
                turret=TurretCommand(pan_deg=0),
            )

        if latest and latest.kind in {RoverEventKind.sound, RoverEventKind.speech} and self._cooldown_ok("react_to_sound", now, cooldowns.react_to_sound_seconds):
            self._mark("react_to_sound", now)
            drive = DriveCommand(linear=0.0, turn=0.16, duration_ms=180) if allow_movement and motors_armed else None
            return BehaviorDecision(
                behavior="react_to_sound",
                reason=f"{latest.kind.value} stimulus received",
                attention_level=1,
                expression=ExpressionCommand(mode=ExpressionMode.listening, text="heard", brightness=0.58),
                drive=drive,
            )

        if latest and latest.kind in {RoverEventKind.bump, RoverEventKind.obstacle}:
            self._mark("safety_stop", now)
            return BehaviorDecision(
                behavior="safety_stop",
                reason=f"safety stimulus: {latest.kind.value}",
                attention_level=4,
                expression=ExpressionCommand(mode=ExpressionMode.alert, text="stop", brightness=0.85),
                stop=True,
            )

        if self.state.curiosity > 0.68 and self._cooldown_ok("curious_scan", now, cooldowns.curious_scan_seconds):
            self._mark("curious_scan", now)
            return BehaviorDecision(
                behavior="curious_scan",
                reason="curiosity above threshold",
                attention_level=1,
                expression=ExpressionCommand(mode=ExpressionMode.watching, text="watching", brightness=0.5),
                turret=TurretCommand(pan_deg=18),
            )

        if self._cooldown_ok("idle_presence", now, cooldowns.idle_presence_seconds):
            self._mark("idle_presence", now)
            return BehaviorDecision(
                behavior="idle_presence",
                reason="quiet presence tick",
                attention_level=0,
                expression=ExpressionCommand(mode=ExpressionMode.idle, text="Cleo", brightness=0.42),
            )

        return BehaviorDecision(behavior="hold", reason="restraint: no useful autonomous action", attention_level=0)
