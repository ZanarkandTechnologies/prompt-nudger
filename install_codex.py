#!/usr/bin/env python3
"""Install Prompt Nudger for Codex users."""

from __future__ import annotations

import getpass
import json
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
INSTALL_DIR = Path.home() / ".prompt-nudger"
BIN_SCRIPT = INSTALL_DIR / "prompt_nudger.py"
LOG_DIR = INSTALL_DIR / "logs"
CODEX_HOOK = Path.home() / ".codex" / "hooks" / "prompt_nudger_codex_activity.py"
CODEX_HOOKS_JSON = Path.home() / ".codex" / "hooks.json"
CODEX_CONFIG_TOML = Path.home() / ".codex" / "config.toml"
LIVE_PLIST = Path.home() / "Library" / "LaunchAgents" / "com.zanarkand.prompt-nudger.plist"
REMINDER_PLIST = Path.home() / "Library" / "LaunchAgents" / "com.zanarkand.prompt-nudger.reminder.plist"


def ask(prompt: str, default: str | None = None, secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    full_prompt = f"{prompt}{suffix}: "
    value = getpass.getpass(full_prompt) if secret else input(full_prompt)
    if not value.strip() and default is not None:
        return default
    return value.strip()


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    default_text = "Y/n" if default else "y/N"
    value = input(f"{prompt} [{default_text}]: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "1", "true"}


def copy_files() -> None:
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "prompt_nudger.py", BIN_SCRIPT)
    BIN_SCRIPT.chmod(0o755)

    CODEX_HOOK.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "hooks" / "codex_activity.py", CODEX_HOOK)
    CODEX_HOOK.chmod(0o755)


def load_hooks_json() -> dict[str, Any]:
    try:
        with CODEX_HOOKS_JSON.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        data = {}
    return data if isinstance(data, dict) else {}


def ensure_codex_hook(data: dict[str, Any], event_name: str, status_message: str) -> None:
    command = 'python3 "$HOME/.codex/hooks/prompt_nudger_codex_activity.py"'
    hooks_by_event = data.setdefault("hooks", {})
    if not isinstance(hooks_by_event, dict):
        hooks_by_event = {}
        data["hooks"] = hooks_by_event
    event_groups = hooks_by_event.setdefault(event_name, [])
    if not isinstance(event_groups, list):
        event_groups = []
        hooks_by_event[event_name] = event_groups

    for group in event_groups:
        if not isinstance(group, dict):
            continue
        hooks = group.get("hooks")
        if not isinstance(hooks, list):
            continue
        if any(isinstance(hook, dict) and hook.get("command") == command for hook in hooks):
            return

    if event_groups and isinstance(event_groups[0], dict) and isinstance(event_groups[0].get("hooks"), list):
        target_hooks = event_groups[0]["hooks"]
    else:
        target_group: dict[str, Any] = {"hooks": []}
        event_groups.insert(0, target_group)
        target_hooks = target_group["hooks"]

    target_hooks.append(
        {
            "type": "command",
            "command": command,
            "statusMessage": status_message,
            "timeout": 5,
        }
    )


def install_codex_hooks() -> None:
    data = load_hooks_json()
    ensure_codex_hook(data, "UserPromptSubmit", "Marking Prompt Nudger active work")
    ensure_codex_hook(data, "Stop", "Clearing Prompt Nudger active work")
    CODEX_HOOKS_JSON.parent.mkdir(parents=True, exist_ok=True)
    with CODEX_HOOKS_JSON.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
        file.write("\n")


