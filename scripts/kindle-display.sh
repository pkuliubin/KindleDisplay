#!/usr/bin/env bash
set -euo pipefail

KINDLE_HOST="${KINDLE_HOST:-192.168.15.244}"
KINDLE_SSH_KEY="${KINDLE_SSH_KEY:-$(dirname "$0")/kindle_ed25519}"
KINDLE_CJK_FONT="${KINDLE_CJK_FONT:-/mnt/us/fonts/SarasaMonoSC-Regular.ttf}"
KINDLE_CONNECT_TIMEOUT="${KINDLE_CONNECT_TIMEOUT:-5}"
LAYOUT_MODE=0
REFRESH_PROFILE="${KINDLE_REFRESH_PROFILE:-flash_clean}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --layout)
      LAYOUT_MODE=1
      shift
      ;;
    --refresh-profile)
      [[ $# -ge 2 ]] || { echo "Missing value for --refresh-profile" >&2; exit 2; }
      REFRESH_PROFILE="$2"
      shift 2
      ;;
    *)
      break
      ;;
  esac
done

case "$REFRESH_PROFILE" in
  clean) PAGE_REFRESH_FLAGS='-q -c' ;;
  flash_clean) PAGE_REFRESH_FLAGS='-q -f -c' ;;
  *) echo "Unknown refresh profile: $REFRESH_PROFILE" >&2; exit 2 ;;
esac

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

  # Draw every block into the framebuffer first, then refresh the E-Ink panel once.
  REMOTE_COMMAND='echo "14 2" > /proc/eink_fb/update_display; '
  TAB=$(printf "\t")
  first=1
  needs_refresh=0
  while IFS="$TAB" read -r size pixel_top pixel_left pixel_right renderer text; do
    case "$size:$pixel_top:$pixel_left:$pixel_right" in
      *[!0-9:]* | ::* | *::) echo "Invalid layout coordinates" >&2; exit 2 ;;
    esac
    case "$renderer" in
      ttf|ttf_page) ;;
      *) echo "Invalid layout renderer: $renderer" >&2; exit 2 ;;
    esac
    if [ "$renderer" = "ttf_page" ]; then
      page_text="${text//$'\036'/$'\n'}"
      REMOTE_COMMAND+="/mnt/us/fbink ${PAGE_REFRESH_FLAGS} -t $(shell_quote "regular=${KINDLE_CJK_FONT},px=${size},top=${pixel_top},bottom=20,left=${pixel_left},right=${pixel_right},notrunc") -- $(shell_quote "$page_text"); "
      first=0
      continue
    fi
    draw_flags=' -b'
    if [ "$first" -eq 1 ]; then
      draw_flags=' -c -b'
      first=0
    fi
    REMOTE_COMMAND+="/mnt/us/fbink -q${draw_flags} -t $(shell_quote "regular=${KINDLE_CJK_FONT},px=${size},top=${pixel_top},bottom=0,left=${pixel_left},right=${pixel_right},notrunc") -- $(shell_quote "$text"); "
    needs_refresh=1
  done < "$LAYOUT_FILE"
  [ "$first" -eq 1 ] && exit 0
  if [ "$needs_refresh" -eq 1 ]; then
    REMOTE_COMMAND+='/mnt/us/fbink -q -s; '
  fi
  ssh -n -i "$KINDLE_SSH_KEY" -o BatchMode=yes -o ConnectTimeout="$KINDLE_CONNECT_TIMEOUT" "root@$KINDLE_HOST" "$REMOTE_COMMAND"
else
  if [[ $# -gt 0 ]]; then
    printf '%s' "$1"
  else
    cat
  fi | ssh -i "$KINDLE_SSH_KEY" -o BatchMode=yes -o ConnectTimeout="$KINDLE_CONNECT_TIMEOUT" "root@$KINDLE_HOST" \
    'cat > /tmp/kindle-display.txt; echo "14 2" > /proc/eink_fb/update_display; /mnt/us/fbink -q -c -S 3 -x 1 -y 1 "$(cat /tmp/kindle-display.txt)"'
fi
