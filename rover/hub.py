from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HubSnapshot:
    ok: bool
    mode: str | None = None
    current_focus: str | None = None
    trading: dict[str, Any] | None = None
    quiet_recommended: bool = False
    error: str | None = None


def fetch_hub_snapshot(base_url: str = "http://127.0.0.1:8787", timeout: float = 2.0, trading_timeout: float = 1.0) -> HubSnapshot:
    try:
        with urllib.request.urlopen(base_url.rstrip('/') + '/api/hub', timeout=timeout) as r:
            hub = json.loads(r.read().decode())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return HubSnapshot(ok=False, error=repr(exc))
    trading: dict[str, Any] | None = None
    try:
        with urllib.request.urlopen(base_url.rstrip('/') + '/api/trading-bot', timeout=trading_timeout) as r:
            trading = json.loads(r.read().decode())
    except Exception as exc:  # best-effort only
        trading = {"ok": False, "error": repr(exc)}
    state = str(hub.get('state') or '')
    focus = hub.get('currentFocus')
    focus_session = hub.get('focusSession') or {}
    quiet = state == 'focus' or focus_session.get('status') == 'running'
    return HubSnapshot(ok=True, mode=state, current_focus=focus, trading=trading, quiet_recommended=quiet)
