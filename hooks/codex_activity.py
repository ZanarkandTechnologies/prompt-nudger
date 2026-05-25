#!/usr/bin/env python3
"""Codex hook for local Prompt Nudger active-work state.

Reads one Codex hook JSON payload from stdin and updates a small local state
file. It never sends network requests and should stay silent on stdout.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any


STATE_FILE = Path(os.getenv("NUDGE_ACTIVE_STATE_FILE", "~/.prompt-nudger/active.json")).expanduser()
STATE_TTL_SECONDS = int(os.getenv("NUDGE_ACTIVE_STATE_TTL_SECONDS", str(6 * 60 * 60)))


def clean_text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    return trimmed[:limit]


def turn_key(event: dict[str, Any]) -> str:
    session_id = clean_text(event.get("session_id"), 120) or "unknown-session"
    turn_id = clean_text(event.get("turn_id"), 120) or "unknown-turn"
    return f"{session_id}:{turn_id}"


def read_state() -> dict[str, Any]:
    try:
        with STATE_FILE.open("r", encoding="utf-8") as file:
            state = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}
    return state if isinstance(state, dict) else {}


def write_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = STATE_FILE.with_suffix(".tmp")
    with temp_file.open("w", encoding="utf-8") as file:
        json.dump(state, file, separators=(",", ":"))
    temp_file.replace(STATE_FILE)


def prune_active_turns(active_turns: dict[str, Any], now: float) -> dict[str, Any]:
    pruned: dict[str, Any] = {}
    for key, value in active_turns.items():
        if not isinstance(value, dict):
            continue
        started_at = value.get("started_at")
        if isinstance(started_at, (int, float)) and now - float(started_at) <= STATE_TTL_SECONDS:
            pruned[key] = value
    return pruned


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception as error:
        print(f"prompt-nudger hook: failed to parse stdin JSON: {error}", file=sys.stderr)
        return 0
    if not isinstance(event, dict):
        return 0

    now = time.time()
    state = read_state()
    active_turns = state.get("active_turns")
    active = prune_active_turns(active_turns if isinstance(active_turns, dict) else {}, now)
    key = turn_key(event)
    hook_event_name = event.get("hook_event_name")

    if hook_event_name == "UserPromptSubmit":
        active[key] = {
            "started_at": now,
            "session_id": clean_text(event.get("session_id"), 120),
            "turn_id": clean_text(event.get("turn_id"), 120),
        }
    elif hook_event_name == "Stop":
        active.pop(key, None)
        session_id = clean_text(event.get("session_id"), 120)
        if session_id and key.endswith(":unknown-turn"):
            active = {active_key: value for active_key, value in active.items() if not active_key.startswith(f"{session_id}:")}

    write_state(
        {
            "updated_at": now,
            "active_count": len(active),
            "active_turns": active,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
