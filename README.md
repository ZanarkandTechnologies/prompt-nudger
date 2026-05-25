# Prompt Nudger

One local Python script that nudges you on Telegram when you have been typing for a while.

Prompt Nudger is the tiny standalone version of the activity nudge loop. It does not need Convex, Aikage, or any backend. Raw keys and typed text stay local; the script only counts activity weights and sends a Telegram message after the local threshold, grace delay, and cooldown allow it.

## Quick Start

Install the local CLI:

```bash
git clone https://github.com/ZanarkandTechnologies/prompt-nudger.git
cd prompt-nudger
./install.sh
```

Then run the Codex setup wizard:

```bash
prompt-nudger-install-codex
```

The CLI installer gives you:

- `prompt-nudger`
- `prompt-nudger-install-codex`

The Codex setup wizard will:

- copy Prompt Nudger into `~/.prompt-nudger`
- install the local Codex hooks
- enable `codex_hooks = true`
- optionally send a Telegram test message
- optionally start the live typing nudger in the background
- offer to install PyObjC into a private `~/.prompt-nudger/venv` when live keyboard mode needs it
- optionally create a periodic reminder every configurable number of minutes

The setup wizard stores Telegram credentials only in your local LaunchAgent plist. If you prefer manual setup, use the steps below.

Common commands:

```bash
prompt-nudger --print-config
prompt-nudger --send-test
prompt-nudger --remind-now
prompt-nudger --pulse
prompt-nudger-install-codex --status
prompt-nudger-install-codex --stop
```

Use `prompt-nudger-install-codex --stop` to turn off the background live helper and periodic reminder without deleting your files or config.

## Manual Setup

```bash
git clone https://github.com/ZanarkandTechnologies/prompt-nudger.git
cd prompt-nudger
python3 -m py_compile prompt_nudger.py
chmod +x prompt_nudger.py
```

Set Telegram credentials:

```bash
export TELEGRAM_BOT_TOKEN="replace-with-bot-token"
export TELEGRAM_CHAT_ID="123456789"
```

Send a setup test:

```bash
./prompt_nudger.py --send-test
```

Run live macOS keyboard activity monitoring:

```bash
./prompt_nudger.py
```

macOS live mode requires Accessibility permission for the terminal app running the script. The event tap is listen-only.
It also needs PyObjC:

```bash
python3 -m pip install pyobjc
```

The Codex setup wizard can install this into a private Prompt Nudger environment for you.
Codex hooks, shortcut pulses, and periodic reminders still work without PyObjC.

## WisprFlow / Raycast / BetterTouchTool

Run the helper in a long-lived terminal:

```bash
./prompt_nudger.py
```

Then make your shortcut run:

```bash
/path/to/prompt_nudger.py --pulse
```

The pulse command appends one local marker to a pulse file. The running helper polls that file and treats each pulse as activity.

## Codex Hooks

Prompt Nudger can suppress Telegram nudges while a local Codex turn is active. Install the hook:

```bash
mkdir -p ~/.codex/hooks
cp hooks/codex_activity.py ~/.codex/hooks/prompt_nudger_codex_activity.py
chmod +x ~/.codex/hooks/prompt_nudger_codex_activity.py
```

