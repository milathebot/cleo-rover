"""The deliberative "mind": ask a pluggable LLM for a high-level intent.

This is the slow, optional brain tier of the dual-process design. It asks an
OpenAI-compatible endpoint (Hermes by default, or Claude / any gateway) for a
SINGLE high-level intent from a closed allow-list, with bounded params. The Pi
then validates that intent (rover/supervisor.validate_intent) and may refuse it;
the deterministic local policy is both the default and the fallback, so Pip keeps
acting safely when the mind is slow, offline, or returns junk.

The mind NEVER emits motor PWM and can NEVER relax a safety guard. It chooses
among already-safe options and supplies Pip's voice/mood.

Config (env, never committed):
  HERMES_API_BASE / HERMES_API_KEY / HERMES_MODEL   (existing Hermes bridge)
  MIND_API_BASE  / MIND_API_KEY  / MIND_MODEL       (optional override; e.g. point
    at Claude via an OpenAI-compatible gateway)
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

# Closed intent vocabulary. Mirrors rover.supervisor.SAFE_INTENTS so every value
# is something the Pi knows how to validate and execute as a bounded primitive.
ALLOWED_INTENTS = ("status", "stop", "scan", "look", "say", "mood", "move_step", "rotate_step", "idle", "set_goal")
GOAL_KINDS = ("explore_zone", "find_person", "return_to", "observe")
ALLOWED_MOODS = ("idle", "happy", "sad", "alert", "thinking", "confused", "speaking", "mad", "focused", "laugh", "curious", "watching", "seeking")

# Hard caps the mind's params are clamped to before the Pi even validates them.
MAX_FORWARD_CM = 12.0
MAX_ROTATE_DEG = 35.0

INTENT_INSTRUCTIONS = (
    "You are choosing Pip's next single action. Respond with ONLY a JSON object, no prose:\n"
    '{"intent": "<one of: ' + " | ".join(ALLOWED_INTENTS) + '>",'
    ' "mood": "<optional mood word>",'
    ' "speech": "<optional one short spoken line>",'
    ' "params": {"forward_cm": <-12..12>, "deg": <-35..35>, "pan_deg": <-80..80>, "zone": "<zone>", "angles": [..]},'
    ' "reason": "<one short clause>"}\n'
    "Rules: choose move_step/rotate_step only when the state clearly shows it is safe; prefer scan when unsure; "
    "the Pi will validate and may refuse your intent. Never invent sensor values. Keep speech to one short sentence."
)


def mind_configured() -> bool:
    return bool(os.getenv("MIND_API_BASE") or os.getenv("HERMES_API_BASE"))


def _endpoint() -> tuple[str, str, str]:
    base = (os.getenv("MIND_API_BASE") or os.getenv("HERMES_API_BASE") or "").strip()
    key = (os.getenv("MIND_API_KEY") or os.getenv("HERMES_API_KEY") or "").strip()
    model = (os.getenv("MIND_MODEL") or os.getenv("HERMES_MODEL") or "hermes-agent").strip() or "hermes-agent"
    return base, key, model


def _api_url(base: str) -> str:
    base = base.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def parse_intent(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from an LLM reply (tolerates ``` fences/prose)."""
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.S)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _clamp(value: Any, lo: float, hi: float, default: float = 0.0) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return default


def clamp_intent(intent: dict[str, Any]) -> dict[str, Any]:
    """Coerce a raw mind intent into the safe, bounded contract.

    Unknown intents become 'idle'; out-of-range params are clamped; unknown param
    keys are dropped. This runs BEFORE the Pi's validate_intent safety gate.
    """
    name = str(intent.get("intent", "idle")).strip().lower()
    if name not in ALLOWED_INTENTS:
        name = "idle"
    raw_params = intent.get("params") if isinstance(intent.get("params"), dict) else {}
    params: dict[str, Any] = {}
    if name == "move_step":
        params["forward_cm"] = _clamp(raw_params.get("forward_cm", 6), -MAX_FORWARD_CM, MAX_FORWARD_CM, 0.0)
    if name == "rotate_step":
        params["deg"] = _clamp(raw_params.get("deg", 12), -MAX_ROTATE_DEG, MAX_ROTATE_DEG, 0.0)
    if name == "look":
        params["pan_deg"] = _clamp(raw_params.get("pan_deg", 0), -80.0, 80.0, 0.0)
    if name == "scan":
        params["zone"] = str(raw_params.get("zone", "unknown"))[:80]
        angles = raw_params.get("angles")
        if isinstance(angles, list):
            params["angles"] = [_clamp(a, -80.0, 80.0, 0.0) for a in angles][:9]
    if name == "set_goal":
        kind = str(raw_params.get("goal_kind", "observe")).strip().lower()
        params["goal_kind"] = kind if kind in GOAL_KINDS else "observe"
        params["target"] = str(raw_params.get("target", ""))[:80]
    mood = str(intent.get("mood")).strip().lower() if intent.get("mood") else None
    if mood not in ALLOWED_MOODS:
        mood = None
    speech = str(intent.get("speech"))[:240] if intent.get("speech") else None
    return {"intent": name, "mood": mood, "speech": speech, "params": params, "reason": str(intent.get("reason", ""))[:160]}


def ask_mind_for_intent(*, packet: dict[str, Any], soul_prompt: str, max_tokens: int = 220, timeout: float = 30.0) -> dict[str, Any]:
    """Ask the LLM for one validated-shape intent. Returns {ok, intent|error}."""
    base, key, model = _endpoint()
    if not base:
        return {"ok": False, "configured": False, "error": "no MIND_API_BASE/HERMES_API_BASE"}
    context = json.dumps(packet, sort_keys=True, default=str)[:5000]
    payload = {
        "model": model,
        "stream": False,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": soul_prompt + "\n\n" + INTENT_INSTRUCTIONS},
            {"role": "user", "content": f"Pip world-state packet JSON:\n{context}\n\nReturn one JSON intent."},
        ],
    }
    headers = {"content-type": "application/json"}
    if key:
        headers["authorization"] = f"Bearer {key}"
    req = urllib.request.Request(_api_url(base), data=json.dumps(payload).encode(), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return {"ok": False, "configured": True, "status": exc.code, "error": exc.read().decode(errors="replace")[-500:]}
    except Exception as exc:
        return {"ok": False, "configured": True, "error": repr(exc)}
    try:
        content = data["choices"][0]["message"]["content"]
    except Exception:
        return {"ok": False, "configured": True, "error": "no message content", "raw": data}
    parsed = parse_intent(str(content))
    if parsed is None:
        return {"ok": False, "configured": True, "error": "could not parse intent JSON", "raw_text": str(content)[:500]}
    return {"ok": True, "configured": True, "intent": clamp_intent(parsed), "model": model, "raw_usage": data.get("usage")}
