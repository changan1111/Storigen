#!/bin/bash
# Mac install: creates the settings, then a launchd job so Auto-ID starts when this Mac user logs in and restarts if it stops.
# Run it as the dedicated user that will stay logged in on the Mac mini:   ./deploy/mac/install_mac.sh
set -e
cd "$(dirname "$0")/../.."; HOME_DIR="$(pwd)"
PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "python3 not found. Install Python 3.9 or newer from python.org (or run: xcode-select --install), then run this again."; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || { echo "Python is older than 3.9. Install a newer one from python.org."; exit 1; }
"$PY" autoid.py init "${1:-admin@autoid.local}" || true
PLIST="$HOME/Library/LaunchAgents/com.autoid.lite.plist"; mkdir -p "$HOME/Library/LaunchAgents" "$HOME_DIR/data/logs"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.autoid.lite</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$HOME_DIR/autoid.py</string><string>run</string></array>
  <key>WorkingDirectory</key><string>$HOME_DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$HOME_DIR/data/logs/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$HOME_DIR/data/logs/launchd.err.log</string>
</dict></plist>
PL
RPLIST="$HOME/Library/LaunchAgents/com.autoid.lite.restart.plist"      # nightly restart at 04:30, before the 05:00 broadcast-day change
cat > "$RPLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.autoid.lite.restart</string>
  <key>ProgramArguments</key><array><string>/bin/launchctl</string><string>kickstart</string><string>-k</string><string>gui/$(id -u)/com.autoid.lite</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>4</integer><key>Minute</key><integer>30</integer></dict>
</dict></plist>
PL
echo
echo "Installed: $PLIST"
echo "Nightly restart (04:30): $RPLIST   (start it with: launchctl load -w \"$RPLIST\")"
echo "Before starting it:"
echo "  1. Edit $HOME_DIR/autoid.env (folders, LINK_MODE) and run:  $PY autoid.py doctor"
echo "  2. Mount the Playout and Nitro shares at login (see deploy/mac/mount_shares.sh)."
echo "Then start it:   launchctl load -w \"$PLIST\"      (stop: launchctl unload \"$PLIST\")"
echo "Check it:        $PY autoid.py status"
