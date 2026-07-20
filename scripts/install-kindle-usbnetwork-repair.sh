#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LABEL="com.kindle-display.usbnetwork-repair"
INSTALL_DIR="/usr/local/libexec/kindle-display"
DAEMON_PATH="/Library/LaunchDaemons/$LABEL.plist"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer requires macOS." >&2
  exit 2
fi

sudo /usr/bin/install -d -m 755 "$INSTALL_DIR"
sudo /usr/bin/install -m 755 "$SCRIPT_DIR/kindle-usbnetwork-repair.sh" "$INSTALL_DIR/kindle-usbnetwork-repair.sh"
sudo /usr/bin/install -m 644 "$ROOT_DIR/config/$LABEL.plist" "$DAEMON_PATH"

# Reloading makes repeated installs update the service immediately.
sudo /bin/launchctl bootout system "$DAEMON_PATH" 2>/dev/null || true
sudo /bin/launchctl bootstrap system "$DAEMON_PATH"
echo "Installed $LABEL. RNDIS address repair now runs at boot and every 5 minutes."
