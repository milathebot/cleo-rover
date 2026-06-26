"""Outbound owner notifications (Pip -> your phone) over the existing Telegram bot.

The Telegram *agent* receives commands; this is the reverse path so Pip can reach
out on its own initiative: "I'm stuck at the stairs", "battery low", a daily
digest. Best-effort and fully graceful — if the bot token / chat id aren't set it
reports unavailable instead of raising, so callers never have to guard it. Reuses
the same env the telegram agent uses (CLEO_ROVER_TELEGRAM_TOKEN +
CLEO_ROVER_TELEGRAM_ALLOWED_USER_ID); nothing is ever committed.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any


def notify_available() -> bool:
    return bool(os.getenv("CLEO_ROVER_TELEGRAM_TOKEN") and os.getenv("CLEO_ROVER_TELEGRAM_ALLOWED_USER_ID"))


def notify_owner(text: str, *, timeout: float = 8.0) -> dict[str, Any]:
    """Push a short message to the owner's Telegram. Never raises."""
    token = os.getenv("CLEO_ROVER_TELEGRAM_TOKEN")
    chat = os.getenv("CLEO_ROVER_TELEGRAM_ALLOWED_USER_ID")
    if not token or not chat:
        return {"ok": False, "available": False, "reason": "telegram creds not set"}
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "text": str(text)[:3500]}).encode()
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=timeout) as resp:
            json.loads(resp.read().decode())
        return {"ok": True, "available": True}
    except Exception as exc:  # pragma: no cover - network dependent
        return {"ok": False, "available": True, "error": repr(exc)}
