#!/usr/bin/env python3
"""Standalone local activity nudges over Telegram.

The helper keeps all raw input local. It only counts activity weights, then
sends a Telegram message when the local threshold, debounce, and cooldown allow.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


HELPER_VERSION = "0.1.0"
SEPARATOR_KEYCODES = {36, 48, 49, 51, 76}
DEFAULT_ACTIVITY_MESSAGE = "Hey, you've been writing for a bit. Want to spin up another agent thread?"
DEFAULT_REMINDER_MESSAGE = "Nothing is running right now.\nWant to start a thread?"


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    telegram_chat_id: str
    message: str
    reminder_message: str
    include_details: bool
    dry_run: bool
    machine_name: str
    activity_threshold: int
    window_seconds: int
    grace_seconds: int
    cooldown_seconds: int
    pulse_file: Path
    pulse_weight: int
    pulse_poll_seconds: float
    suppress_when_active: bool
    active_state_file: Path
    active_state_ttl_seconds: int
    suppress_process_names: tuple[str, ...]


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def env_int(name: str, default: int, minimum: int, maximum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = max(minimum, int(raw))
    except ValueError:
        return default
    if maximum is not None:
        return min(maximum, value)
    return value


def env_float(name: str, default: float, minimum: float, maximum: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = max(minimum, float(raw))
    except ValueError:
        return default
    if maximum is not None:
        return min(maximum, value)
    return value


def clean_text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    return trimmed[:limit]


def load_config() -> Config:
    suppress_process_names = tuple(
        name.strip()
        for name in os.getenv("NUDGE_SUPPRESS_PROCESS_NAMES", "").split(",")
        if name.strip()
    )
    return Config(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        message=os.getenv(
            "NUDGE_MESSAGE",
            DEFAULT_ACTIVITY_MESSAGE,
        ).strip(),
        reminder_message=os.getenv(
            "NUDGE_REMINDER_MESSAGE",
            DEFAULT_REMINDER_MESSAGE,
        ).strip(),
        include_details=env_bool("NUDGE_INCLUDE_DETAILS", True),
        dry_run=env_bool("NUDGE_DRY_RUN", False),
        machine_name=clean_text(os.getenv("NUDGE_MACHINE_NAME"), 120)
        or clean_text(socket.gethostname(), 120)
        or "unknown-machine",
        activity_threshold=env_int("NUDGE_ACTIVITY_THRESHOLD", 20, 1, 10_000),
        window_seconds=env_int("NUDGE_WINDOW_SECONDS", 300, 1, 24 * 60 * 60),
        grace_seconds=env_int("NUDGE_GRACE_SECONDS", 3, 0, 15 * 60),
        cooldown_seconds=env_int("NUDGE_COOLDOWN_SECONDS", 60, 0, 24 * 60 * 60),
        pulse_file=Path(os.getenv("NUDGE_PULSE_FILE", "~/.prompt-nudger/pulse.log")).expanduser(),
        pulse_weight=env_int("NUDGE_PULSE_WEIGHT", 25, 1, 10_000),
        pulse_poll_seconds=env_float("NUDGE_PULSE_POLL_SECONDS", 0.5, 0.1, 60),
        suppress_when_active=env_bool("NUDGE_SUPPRESS_WHEN_ACTIVE", True),
        active_state_file=Path(os.getenv("NUDGE_ACTIVE_STATE_FILE", "~/.prompt-nudger/active.json")).expanduser(),
        active_state_ttl_seconds=env_int("NUDGE_ACTIVE_STATE_TTL_SECONDS", 6 * 60 * 60, 1, 7 * 24 * 60 * 60),
        suppress_process_names=suppress_process_names,
    )


def now_ms() -> int:
    return int(time.time() * 1000)


def ensure_pulse_file(config: Config) -> None:
    config.pulse_file.parent.mkdir(parents=True, exist_ok=True)
    config.pulse_file.touch(exist_ok=True)


def append_pulse(config: Config) -> None:
    ensure_pulse_file(config)
    with config.pulse_file.open("a", encoding="utf-8") as file:
        file.write(f"{now_ms()}\n")
    print("prompt-nudger: recorded local activity pulse")


def poll_pulse_file(config: Config, window: "ActivityWindow") -> None:
    ensure_pulse_file(config)
    position = config.pulse_file.stat().st_size
    while True:
        try:
            with config.pulse_file.open("r", encoding="utf-8") as file:
                file.seek(position)
                lines = [line for line in file.readlines() if line.strip()]
                position = file.tell()
            if lines:
                window.add(config.pulse_weight * len(lines))
        except OSError as error:
            print(f"prompt-nudger: pulse read failed: {error}", file=sys.stderr)
        time.sleep(config.pulse_poll_seconds)


def has_suppressed_process(config: Config) -> bool:
    for process_name in config.suppress_process_names:
        try:
            result = subprocess.run(
                ["pgrep", "-f", process_name],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return False
        if result.returncode == 0:
            return True
    return False


def read_active_state(config: Config) -> dict[str, Any] | None:
    try:
        with config.active_state_file.open("r", encoding="utf-8") as file:
            state = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None
    return state if isinstance(state, dict) else None


def active_count_from_state(state: dict[str, Any]) -> int:
    active_count = state.get("active_count")
    if isinstance(active_count, int):
        return max(0, active_count)

    active_turns = state.get("active_turns")
    if isinstance(active_turns, dict):
        return len(active_turns)
    return 0


def active_state_age_seconds(config: Config, state: dict[str, Any]) -> float | None:
    updated_at = state.get("updated_at")
    if not isinstance(updated_at, (int, float)):
        return None
    return max(0.0, time.time() - float(updated_at))


def has_active_local_work(config: Config) -> bool:
    if not config.suppress_when_active:
        return False
    state = read_active_state(config)
    if state is None:
        return False

    age_seconds = active_state_age_seconds(config, state)
    if age_seconds is None:
        return False
    if age_seconds > config.active_state_ttl_seconds:
        return False

    return active_count_from_state(state) > 0


def build_activity_message(config: Config, score: int, observed_at_ms: int) -> str:
    text = config.message or "Want to spin up another agent thread?"
    if not config.include_details:
        return text
    details = [
        "",
        f"Machine: {config.machine_name}",
        f"Activity score: {score}",
        f"Observed: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(observed_at_ms / 1000))}",
    ]
    return "\n".join([text, *details])


def build_reminder_message(config: Config, observed_at_ms: int) -> str:
    text = config.reminder_message or "Write another prompt and keep the loop moving."
    if not config.include_details:
        return text
    details = [
        "",
        f"Machine: {config.machine_name}",
        f"Observed: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(observed_at_ms / 1000))}",
    ]
    return "\n".join([text, *details])


def send_telegram_text(config: Config, text: str) -> bool:
    if config.dry_run:
        print("prompt-nudger: dry run telegram message")
        print(text)
        return True
    if not config.telegram_bot_token or not config.telegram_chat_id:
        print("prompt-nudger: missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID", file=sys.stderr)
        return False

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage",
        data=json.dumps({"chat_id": config.telegram_chat_id, "text": text}).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
        print("prompt-nudger: sent")
        return True
    except urllib.error.URLError as error:
        print(f"prompt-nudger: telegram failed: {error}", file=sys.stderr)
        return False


def send_activity_nudge(config: Config, score: int, observed_at_ms: int) -> bool:
    return send_telegram_text(config, build_activity_message(config, score, observed_at_ms))


def send_reminder(config: Config) -> bool:
    if has_active_local_work(config) or has_suppressed_process(config):
        print("prompt-nudger: reminder suppressed because local work is active")
        return True
    return send_telegram_text(config, build_reminder_message(config, now_ms()))


class ActivityWindow:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.events: list[tuple[int, int]] = []
        self.last_request_at = 0
        self.evaluating = False
        self.lock = threading.Lock()

    def add(self, weight: int) -> None:
        timestamp = now_ms()
        cutoff = timestamp - self.config.window_seconds * 1000
        should_evaluate = False
        with self.lock:
            self.events = [(at, event_weight) for at, event_weight in self.events if at >= cutoff]
            self.events.append((timestamp, max(0, weight)))
            score = sum(event_weight for _, event_weight in self.events)
            cooled_down = timestamp - self.last_request_at >= self.config.cooldown_seconds * 1000
            if score >= self.config.activity_threshold and cooled_down and not self.evaluating:
                self.evaluating = True
                should_evaluate = True

        if should_evaluate:
            threading.Thread(target=self.evaluate, daemon=True).start()

    def snapshot(self) -> tuple[int, int, int, int]:
        with self.lock:
            if not self.events:
                timestamp = now_ms()
                return 0, timestamp, timestamp, 0
            started_at = self.events[0][0]
            ended_at = self.events[-1][0]
            score = sum(event_weight for _, event_weight in self.events)
            return score, started_at, ended_at, max(0, ended_at - started_at)

    def reset_after_request(self) -> None:
        with self.lock:
            self.events = []
            self.last_request_at = now_ms()
            self.evaluating = False

    def clear_evaluating(self) -> None:
        with self.lock:
            self.evaluating = False

    def evaluate(self) -> None:
        try:
            time.sleep(self.config.grace_seconds)
            score, _started_at, ended_at, _window_ms = self.snapshot()
            if score < self.config.activity_threshold:
                self.clear_evaluating()
                return
            if has_active_local_work(self.config) or has_suppressed_process(self.config):
                self.reset_after_request()
                return
            send_activity_nudge(self.config, score, ended_at)
            self.reset_after_request()
        except Exception as error:
            print(f"prompt-nudger: evaluation failed: {error}", file=sys.stderr)
            self.clear_evaluating()


def ensure_listen_event_access(quartz: Any) -> bool:
    preflight = getattr(quartz, "CGPreflightListenEventAccess", None)
    request = getattr(quartz, "CGRequestListenEventAccess", None)
    if callable(preflight):
        try:
            if preflight():
                return True
        except Exception as error:
            print(f"prompt-nudger: accessibility preflight failed: {error}", file=sys.stderr)

    if callable(request):
        print("prompt-nudger: requesting macOS Accessibility permission.")
        try:
            if request():
                return True
        except Exception as error:
            print(f"prompt-nudger: accessibility request failed: {error}", file=sys.stderr)
        print("prompt-nudger: grant Accessibility permission and restart live mode.", file=sys.stderr)
        return False
    return True


def run_live(config: Config) -> int:
    if platform.system() != "Darwin":
        print("prompt-nudger: live mode currently requires macOS. Use --pulse or --test-key-event elsewhere.", file=sys.stderr)
        return 2

    try:
        import CoreFoundation  # type: ignore[import-not-found]
        import Quartz  # type: ignore[import-not-found]
    except Exception as error:
        print(f"prompt-nudger: install PyObjC for live mode: {error}", file=sys.stderr)
        return 2

    if not ensure_listen_event_access(Quartz):
        return 2

    window = ActivityWindow(config)
    threading.Thread(target=poll_pulse_file, args=(config, window), daemon=True).start()

    def callback(proxy: Any, event_type: Any, event: Any, refcon: Any) -> Any:
        keycode = int(Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode))
        window.add(3 if keycode in SEPARATOR_KEYCODES else 1)
        return event

    event_mask = Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionListenOnly,
        event_mask,
        callback,
        None,
    )
    if tap is None:
        print("prompt-nudger: could not create event tap. Grant Accessibility permission.", file=sys.stderr)
        return 2

    source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    CoreFoundation.CFRunLoopAddSource(CoreFoundation.CFRunLoopGetCurrent(), source, CoreFoundation.kCFRunLoopCommonModes)
    Quartz.CGEventTapEnable(tap, True)
    print("prompt-nudger: live helper running. Raw keys and typed text stay local.")
    CoreFoundation.CFRunLoopRun()
    return 0


def run_test_key_event(config: Config) -> int:
    window = ActivityWindow(config)
    window.add(config.activity_threshold)
    while True:
        with window.lock:
            pending = window.evaluating
        if not pending:
            return 0
        time.sleep(0.05)


def print_config(config: Config) -> None:
    safe_config = {
        "telegram_bot_token": "set" if config.telegram_bot_token else "missing",
        "telegram_chat_id": "set" if config.telegram_chat_id else "missing",
        "message": config.message,
        "reminder_message": config.reminder_message,
        "include_details": config.include_details,
        "dry_run": config.dry_run,
        "machine_name": config.machine_name,
        "activity_threshold": config.activity_threshold,
        "window_seconds": config.window_seconds,
        "grace_seconds": config.grace_seconds,
        "cooldown_seconds": config.cooldown_seconds,
        "pulse_file": str(config.pulse_file),
        "pulse_weight": config.pulse_weight,
        "pulse_poll_seconds": config.pulse_poll_seconds,
        "suppress_when_active": config.suppress_when_active,
        "active_state_file": str(config.active_state_file),
        "active_state_ttl_seconds": config.active_state_ttl_seconds,
        "suppress_process_names": config.suppress_process_names,
    }
    print(json.dumps(safe_config, indent=2))


def get_status(config: Config) -> dict[str, Any]:
    state = read_active_state(config)
    state_age_seconds = active_state_age_seconds(config, state) if state is not None else None
    state_is_fresh = state_age_seconds is not None and state_age_seconds <= config.active_state_ttl_seconds
    active_count = active_count_from_state(state) if state is not None and state_is_fresh else 0
    return {
        "telegram_configured": bool(config.telegram_bot_token and config.telegram_chat_id),
        "dry_run": config.dry_run,
        "live_suppression_enabled": config.suppress_when_active,
        "local_active_work": active_count > 0,
        "local_active_count": active_count,
        "active_state_file": str(config.active_state_file),
        "active_state_seen": state is not None,
        "active_state_fresh": state_is_fresh,
        "active_state_age_seconds": round(state_age_seconds, 3) if state_age_seconds is not None else None,
        "suppressed_process_running": has_suppressed_process(config),
        "cooldown_seconds": config.cooldown_seconds,
        "reminder_message": config.reminder_message,
    }


def print_status(config: Config) -> None:
    print(json.dumps(get_status(config), indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Standalone local Telegram nudges for sustained typing.")
    parser.add_argument("--live", action="store_true", help="Run macOS listen-only keyboard activity monitor")
    parser.add_argument("--pulse", action="store_true", help="Record one shortcut pulse for a running live helper")
    parser.add_argument("--remind-now", action="store_true", help="Send one scheduled prompt reminder immediately")
    parser.add_argument("--send-test", action="store_true", help="Send one Telegram test message immediately")
    parser.add_argument("--test-key-event", action="store_true", help="Inject one local key-event weight into the nudge pipeline")
    parser.add_argument("--print-config", action="store_true", help="Print safe effective config without secrets")
    parser.add_argument("--status", action="store_true", help="Print safe runtime status and local active-work state")
    args = parser.parse_args()
    config = load_config()

    if args.print_config:
        print_config(config)
        return 0
    if args.status:
        print_status(config)
        return 0
    if args.pulse:
        append_pulse(config)
        return 0
    if args.remind_now:
        return 0 if send_reminder(config) else 1
    if args.send_test:
        return 0 if send_activity_nudge(config, config.activity_threshold, now_ms()) else 1
    if args.test_key_event:
        return run_test_key_event(config)
    return run_live(config)


if __name__ == "__main__":
    raise SystemExit(main())
