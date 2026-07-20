#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="RNDIS/Ethernet Gadget"
TARGET_IP="192.168.15.201"
TARGET_NETMASK="255.255.255.0"

device="$(/usr/sbin/networksetup -listallhardwareports | /usr/bin/awk -v service="$SERVICE_NAME" '
  $0 == "Hardware Port: " service { found = 1; next }
  found && /^Device: / { print $2; exit }
')"

# Kindle is unplugged or USBNetwork is disabled.
[[ -n "$device" ]] || exit 0

interface_info="$(/sbin/ifconfig "$device" 2>/dev/null || true)"
[[ "$interface_info" == *"status: active"* ]] || exit 0

current_ip="$(/usr/sbin/ipconfig getifaddr "$device" 2>/dev/null || true)"
[[ "$current_ip" == "$TARGET_IP" ]] && exit 0

/sbin/ifconfig "$device" inet "$TARGET_IP" netmask "$TARGET_NETMASK" up
