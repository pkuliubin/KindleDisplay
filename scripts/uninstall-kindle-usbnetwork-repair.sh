#!/usr/bin/env bash
set -euo pipefail

LABEL="com.kindle-display.usbnetwork-repair"
DAEMON_PATH="/Library/LaunchDaemons/$LABEL.plist"

sudo /bin/launchctl bootout system "$DAEMON_PATH" 2>/dev/null || true
sudo /bin/rm -f "$DAEMON_PATH" \
  /usr/local/libexec/kindle-display/kindle-usbnetwork-repair.sh
sudo /bin/rmdir /usr/local/libexec/kindle-display 2>/dev/null || true
echo "Removed $LABEL."
