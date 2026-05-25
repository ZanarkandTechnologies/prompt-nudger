#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
BIN_DIR="$PREFIX/bin"
APP_DIR="${PROMPT_NUDGER_HOME:-$HOME/.prompt-nudger}"

mkdir -p "$BIN_DIR" "$APP_DIR/hooks"

cp "$ROOT/prompt_nudger.py" "$APP_DIR/prompt_nudger.py"
cp "$ROOT/install_codex.py" "$APP_DIR/install_codex.py"
cp "$ROOT/hooks/codex_activity.py" "$APP_DIR/hooks/codex_activity.py"
chmod +x "$APP_DIR/prompt_nudger.py" "$APP_DIR/install_codex.py" "$APP_DIR/hooks/codex_activity.py"

cat > "$BIN_DIR/prompt-nudger" <<EOF
#!/usr/bin/env bash
exec python3 "$APP_DIR/prompt_nudger.py" "\$@"
EOF

cat > "$BIN_DIR/prompt-nudger-install-codex" <<EOF
#!/usr/bin/env bash
exec python3 "$APP_DIR/install_codex.py" "\$@"
EOF

chmod +x "$BIN_DIR/prompt-nudger" "$BIN_DIR/prompt-nudger-install-codex"

echo "Prompt Nudger installed."
echo
echo "Commands:"
echo "  prompt-nudger --print-config"
echo "  prompt-nudger --send-test"
echo "  prompt-nudger --remind-now"
echo "  prompt-nudger-install-codex"
echo "  prompt-nudger-install-codex --status"
echo "  prompt-nudger-install-codex --stop"
echo
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  echo "Add this to your shell profile if prompt-nudger is not found:"
  echo "  export PATH=\"$BIN_DIR:\$PATH\""
fi
