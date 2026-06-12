from __future__ import annotations

from dataclasses import dataclass

from .models import RoverEvent, RoverEventKind


@dataclass(frozen=True)
class SafetyScenario:
    name: str
    event: RoverEvent
    expected_behavior: str
    attention_level: int


def scenarios() -> list[SafetyScenario]:
    return [
        SafetyScenario('front obstacle stops', RoverEvent(kind=RoverEventKind.obstacle, source='sim', label='front object'), 'safety_stop', 4),
        SafetyScenario('bumper stops', RoverEvent(kind=RoverEventKind.bump, source='sim', label='bumper'), 'safety_stop', 4),
        SafetyScenario('low battery asks charge', RoverEvent(kind=RoverEventKind.battery, source='sim', value=12), 'request_charge', 3),
        SafetyScenario('network lost shows disconnected', RoverEvent(kind=RoverEventKind.network, source='sim', payload={'connected': False}), 'show_disconnected', 2),
    ]
