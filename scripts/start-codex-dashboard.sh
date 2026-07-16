#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-60}"
LAST_CONTENT=""

while true; do
  CONTENT="$(PYTHONPATH="$SCRIPT_DIR/../src${PYTHONPATH:+:$PYTHONPATH}" \
    "$SCRIPT_DIR/preview_codex_status.py" --layout)"
  if [[ "$CONTENT" != "$LAST_CONTENT" ]]; then
    if printf '%s\n' "$CONTENT" | "$SCRIPT_DIR/kindle-display.sh" --layout; then
      LAST_CONTENT="$CONTENT"
    else
      echo "$(date '+%H:%M:%S') Kindle update failed; retrying." >&2
    fi
  fi
  sleep "$INTERVAL_SECONDS"
done
