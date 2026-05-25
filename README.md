# Prompt Nudger

One local Python script that nudges you on Telegram when you have been typing for a while.

Prompt Nudger is the tiny standalone version of the activity nudge loop. It does not need Convex, Aikage, or any backend. Raw keys and typed text stay local; the script only counts activity weights and sends a Telegram message after the local threshold, grace delay, and cooldown allow it.

## Quick Start

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

## Config

All config is environment variables.

| Env var | Default | Meaning |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | empty | Telegram bot token. Required unless `NUDGE_DRY_RUN=1`. |
| `TELEGRAM_CHAT_ID` | empty | Telegram chat/user id. Required unless `NUDGE_DRY_RUN=1`. |
| `NUDGE_MESSAGE` | natural prompt | Message shown before diagnostics. |
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

## Privacy

The script does not store or send typed text, raw key names, foreground app names, prompts, repo paths, or clipboard content. Telegram receives only your configured message and optional coarse diagnostics.
