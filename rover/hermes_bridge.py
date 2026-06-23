from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from .pip_soul import pip_soul_prompt


DEFAULT_SYSTEM_PROMPT = pip_soul_prompt()


def hermes_configured() -> bool:
    return bool(os.getenv("HERMES_API_BASE"))


def _api_url(base: str) -> str:
    base = base.rstrip("/")
    if base.endswith("/v1"):
        return base + "/chat/completions"
    if base.endswith("/v1/chat/completions"):
        return base
    return base + "/v1/chat/completions"


def ask_hermes_as_pip(prompt: str, *, context: dict[str, Any], timeout: float = 45.0) -> dict[str, Any]:
    """Call an OpenAI-compatible Hermes API server for Pip's spoken reply.

    Configure with:
      HERMES_API_BASE=http://host:8642/v1
      HERMES_API_KEY=...
      HERMES_MODEL=hermes-agent
    """

    base = os.getenv("HERMES_API_BASE", "").strip()
    if not base:
        return {"ok": False, "configured": False, "error": "HERMES_API_BASE is not set"}

    key = os.getenv("HERMES_API_KEY", "").strip()
    model = os.getenv("HERMES_MODEL", "hermes-agent").strip() or "hermes-agent"
    max_tokens = int(os.getenv("HERMES_PIP_MAX_TOKENS", "220"))
    system_prompt = os.getenv("HERMES_PIP_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT)

    context_text = json.dumps(context, sort_keys=True, default=str)[:5000]
    payload = {
        "model": model,
        "stream": False,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Pip state/context JSON:\n{context_text}\n\nNoot/user said:\n{prompt}"},
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
        body = exc.read().decode(errors="replace")[-1000:]
        return {"ok": False, "configured": True, "status": exc.code, "error": body}
    except Exception as exc:
        return {"ok": False, "configured": True, "error": repr(exc)}

    try:
        answer = data["choices"][0]["message"]["content"].strip()
    except Exception:
        answer = ""
    if not answer:
        return {"ok": False, "configured": True, "error": "Hermes returned no message content", "raw": data}

    return {"ok": True, "configured": True, "answer": answer, "model": model, "raw_usage": data.get("usage")}
