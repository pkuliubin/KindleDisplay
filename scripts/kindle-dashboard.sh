#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_PATH="${KINDLE_DISPLAY_CONFIG:-$ROOT_DIR/config/dashboard.toml}"
RUN_DIR="${KINDLE_DISPLAY_RUN_DIR:-/tmp/kindle-display}"
PID_FILE="$RUN_DIR/kindle-dashboard.pid"
LEGACY_PID_FILE="$RUN_DIR/codex-dashboard.pid"
LOG_FILE="$RUN_DIR/kindle-dashboard.log"

run_cli() {
  PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m kindle_display.cli --config "$CONFIG_PATH" "$@"
}

start_dashboard() {
  mkdir -p "$RUN_DIR"
  if [[ -r "$LEGACY_PID_FILE" ]] && kill -0 "$(<"$LEGACY_PID_FILE")" 2>/dev/null; then
    echo "Legacy Codex dashboard is running (PID $(<"$LEGACY_PID_FILE")). Stop it before starting the unified dashboard." >&2
    return 1
  fi
  if [[ -r "$PID_FILE" ]] && kill -0 "$(<"$PID_FILE")" 2>/dev/null; then
    echo "Dashboard already running (PID $(<"$PID_FILE"))."
    return 0
  fi
  rm -f "$PID_FILE"
  run_cli validate
  nohup env PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m kindle_display.cli --config "$CONFIG_PATH" run > "$LOG_FILE" 2>&1 &
  echo "$!" > "$PID_FILE"
  sleep 0.2
  if ! kill -0 "$!" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "Dashboard failed to start; inspect $LOG_FILE." >&2
    return 1
  fi
  echo "Dashboard started (PID $!, log: $LOG_FILE)."
}

stop_dashboard() {
  if [[ ! -r "$PID_FILE" ]]; then
    echo "Dashboard is not running."
    return 0
  fi
  local pid
  pid="$(<"$PID_FILE")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    for _ in {1..50}; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.2
    done
    if kill -0 "$pid" 2>/dev/null; then
      echo "Dashboard is still stopping (PID $pid)." >&2
      return 1
    fi
    echo "Dashboard stopped (PID $pid)."
  else
    echo "Removed stale dashboard PID file ($pid)."
  fi
  rm -f "$PID_FILE"
}

status_dashboard() {
  if [[ -r "$PID_FILE" ]] && kill -0 "$(<"$PID_FILE")" 2>/dev/null; then
    echo "Dashboard running (PID $(<"$PID_FILE"), log: $LOG_FILE)."
    run_cli status || true
  else
    echo "Dashboard is not running."
  fi
}

case "${1:-once}" in
  start) start_dashboard ;;
  stop) stop_dashboard ;;
  status) status_dashboard ;;
  once)
    shift || true
    run_cli once "$@"
    ;;
  preview)
    shift
    run_cli preview "$@"
    ;;
  check) run_cli check ;;
  *)
    echo "Usage: $0 [start|stop|status|once|preview|check]" >&2
    exit 2
    ;;
esac
