from __future__ import annotations

import argparse
import json
import os
import secrets
import shlex
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SAFE_COMMANDS: dict[str, list[str]] = {
    "status": ["cleo-rover", "status"],
    "sensors": ["cleo-rover", "sensors"],
    "doctor": ["cleo-rover", "doctor"],
    "safe-mode": ["cleo-rover", "safe-mode"],
    "stop": ["cleo-rover", "safe-mode"],
    "estop": ["cleo-rover", "safe-mode"],
    "map": ["cleo-rover", "map"],
    "map-summary": ["cleo-rover", "map-summary"],
    "last-seen": ["cleo-rover", "last-seen"],
    "look-around": ["cleo-rover", "look-around"],
    "motion-check": ["cleo-rover", "motion-check"],
    "movement-status": ["cleo-rover", "movement-status"],
    "preflight": ["cleo-rover", "preflight"],
    "presence-tick": ["cleo-rover", "presence-tick", "--cleanup"],
    "situation": ["cleo-rover", "situation"],
    "snapshot": ["cleo-rover", "snapshot"],
}

SAFE_PREFIX_COMMANDS = {"map-scan", "visual-map-scan", "look-remember", "remember-room", "rgb-mode", "preflight", "floor-precheck", "floor-map-dry-run", "pip"}
DANGEROUS_COMMANDS = {"drive", "move-step", "rotate-step", "movement-grant", "map-floor", "dance"}
ARM_STATE_FILE = "data/telegram_floor_arm.json"
FLOOR_MODE_STATE_FILE = "data/telegram_floor_mode.json"
OFFSET_STATE_FILE = "data/telegram_agent_offset.json"
PROFILE_SWITCH_SCRIPT = "scripts/set_rover_profile.sh"


@dataclass
class AgentConfig:
    token: str
    allowed_user_id: int
    workdir: str = "/home/cleo/cleo-rover"
    poll_timeout: int = 25
    dry_run: bool = False
    hermes_api_base: str | None = None
    hermes_api_key: str | None = None
    hermes_model: str = "hermes-agent"


def rover_text(text: str) -> str | None:
    text = text.strip()
    first = text.split(maxsplit=1)[0] if text else ""
    if first.startswith("/rover"):
        return text[len(first) :].strip()
    if text.startswith("rover "):
        return text[len("rover ") :].strip()
    if text in {"/status", "status"}:
        return "status"
    if text in {"/start", "start", "/help", "help"}:
        return "help"
    return None


def arm_state_path(config: AgentConfig) -> Path:
    return Path(config.workdir) / ARM_STATE_FILE


def floor_mode_state_path(config: AgentConfig) -> Path:
    return Path(config.workdir) / FLOOR_MODE_STATE_FILE


def offset_state_path(config: AgentConfig) -> Path:
    return Path(config.workdir) / OFFSET_STATE_FILE


def _load_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _save_json_file(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True))


def load_arm_state(config: AgentConfig) -> dict[str, Any] | None:
    return _load_json_file(arm_state_path(config))


def save_arm_state(config: AgentConfig, state: dict[str, Any]) -> None:
    _save_json_file(arm_state_path(config), state)


def clear_arm_state(config: AgentConfig) -> None:
    try:
        arm_state_path(config).unlink()
    except FileNotFoundError:
        pass


def active_floor_arm(config: AgentConfig) -> dict[str, Any] | None:
    state = load_arm_state(config)
    if not state or not state.get("confirmed"):
        return None
    if float(state.get("expires_at", 0)) <= time.time():
        clear_arm_state(config)
        return None
    return state


class TelegramAPI:
    def __init__(self, token: str) -> None:
        self.base = f"https://api.telegram.org/bot{token}"

    def call(self, method: str, payload: dict[str, Any] | None = None, timeout: int = 35) -> dict[str, Any]:
        data = None if payload is None else urllib.parse.urlencode(payload).encode()
        with urllib.request.urlopen(f"{self.base}/{method}", data=data, timeout=timeout) as resp:
            return json.loads(resp.read().decode())

    def send_message(self, chat_id: int, text: str) -> None:
        # Telegram hard cap is 4096 chars. Keep room for formatting/plain text.
        chunks = [text[i : i + 3500] for i in range(0, len(text), 3500)] or [""]
        for chunk in chunks[:4]:
            self.call("sendMessage", {"chat_id": chat_id, "text": chunk})

    def get_updates(self, offset: int | None, timeout: int) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        data = self.call("getUpdates", payload, timeout=timeout + 10)
        return data.get("result", [])


