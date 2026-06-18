from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

SAFE_COMMANDS: dict[str, list[str]] = {
    "status": ["cleo-rover", "status"],
    "sensors": ["cleo-rover", "sensors"],
    "safe-mode": ["cleo-rover", "safe-mode"],
    "stop": ["cleo-rover", "safe-mode", "--amber"],
    "estop": ["cleo-rover", "safe-mode", "--amber"],
    "map": ["cleo-rover", "map"],
    "movement-status": ["cleo-rover", "movement-status"],
    "presence-tick": ["cleo-rover", "presence-tick", "--cleanup"],
    "snapshot": ["cleo-rover", "snapshot"],
}

SAFE_PREFIX_COMMANDS = {"map-scan", "visual-map-scan", "look-remember", "rgb-mode", "floor-precheck", "floor-map-dry-run"}
DANGEROUS_COMMANDS = {"drive", "move-step", "rotate-step", "movement-grant", "map-floor", "dance"}


@dataclass
class AgentConfig:
    token: str
    allowed_user_id: int
    workdir: str = "/home/cleo/cleo-rover"
    poll_timeout: int = 25
    dry_run: bool = False


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
    text = text.strip()
    first = text.split(maxsplit=1)[0] if text else ""
    if first.startswith("/rover"):
        # Accept both /rover and /rover@botname, which Telegram may emit in groups.
        text = text[len(first) :].strip()
    elif text.startswith("rover "):
        text = text[len("rover ") :].strip()
    elif text in {"/status", "status"}:
        text = "status"
    elif text in {"/start", "start", "/help", "help"}:
        return None, help_text()
    else:
        return None, None

    if not text or text in {"help", "/help"}:
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
        "  /rover safe-mode\n"
        "  /rover estop\n"
        "  /rover map\n"
        "  /rover floor-precheck --zone living-room\n"
        "  /rover floor-map-dry-run --zone living-room\n"
        "  /rover map-scan --zone office --angles=-25,0,25\n"
        "  /rover visual-map-scan --zone office --angles=-25,0,25\n"
        "  /rover look-remember --zone office --pan 0\n"
        "  /rover rgb-mode off\n\n"
        f"Single-word safe commands: {safe}\n"
        f"Allowlisted parameterized commands: {prefixed}\n"
        f"Blocked movement commands: {blocked}"
    )


def run_command(argv: list[str], config: AgentConfig) -> tuple[int, str]:
    if config.dry_run:
        return 0, "DRY RUN: " + " ".join(shlex.quote(part) for part in argv)
    env = os.environ.copy()
    env["PATH"] = f"{config.workdir}/.venv/bin:" + env.get("PATH", "")
    proc = subprocess.run(
        argv,
        cwd=config.workdir,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=90,
        check=False,
    )
    return proc.returncode, proc.stdout.strip()


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

    argv, error = parse_rover_command(text)
    if error:
        api.send_message(chat_id, error)
        return
    if argv is None:
        print(json.dumps({"ok": True, "event": "ignored", "text": text[:120]}), flush=True)
        return

    api.send_message(chat_id, "Running: " + " ".join(shlex.quote(part) for part in argv))
    print(json.dumps({"ok": True, "event": "run", "argv": argv}), flush=True)
    try:
        code, output = run_command(argv, config)
        prefix = "OK" if code == 0 else f"FAILED exit={code}"
        api.send_message(chat_id, f"{prefix}\n{output or '(no output)'}")
    except subprocess.TimeoutExpired:
        api.send_message(chat_id, "FAILED: command timed out")
    except Exception as exc:
        api.send_message(chat_id, f"FAILED: {exc!r}")


def loop(config: AgentConfig) -> int:
    api = TelegramAPI(config.token)
    me = api.call("getMe")
    print(json.dumps({"ok": True, "bot": me.get("result", {}).get("username"), "dry_run": config.dry_run}), flush=True)
    offset: int | None = None
    while True:
        try:
            updates = api.get_updates(offset, config.poll_timeout)
            for update in updates:
                offset = int(update["update_id"]) + 1
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
    args = parser.parse_args(argv)
    if not args.token:
        raise SystemExit("Missing --token or CLEO_ROVER_TELEGRAM_TOKEN")
    if not args.allowed_user_id:
        raise SystemExit("Missing --allowed-user-id or CLEO_ROVER_TELEGRAM_ALLOWED_USER_ID")
    return loop(AgentConfig(token=args.token, allowed_user_id=int(args.allowed_user_id), workdir=args.workdir, dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