Then merge these entries into `~/.codex/hooks.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$HOME/.codex/hooks/prompt_nudger_codex_activity.py\"",
            "statusMessage": "Marking Prompt Nudger active work",
            "timeout": 5
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$HOME/.codex/hooks/prompt_nudger_codex_activity.py\"",
            "statusMessage": "Clearing Prompt Nudger active work",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

Make sure Codex hooks are enabled in `~/.codex/config.toml`:

```toml
[features]
codex_hooks = true
```

The hook writes only local state to `~/.prompt-nudger/active.json`. It does not send network requests.

## Config

All config is environment variables.

| Env var | Default | Meaning |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | empty | Telegram bot token. Required unless `NUDGE_DRY_RUN=1`. |
| `TELEGRAM_CHAT_ID` | empty | Telegram chat/user id. Required unless `NUDGE_DRY_RUN=1`. |
| `NUDGE_MESSAGE` | natural prompt | Message shown before diagnostics. |
| `NUDGE_REMINDER_MESSAGE` | natural reminder | Message sent by `--remind-now` and the periodic LaunchAgent. |
| `NUDGE_INCLUDE_DETAILS` | `1` | Add machine, score, and observed timestamp after a blank line. |
| `NUDGE_DRY_RUN` | `0` | Print the message instead of sending Telegram. |
| `NUDGE_MACHINE_NAME` | hostname | Displayed in message details. |
| `NUDGE_ACTIVITY_THRESHOLD` | `20` | Score required before a nudge candidate is evaluated. |
| `NUDGE_WINDOW_SECONDS` | `300` | Rolling activity scoring window. |
| `NUDGE_GRACE_SECONDS` | `3` | Debounce delay after crossing the threshold. |
| `NUDGE_COOLDOWN_SECONDS` | `60` | Minimum delay between Telegram sends. |
| `NUDGE_PULSE_FILE` | `~/.prompt-nudger/pulse.log` | Local marker file for shortcut pulses. |
| `NUDGE_PULSE_WEIGHT` | `25` | Score added per pulse. |
| `NUDGE_PULSE_POLL_SECONDS` | `0.5` | Pulse file polling interval. |
| `NUDGE_SUPPRESS_WHEN_ACTIVE` | `1` | Suppress nudges while local hook state says Codex work is active. |
| `NUDGE_ACTIVE_STATE_FILE` | `~/.prompt-nudger/active.json` | Local active-work state written by `hooks/codex_activity.py`. |
| `NUDGE_ACTIVE_STATE_TTL_SECONDS` | `21600` | Ignore active-work state older than this. |
| `NUDGE_SUPPRESS_PROCESS_NAMES` | empty | Comma-separated process name patterns; suppress nudges if any match `pgrep -f`. |

Example:

```bash
export NUDGE_ACTIVITY_THRESHOLD=20
export NUDGE_GRACE_SECONDS=3
export NUDGE_COOLDOWN_SECONDS=60
export NUDGE_MESSAGE="You have been writing for a bit. Want to start another agent?"
./prompt_nudger.py
```

## Local Testing

Print safe config:

```bash
./prompt_nudger.py --print-config
```

Test the nudge pipeline without keyboard permissions:

```bash
NUDGE_DRY_RUN=1 ./prompt_nudger.py --test-key-event
```

Test a shortcut pulse:

```bash
./prompt_nudger.py --pulse
```

Send one periodic-reminder style message now:

```bash
./prompt_nudger.py --remind-now
```

Test Codex active-work suppression:

```bash
STATE="$(mktemp)"
printf '{"hook_event_name":"UserPromptSubmit","session_id":"demo","turn_id":"one"}' \
  | NUDGE_ACTIVE_STATE_FILE="$STATE" ./hooks/codex_activity.py
NUDGE_DRY_RUN=1 NUDGE_ACTIVE_STATE_FILE="$STATE" ./prompt_nudger.py --test-key-event
printf '{"hook_event_name":"Stop","session_id":"demo","turn_id":"one"}' \
  | NUDGE_ACTIVE_STATE_FILE="$STATE" ./hooks/codex_activity.py
```

## Install as a LaunchAgent

Create `~/Library/LaunchAgents/com.zanarkand.prompt-nudger.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.zanarkand.prompt-nudger</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/path/to/prompt_nudger.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>TELEGRAM_BOT_TOKEN</key>
    <string>replace-me</string>
    <key>TELEGRAM_CHAT_ID</key>
    <string>replace-me</string>
    <key>NUDGE_ACTIVITY_THRESHOLD</key>
    <string>20</string>
    <key>NUDGE_COOLDOWN_SECONDS</key>
    <string>60</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
</dict>
</plist>
```

Load it:

```bash
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.zanarkand.prompt-nudger.plist
launchctl kickstart -k "gui/$(id -u)/com.zanarkand.prompt-nudger"
```

## Periodic Prompt Reminders

The installer can create this automatically. For manual setup, create a second LaunchAgent:

`~/Library/LaunchAgents/com.zanarkand.prompt-nudger.reminder.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.zanarkand.prompt-nudger.reminder</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/path/to/prompt_nudger.py</string>
    <string>--remind-now</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>TELEGRAM_BOT_TOKEN</key>
    <string>replace-me</string>
    <key>TELEGRAM_CHAT_ID</key>
    <string>replace-me</string>
    <key>NUDGE_REMINDER_MESSAGE</key>
    <string>Quick reminder: write another prompt and keep the loop moving.</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>900</integer>
</dict>
</plist>
```

`StartInterval` is seconds. `900` means every 15 minutes; `3600` means every hour.

Load it:

```bash
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.zanarkand.prompt-nudger.reminder.plist
launchctl kickstart -k "gui/$(id -u)/com.zanarkand.prompt-nudger.reminder"
```

## Privacy

The script does not store or send typed text, raw key names, foreground app names, prompts, repo paths, or clipboard content. Telegram receives only your configured message and optional coarse diagnostics.