def enable_codex_hooks_feature() -> None:
    try:
        lines = CODEX_CONFIG_TOML.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []

    output: list[str] = []
    in_features = False
    saw_features = False
    wrote_key = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_features and not wrote_key:
                output.append("codex_hooks = true")
                wrote_key = True
            in_features = stripped == "[features]"
            saw_features = saw_features or in_features
            output.append(line)
            continue

        if in_features and stripped.startswith("codex_hooks"):
            output.append("codex_hooks = true")
            wrote_key = True
        else:
            output.append(line)

    if not saw_features:
        if output and output[-1].strip():
            output.append("")
        output.extend(["[features]", "codex_hooks = true"])
    elif in_features and not wrote_key:
        output.append("codex_hooks = true")

    CODEX_CONFIG_TOML.parent.mkdir(parents=True, exist_ok=True)
    CODEX_CONFIG_TOML.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def plist_env(token: str, chat_id: str, reminder_message: str) -> dict[str, str]:
    return {
        "TELEGRAM_BOT_TOKEN": token,
        "TELEGRAM_CHAT_ID": chat_id,
        "NUDGE_MESSAGE": "Hey, you've been writing for a bit. Want to spin up another agent thread?",
        "NUDGE_REMINDER_MESSAGE": reminder_message,
        "NUDGE_ACTIVITY_THRESHOLD": "20",
        "NUDGE_GRACE_SECONDS": "3",
        "NUDGE_COOLDOWN_SECONDS": "60",
        "NUDGE_SUPPRESS_WHEN_ACTIVE": "1",
        "PYTHONUNBUFFERED": "1",
    }


def write_launch_agent(
    path: Path,
    label: str,
    args: list[str],
    env: dict[str, str],
    start_interval_seconds: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    plist: dict[str, Any] = {
        "Label": label,
        "ProgramArguments": [sys.executable, str(BIN_SCRIPT), *args],
        "EnvironmentVariables": env,
        "StandardOutPath": str(LOG_DIR / f"{label}.out.log"),
        "StandardErrorPath": str(LOG_DIR / f"{label}.err.log"),
    }
    if start_interval_seconds is None:
        plist["RunAtLoad"] = True
        plist["KeepAlive"] = True
    else:
        plist["RunAtLoad"] = True
        plist["StartInterval"] = max(60, start_interval_seconds)

    with path.open("wb") as file:
        plistlib.dump(plist, file)


def launch_agent(path: Path, label: str) -> None:
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(path)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=False)
    subprocess.run(["launchctl", "kickstart", "-k", f"{domain}/{label}"], check=False)


def install_launch_agents(token: str, chat_id: str) -> None:
    env = plist_env(
        token,
        chat_id,
        ask("Periodic reminder message", "Quick reminder: write another prompt and keep the loop moving."),
    )

    if ask_yes_no("Run the live typing nudger in the background?", True):
        write_launch_agent(LIVE_PLIST, "com.zanarkand.prompt-nudger", [], env)
        launch_agent(LIVE_PLIST, "com.zanarkand.prompt-nudger")
        print(f"Installed live helper LaunchAgent: {LIVE_PLIST}")

    interval_minutes = ask("Send periodic prompt reminders every N minutes? Blank disables", "")
    if interval_minutes:
        try:
            minutes = max(1, int(interval_minutes))
        except ValueError:
            print("Skipping periodic reminder because the interval was not a number.")
            return
        write_launch_agent(
            REMINDER_PLIST,
            "com.zanarkand.prompt-nudger.reminder",
            ["--remind-now"],
            env,
            start_interval_seconds=minutes * 60,
        )
        launch_agent(REMINDER_PLIST, "com.zanarkand.prompt-nudger.reminder")
        print(f"Installed reminder LaunchAgent: {REMINDER_PLIST}")


def main() -> int:
    print("Prompt Nudger Codex installer")
    print("This installs local Codex hooks and optional background Telegram nudges.")
    copy_files()
    install_codex_hooks()
    enable_codex_hooks_feature()

    token = ask("Telegram bot token", secret=True)
    chat_id = ask("Telegram chat id")
    if token and chat_id and ask_yes_no("Send a Telegram test message now?", True):
        result = subprocess.run(
            [sys.executable, str(BIN_SCRIPT), "--send-test"],
            check=False,
            env={**os.environ, "TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": chat_id},
        )
        if result.returncode != 0:
            print("Telegram test failed. Check the token/chat id, then run prompt_nudger.py --send-test.")

    if token and chat_id:
        install_launch_agents(token, chat_id)
    else:
        print("Skipped LaunchAgent setup because Telegram credentials were missing.")

    print("\nInstalled:")
    print(f"- Prompt Nudger script: {BIN_SCRIPT}")
    print(f"- Codex hook: {CODEX_HOOK}")
    print(f"- Codex hooks config: {CODEX_HOOKS_JSON}")
    print(f"- Codex feature flag: {CODEX_CONFIG_TOML}")
    print("\nRestart Codex or open a new Codex session so hook changes take effect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
