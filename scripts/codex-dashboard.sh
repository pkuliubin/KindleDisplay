#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="${KINDLE_DISPLAY_RUN_DIR:-/tmp/kindle-display}"
PID_FILE="$RUN_DIR/codex-dashboard.pid"
LOG_FILE="$RUN_DIR/codex-dashboard.log"
KEY_PATH="${KINDLE_SSH_KEY:-$SCRIPT_DIR/kindle_ed25519}"

require_key() {
  if [[ ! -r "$KEY_PATH" ]]; then
    echo "Kindle SSH key is not readable: $KEY_PATH" >&2
    exit 2
  fi
}

render_layout() {
  PYTHONPATH="$SCRIPT_DIR/../src${PYTHONPATH:+:$PYTHONPATH}" \
    "$SCRIPT_DIR/preview_codex_status.py" --layout
}

start_dashboard() {
  mkdir -p "$RUN_DIR"
  if [[ -r "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Dashboard already running (PID $(cat "$PID_FILE"))."
    return 0
  fi
  rm -f "$PID_FILE"
  nohup "$SCRIPT_DIR/start-codex-dashboard.sh" > "$LOG_FILE" 2>&1 &
  echo "$!" > "$PID_FILE"
  echo "Dashboard started (PID $!, log: $LOG_FILE)."
}

stop_dashboard() {
  if [[ ! -r "$PID_FILE" ]]; then
    echo "Dashboard is not running."
    return 0
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    echo "Dashboard stopped (PID $pid)."
  else
    echo "Removed stale dashboard PID file ($pid)."
  fi
  rm -f "$PID_FILE"
}

status_dashboard() {
  if [[ -r "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Dashboard running (PID $(cat "$PID_FILE"), log: $LOG_FILE)."
  else
    echo "Dashboard is not running."
  fi
}

case "${1:-once}" in
  once)
    require_key
    render_layout | "$SCRIPT_DIR/kindle-display.sh" --layout
    ;;
  start)
    require_key
    start_dashboard
    ;;
  stop)
    stop_dashboard
    ;;
  status)
    status_dashboard
    ;;
  --print)
    render_layout
    ;;
  --verbose)
    require_key
    render_layout | tee /dev/stderr | "$SCRIPT_DIR/kindle-display.sh" --layout
    ;;
  *)
    echo "Usage: $0 [once|start|stop|status|--print|--verbose]" >&2
    exit 2
    ;;
esac