def parse_rover_command(text: str) -> tuple[list[str] | None, str | None]:
    parsed = rover_text(text)

    if not parsed:
        return None, None
    text = parsed
    if text in {"help", "/help"}:
        return None, help_text()

    parts = shlex.split(text)
    if not parts:
        return None, help_text()
    cmd = parts[0]

    if cmd in SAFE_COMMANDS and len(parts) == 1:
        return SAFE_COMMANDS[cmd], None

    if cmd in SAFE_PREFIX_COMMANDS:
        # Allow only CLI options/values, not shell execution. subprocess gets argv directly.
        return ["cleo-rover", cmd, *parts[1:]], None

    if cmd in DANGEROUS_COMMANDS:
        return None, f"Refusing `{cmd}` from Telegram agent. Use SSH/local terminal for movement or explicit bench tests."

    return None, f"Unknown or not-allowed rover command: {cmd}\n\n{help_text()}"


def help_text() -> str:
    safe = ", ".join(sorted(SAFE_COMMANDS))
    prefixed = ", ".join(sorted(SAFE_PREFIX_COMMANDS))
    blocked = ", ".join(sorted(DANGEROUS_COMMANDS))
    return (
        "Cleo Rover Telegram agent commands:\n"
        "  /rover status\n"
        "  /rover sensors\n"
        "  /rover doctor\n"
        "  /rover preflight\n"
        "  /rover preflight --mode floor\n"
        "  /rover safe-mode\n"
        "  /rover estop\n"
        "  /rover map\n"
        "  /rover map-summary\n"
        "  /rover last-seen\n"
        "  /rover situation\n"
        "  /rover motion-check\n"
        "  /rover look-around\n"
        "  /rover remember-room --zone office\n"
        "  /rover floor-precheck --zone living-room\n"
        "  /rover floor-map-dry-run --zone living-room\n"
        "  /rover floor-arm request\n"
        "  /rover floor-arm confirm CODE\n"
        "  /rover floor-arm status\n"
        "  /rover floor-arm cancel\n"
        "  /rover floor-mode request\n"
        "  /rover floor-mode confirm CODE\n"
        "  /rover floor-mode presence\n"
        "  /rover floor-mode status\n"
        "  /rover floor-map-run --zone living-room --steps 1  (requires active floor-arm)\n"
        "  /rover pip status\n"
        "  /rover pip wake | sleep | quiet | social | assistant\n"
        "  /rover pip greet | observe | patrol | stop\n"
        "  /rover map-scan --zone office --angles=-25,0,25\n"
        "  /rover visual-map-scan --zone office --angles=-25,0,25\n"
        "  /rover look-remember --zone office --pan 0\n"
        "  /rover rgb-mode off\n\n"
        f"Single-word safe commands: {safe}\n"
        f"Allowlisted parameterized commands: {prefixed}\n"
        f"Blocked movement commands: {blocked}"
    )


