#!/bin/bash
# Installs Hush on macOS for the current user: venv, Discord app keys, login LaunchAgent.
# Usage: ./install.sh [--uninstall]
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.gigolajulian.hush"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
STATE="$HOME/Library/Application Support/Hush"
DOMAIN="gui/$(id -u)"

if [[ "${1:-}" == "--uninstall" ]]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed. Your Discord keys and login token stay in $STATE."
  exit 0
fi

# 1. Python env
[[ -d "$DIR/.venv" ]] || python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/python" -m pip install -q --disable-pip-version-check -r "$DIR/requirements.txt"
"$DIR/.venv/bin/python" "$DIR/test_hush.py"

# 2. Discord app keys, kept in a file only you can read (a LaunchAgent does not see shell env vars)
mkdir -p "$STATE"
if [[ ! -s "$STATE/keys.json" ]]; then
  read -r -p "Discord Client ID: " ID
  [[ "$ID" =~ ^[0-9]{17,20}$ ]] || { echo "That does not look like a Client ID (17 to 20 digits)."; exit 1; }
  read -r -s -p "Discord Client Secret: " SECRET; echo
  [[ -n "$SECRET" ]] || { echo "No secret entered."; exit 1; }
  (umask 077; ID="$ID" SECRET="$SECRET" "$DIR/.venv/bin/python" -c 'import json, os, sys; json.dump({"DISCORD_CLIENT_ID": os.environ["ID"], "DISCORD_CLIENT_SECRET": os.environ["SECRET"]}, open(sys.argv[1], "w"))' "$STATE/keys.json")
fi

# 3. Start at login, and now
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$DIR/.venv/bin/python</string><string>$DIR/hush.py</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>RunAtLoad</key><true/>
  <key>AbandonProcessGroup</key><true/>
  <key>ProcessType</key><string>Interactive</string>
</dict></plist>
EOF
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Hush is running in the menu bar. Dictate once and click Authorize in Discord."
