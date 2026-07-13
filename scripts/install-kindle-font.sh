#!/usr/bin/env bash
set -euo pipefail

KINDLE_HOST="${KINDLE_HOST:-192.168.15.244}"
KINDLE_SSH_KEY="${KINDLE_SSH_KEY:-$(dirname "$0")/kindle_ed25519}"
SARASA_VERSION="${SARASA_VERSION:-1.0.40}"
ARCHIVE_URL="${SARASA_ARCHIVE_URL:-https://github.com/be5invis/Sarasa-Gothic/releases/download/v${SARASA_VERSION}/SarasaMonoSC-TTF-Unhinted-${SARASA_VERSION}.7z}"
REMOTE_FONT="/mnt/us/fonts/SarasaMonoSC-Regular.ttf"

if [[ ! -r "$KINDLE_SSH_KEY" ]]; then
  echo "Kindle SSH key is not readable: $KINDLE_SSH_KEY" >&2
  exit 2
fi
if ! command -v bsdtar >/dev/null; then
  echo "bsdtar is required to extract the Sarasa font archive." >&2
  exit 2
fi

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/kindle-font.XXXXXX")"
trap 'rm -rf "$work_dir"' EXIT
archive="$work_dir/SarasaMonoSC.7z"
font="$work_dir/SarasaMonoSC-Regular.ttf"

curl -fL --retry 2 -o "$archive" "$ARCHIVE_URL"
bsdtar -xOf "$archive" SarasaMonoSC-Regular.ttf > "$font"

ssh -n -i "$KINDLE_SSH_KEY" -o BatchMode=yes -o ConnectTimeout=5 "root@$KINDLE_HOST" \
  'mkdir -p /mnt/us/fonts'
scp -q -i "$KINDLE_SSH_KEY" -o BatchMode=yes -o ConnectTimeout=10 "$font" "root@$KINDLE_HOST:$REMOTE_FONT"
echo "Installed Sarasa Mono SC at $REMOTE_FONT"
