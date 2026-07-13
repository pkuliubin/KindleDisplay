#!/usr/bin/env bash
set -euo pipefail

KINDLE_HOST="${KINDLE_HOST:-192.168.15.244}"
KINDLE_SSH_KEY="${KINDLE_SSH_KEY:-$(dirname "$0")/kindle_ed25519}"
LAYOUT_MODE=0

if [[ "${1:-}" == "--layout" ]]; then
  LAYOUT_MODE=1
  shift
fi

if [[ ! -r "$KINDLE_SSH_KEY" ]]; then
  echo "Kindle SSH key is not readable: $KINDLE_SSH_KEY" >&2
  exit 2
fi

if (( LAYOUT_MODE )); then
  LAYOUT_FILE="$(mktemp "${TMPDIR:-/tmp}/kindle-layout.XXXXXX")"
  trap 'rm -f "$LAYOUT_FILE"' EXIT
  cat > "$LAYOUT_FILE"

  shell_quote() {
    printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
  }

  REMOTE_COMMAND='echo "14 2" > /proc/eink_fb/update_display; '
  TAB=$(printf "\t")
  first=1
  while IFS="$TAB" read -r size column pixel_top pixel_left text; do
    case "$size:$column:$pixel_top:$pixel_left" in
      *[!0-9:]* | ::* | *::) echo "Invalid layout coordinates" >&2; exit 2 ;;
    esac
    clear_flag=''
    if [ "$first" -eq 1 ]; then
      clear_flag=' -c'
      first=0
    fi
    REMOTE_COMMAND+="/mnt/us/fbink -q${clear_flag} -S ${size} -x ${column} -X ${pixel_left} -y 0 -Y ${pixel_top} -- $(shell_quote "$text"); "
  done < "$LAYOUT_FILE"
  [ "$first" -eq 1 ] && exit 0
  ssh -n -i "$KINDLE_SSH_KEY" -o BatchMode=yes -o ConnectTimeout=5 "root@$KINDLE_HOST" "$REMOTE_COMMAND"
else
  if [[ $# -gt 0 ]]; then
    printf '%s' "$1"
  else
    cat
  fi | ssh -i "$KINDLE_SSH_KEY" -o BatchMode=yes -o ConnectTimeout=5 "root@$KINDLE_HOST" \
    'cat > /tmp/kindle-display.txt; echo "14 2" > /proc/eink_fb/update_display; /mnt/us/fbink -q -c -S 3 -x 1 -y 1 "$(cat /tmp/kindle-display.txt)"'
fi