def run_command(argv: list[str], config: AgentConfig, *, timeout: float = 90) -> tuple[int, str]:
    if config.dry_run:
        return 0, "DRY RUN: " + " ".join(shlex.quote(part) for part in argv)
    env = os.environ.copy()
    env["PATH"] = f"{config.workdir}/.venv/bin:" + env.get("PATH", "")
    try:
        proc = subprocess.run(
            argv,
            cwd=config.workdir,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode(errors="replace")
        return 124, f"command timed out after {timeout:.0f}s: {' '.join(shlex.quote(part) for part in argv)}\n{partial}".strip()
    return proc.returncode, proc.stdout.strip()


def _short_json(value: Any, *, max_chars: int = 2600) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= max_chars else text[: max_chars - 3] + "..."


def hermes_pip_response(prompt: str, context: dict[str, Any], config: AgentConfig) -> tuple[bool, str]:
    """Ask Hermes for a concise Pip voice line via Hermes' OpenAI-compatible API server."""

    if not config.hermes_api_base or not config.hermes_api_key:
        return False, (
            "Hermes bridge is not configured on the Pi. Set CLEO_ROVER_HERMES_API_BASE "
            "and CLEO_ROVER_HERMES_API_KEY for cleo-rover-telegram-agent."
        )

    base = config.hermes_api_base.rstrip("/")
    url = base + "/chat/completions" if base.endswith("/v1") else base + "/v1/chat/completions"
    system = (
        "You are Pip, Noot's shy office droid rover. Reply in first person as Pip, "
        "warm, compact, a little timid but curious. Do not claim to move unless the "
        "provided state says movement is active or allowed. For safety, never instruct "
        "movement, wiring, or power changes unless Noot explicitly asks. Keep voice output "
        "under 2 short sentences. No emoji."
    )
    user = (
        f"Noot asked Pip: {prompt}\n\n"
        f"Current Pip state JSON: {_short_json(context)}\n\n"
        "Answer as Pip for text-to-speech."
    )
    payload = {
        "model": config.hermes_model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"content-type": "application/json", "authorization": f"Bearer {config.hermes_api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        return False, f"Hermes bridge request failed: {exc!r}"

    try:
        text = str(data["choices"][0]["message"]["content"]).strip()
    except Exception:
        return False, "Hermes bridge returned an unexpected response shape: " + _short_json(data, max_chars=900)
    if not text:
        return False, "Hermes bridge returned an empty response."
    lowered = text.lower()
    if "api call failed after" in lowered or "model provider failed after" in lowered:
        return False, text[:600]
    return True, text[:600]


def maybe_handle_pip_bridge(argv: list[str], output: str, config: AgentConfig) -> str | None:
    if argv[:2] != ["cleo-rover", "pip"]:
        return None
    try:
        data = json.loads(output)
    except Exception:
        return None
    if data.get("action") != "relay_to_hermes":
        return None

    prompt = str(data.get("prompt") or "").strip()
    context = data.get("context") if isinstance(data.get("context"), dict) else {}
    ok, response = hermes_pip_response(prompt, context, config)
    if not ok:
        fallback = "I heard you, Noot, but my Hermes brain hiccuped for a second. I’m still awake, staying still, and ready to try again."
        code, say_output = run_command(["cleo-rover", "say", fallback], config, timeout=25)
        spoken = "spoken" if code == 0 else f"speech failed exit={code}: {say_output[-500:]}"
        return f"Pip/Hermes fallback:\n{fallback}\n\n{spoken}\n\nBridge detail: {response[:500]}"

    code, say_output = run_command(["cleo-rover", "say", response], config, timeout=25)
    spoken = "spoken" if code == 0 else f"speech failed exit={code}: {say_output[-500:]}"
    return f"Pip/Hermes:\n{response}\n\n{spoken}"


def profile_switch_argv(config: AgentConfig, profile: str) -> list[str]:
    return ["sudo", "-n", str(Path(config.workdir) / PROFILE_SWITCH_SCRIPT), profile]


def handle_floor_mode(text: str, config: AgentConfig) -> str | None:
    parsed = rover_text(text)
    if not parsed:
        return None
    parts = shlex.split(parsed)
    if not parts or parts[0] != "floor-mode":
        return None
    action = parts[1] if len(parts) > 1 else "status"
    if action == "request":
        code = f"{secrets.randbelow(900000) + 100000}"
        state = {"requested_at": time.time(), "expires_at": time.time() + 300, "code": code}
        _save_json_file(floor_mode_state_path(config), state)
        return (
            "Floor-cautious motor profile switch requested.\n"
            "Before confirming: rover is on floor, clear open area, cats/feet/cables clear, you are ready to use /rover estop.\n"
            f"Confirm within 5 min with: /rover floor-mode confirm {code}\n"
            "Return to safe no-motor presence mode anytime with: /rover floor-mode presence"
        )
    if action == "confirm":
        state = _load_json_file(floor_mode_state_path(config))
        if not state:
            return "No pending floor-mode request. Run /rover floor-mode request first."
        if float(state.get("expires_at", 0)) <= time.time():
            floor_mode_state_path(config).unlink(missing_ok=True)
            return "Floor-mode request expired. Run /rover floor-mode request again."
        provided = parts[2] if len(parts) > 2 else ""
        if provided != str(state.get("code")):
            return "Wrong confirmation code. Staying in current profile."
        clear_arm_state(config)
        code, output = run_command(profile_switch_argv(config, "floor-cautious"), config, timeout=30)
        if code != 0:
            return (
                "FAILED to switch to floor-cautious profile.\n"
                f"{output}\n\n"
                "Install the sudoers helper once on the Pi: sudo scripts/install_profile_switch_sudoers.sh"
            )
        floor_mode_state_path(config).unlink(missing_ok=True)
        return "Switched to hardware-floor-cautious. Run /rover floor-precheck, then /rover floor-arm request before movement.\n" + output
    if action in {"presence", "safe", "off", "cancel"}:
        clear_arm_state(config)
        floor_mode_state_path(config).unlink(missing_ok=True)
        code, output = run_command(profile_switch_argv(config, "presence"), config, timeout=30)
        if code != 0:
            return (
                "FAILED to switch to no-motor presence profile.\n"
                f"{output}\n\n"
                "Install the sudoers helper once on the Pi: sudo scripts/install_profile_switch_sudoers.sh"
            )
        return "Switched to hardware-presence-no-motors.\n" + output
    if action == "status":
        state = _load_json_file(floor_mode_state_path(config))
        pending = ""
        if state and float(state.get("expires_at", 0)) > time.time():
            pending = f"\nPending floor-mode confirmation for {max(0, int(float(state['expires_at']) - time.time()))}s."
        code, output = run_command(["cleo-rover", "status"], config)
        prefix = "Current rover status:" if code == 0 else "Could not read rover status:"
        return f"{prefix}\n{output}{pending}"
    return "Usage: /rover floor-mode request | confirm CODE | presence | status"


def handle_floor_arm(text: str, config: AgentConfig) -> str | None:
    parsed = rover_text(text)
    if not parsed:
        return None
    parts = shlex.split(parsed)
    if not parts or parts[0] != "floor-arm":
        return None
    action = parts[1] if len(parts) > 1 else "status"
    if action == "request":
        code = f"{secrets.randbelow(900000) + 100000}"
        state = {
            "requested_at": time.time(),
            "request_expires_at": time.time() + 300,
            "code": code,
            "confirmed": False,
            "expires_at": 0,
            "zone": "floor",
        }
        save_arm_state(config, state)
        return (
            "Floor movement arm requested.\n"
            "Before confirming: rover on floor, open area clear, cats/feet clear, battery ok, /rover floor-precheck passed.\n"
            f"Confirm within 5 min with: /rover floor-arm confirm {code}\n"
            "Cancel: /rover floor-arm cancel"
        )
    if action == "confirm":
        state = load_arm_state(config)
        if not state or state.get("confirmed"):
            return "No pending floor-arm request. Run /rover floor-arm request first."
        if float(state.get("request_expires_at", 0)) <= time.time():
            clear_arm_state(config)
            return "Floor-arm request expired. Run /rover floor-arm request again."
        provided = parts[2] if len(parts) > 2 else ""
        if provided != str(state.get("code")):
            return "Wrong confirmation code. Movement remains blocked."
        state.update({"confirmed": True, "confirmed_at": time.time(), "expires_at": time.time() + 60})
        save_arm_state(config, state)
        return (
            "Floor movement armed for 60 seconds.\n"
            "Allowed next command: /rover floor-map-run --zone living-room --steps 1\n"
            "Emergency stop/cancel: /rover estop or /rover floor-arm cancel"
        )
    if action in {"cancel", "revoke", "off"}:
        clear_arm_state(config)
        return "Floor movement arm cancelled."
    if action == "status":
        state = load_arm_state(config)
        active = active_floor_arm(config)
        if active:
            return f"Floor movement is ARMED for {max(0, int(active['expires_at'] - time.time()))}s."
        if state and not state.get("confirmed"):
            return f"Floor movement request pending for {max(0, int(state.get('request_expires_at', 0) - time.time()))}s."
        return "Floor movement is not armed."
    return "Usage: /rover floor-arm request | confirm CODE | status | cancel"


def build_floor_map_run(text: str, config: AgentConfig) -> tuple[list[str] | None, str | None]:
    parsed = rover_text(text)
    if not parsed:
        return None, None
    parts = shlex.split(parsed)
    if not parts or parts[0] != "floor-map-run":
        return None, None
    active = active_floor_arm(config)
    if not active:
        return None, "Floor movement is not armed. Run /rover floor-arm request, then confirm the code first."
    return ["cleo-rover", "map-floor", "--allow-movement", *parts[1:]], None


def handle_message(api: TelegramAPI, config: AgentConfig, message: dict[str, Any]) -> None:
    chat = message.get("chat") or {}
    user = message.get("from") or {}
    if chat.get("id") is None:
        return
    chat_id = int(chat["id"])
    user_id = int(user.get("id") or 0)
    text = str(message.get("text") or "")
    print(json.dumps({"ok": True, "event": "message", "chat_id": chat_id, "user_id": user_id, "text": text[:120]}), flush=True)

    if user_id != config.allowed_user_id:
        api.send_message(chat_id, "Unauthorized rover command sender.")
        print(json.dumps({"ok": False, "event": "unauthorized", "user_id": user_id}), flush=True)
        return

    floor_mode_response = handle_floor_mode(text, config)
    if floor_mode_response is not None:
        api.send_message(chat_id, floor_mode_response)
        return

    arm_response = handle_floor_arm(text, config)
    if arm_response is not None:
        api.send_message(chat_id, arm_response)
        return

    argv, error = build_floor_map_run(text, config)
    if error:
        api.send_message(chat_id, error)
        return
    if argv is None:
        argv, error = parse_rover_command(text)
    if error:
        api.send_message(chat_id, error)
        return
    if argv is None:
        print(json.dumps({"ok": True, "event": "ignored", "text": text[:120]}), flush=True)
        return
    if argv[:2] == ["cleo-rover", "safe-mode"]:
        clear_arm_state(config)

    api.send_message(chat_id, "Running: " + " ".join(shlex.quote(part) for part in argv))
    print(json.dumps({"ok": True, "event": "run", "argv": argv}), flush=True)
    try:
        code, output = run_command(argv, config)
        if argv[:2] == ["cleo-rover", "map-floor"]:
            clear_arm_state(config)
        prefix = "OK" if code == 0 else f"FAILED exit={code}"
        bridge_output = maybe_handle_pip_bridge(argv, output, config) if code == 0 else None
        api.send_message(chat_id, f"{prefix}\n{bridge_output or output or '(no output)'}")
    except subprocess.TimeoutExpired:
        api.send_message(chat_id, "FAILED: command timed out")
    except Exception as exc:
        api.send_message(chat_id, f"FAILED: {exc!r}")


def load_saved_offset(config: AgentConfig) -> int | None:
    state = _load_json_file(offset_state_path(config))
    if not state:
        return None
    value = state.get("offset")
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def save_offset(config: AgentConfig, offset: int) -> None:
    _save_json_file(offset_state_path(config), {"offset": offset, "saved_at": time.time()})


def loop(config: AgentConfig) -> int:
    api = TelegramAPI(config.token)
    me = api.call("getMe")
    print(json.dumps({"ok": True, "bot": me.get("result", {}).get("username"), "dry_run": config.dry_run}), flush=True)
    offset: int | None = load_saved_offset(config)
    if offset is not None:
        print(json.dumps({"ok": True, "event": "resume_offset", "offset": offset}), flush=True)
    while True:
        try:
            updates = api.get_updates(offset, config.poll_timeout)
            for update in updates:
                next_offset = int(update["update_id"]) + 1
                # Persist the next offset before executing commands. If systemd restarts this
                # agent mid-command, Telegram will not replay the same profile-switch command
                # forever on the next start.
                save_offset(config, next_offset)
                offset = next_offset
                message = update.get("message") or update.get("edited_message")
                if message and message.get("text"):
                    handle_message(api, config, message)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(json.dumps({"ok": False, "error": repr(exc)}), flush=True)
            time.sleep(5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pi-side Telegram command agent for allowlisted Cleo Rover operations")
    parser.add_argument("--token", default=os.getenv("CLEO_ROVER_TELEGRAM_TOKEN"))
    parser.add_argument("--allowed-user-id", type=int, default=os.getenv("CLEO_ROVER_TELEGRAM_ALLOWED_USER_ID"))
    parser.add_argument("--workdir", default=os.getenv("CLEO_ROVER_WORKDIR", "/home/cleo/cleo-rover"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--hermes-api-base", default=os.getenv("CLEO_ROVER_HERMES_API_BASE"))
    parser.add_argument("--hermes-api-key", default=os.getenv("CLEO_ROVER_HERMES_API_KEY"))
    parser.add_argument("--hermes-model", default=os.getenv("CLEO_ROVER_HERMES_MODEL", "hermes-agent"))
    args = parser.parse_args(argv)
    if not args.token:
        raise SystemExit("Missing --token or CLEO_ROVER_TELEGRAM_TOKEN")
    if not args.allowed_user_id:
        raise SystemExit("Missing --allowed-user-id or CLEO_ROVER_TELEGRAM_ALLOWED_USER_ID")
    return loop(AgentConfig(
        token=args.token,
        allowed_user_id=int(args.allowed_user_id),
        workdir=args.workdir,
        dry_run=args.dry_run,
        hermes_api_base=args.hermes_api_base,
        hermes_api_key=args.hermes_api_key,
        hermes_model=args.hermes_model,
    ))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
