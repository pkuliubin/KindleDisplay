# New Mac Setup

This guide connects a new Mac to the modified Kindle 4 and starts this repository's unified dashboard. Each Mac should use a separate SSH key. Never copy a private key into this repository or Git.

## 1. Return Kindle To USB Storage Mode

To add a new Mac's public key, Kindle must be in USB storage mode. If it is currently in USBNetwork mode, use an already authorized Mac:

```sh
KINDLE_SSH_KEY=/path/to/existing/kindle_key \
ssh -i "$KINDLE_SSH_KEY" -o BatchMode=yes root@192.168.15.244 \
  '/mnt/us/usbnet/bin/usbnetwork'
```

SSH will disconnect immediately. Unplug and reconnect USB; Kindle should appear as a Finder volume. If the old Mac is unavailable, turn off USBNetwork from KUAL and reconnect USB.

## 2. Generate A New Mac-Specific Key

Run on the new Mac:

```sh
ssh-keygen -t ed25519 -f "$HOME/.ssh/kindle_display_ed25519" -N "" -C "kindle-display-$(scutil --get ComputerName)"
chmod 600 "$HOME/.ssh/kindle_display_ed25519"
```

## 3. Add The New Public Key To Kindle

Assume Finder mounted Kindle at `/Volumes/Kindle`. Replace the value if its volume name differs.

```sh
export KINDLE_VOLUME=/Volumes/Kindle
test -d "$KINDLE_VOLUME/usbnet/etc" && echo "Kindle volume ready"
```

Only after the command prints `Kindle volume ready`, append the new public key and eject:

```sh
cat "$HOME/.ssh/kindle_display_ed25519.pub" >> "$KINDLE_VOLUME/usbnet/etc/authorized_keys"
diskutil eject "$KINDLE_VOLUME"
```

Use `>>`, not `>`, so existing Macs remain authorized.

## 4. Enable USBNetwork And Configure RNDIS

On Kindle, open `KUAL -> USBNetwork -> Enable`, then reconnect USB. The established addresses are:

```text
Kindle: 192.168.15.244
Mac:    192.168.15.201/24
```

Find the RNDIS interface with `ifconfig`. If it is `en7`, configure and test it:

```sh
sudo ifconfig en7 inet 192.168.15.201 netmask 255.255.255.0 up
ping -c 1 192.168.15.244
```

`en7` is an example only. A `169.254.*` address means the RNDIS interface still needs the fixed address above.

For frequent unplug/replug use, install the automatic repair service once from the repository root:

```sh
./scripts/install-kindle-usbnetwork-repair.sh
```

It installs a root-owned macOS LaunchDaemon. At boot and every five minutes, it finds the `RNDIS/Ethernet Gadget` service and restores `192.168.15.201/24` only when the Kindle interface is active and has another address. It does not run the dashboard as root. To remove it later:

```sh
./scripts/uninstall-kindle-usbnetwork-repair.sh
```

## 5. Verify SSH And FBInk

```sh
ssh -i "$HOME/.ssh/kindle_display_ed25519" -o BatchMode=yes \
  root@192.168.15.244 'test -x /mnt/us/fbink && echo FBInk-ready'
```

Expected result:

```text
FBInk-ready
```

## 6. Install The Chinese Font

Install the full, open-source, monospaced Sarasa Mono SC font to the Kindle.
This download happens once and does not depend on a macOS system font:

```sh
cd /path/to/KindleDisplay
KINDLE_SSH_KEY="$HOME/.ssh/kindle_display_ed25519" \
  ./scripts/install-kindle-font.sh
```

## 7. Persist Local Settings

Create the repository-local task configuration. It is ignored by Git:

```sh
cd /path/to/KindleDisplay
cp config/dashboard.example.toml config/dashboard.toml
```

Edit the Reddit task's `cwd` and `argv[0]` if `AlphaDecisionTaskManager` or its Python environment is elsewhere on this Mac.

Create a user-local environment file for device-specific settings:

```sh
mkdir -p "$HOME/.config/kindle-display"
cat > "$HOME/.config/kindle-display/env.zsh" <<'EOF'
export KINDLE_HOST=192.168.15.244
export KINDLE_SSH_KEY="$HOME/.ssh/kindle_display_ed25519"
EOF
```

Load it automatically for zsh sessions, then load it now:

```sh
grep -qxF 'source "$HOME/.config/kindle-display/env.zsh"' "$HOME/.zshrc" || \
  printf '\nsource "$HOME/.config/kindle-display/env.zsh"\n' >> "$HOME/.zshrc"
source "$HOME/.config/kindle-display/env.zsh"
```

Collection periods, task weights, page budgets, and the periodic full-refresh interval are configured in `config/dashboard.toml`.

## 8. Run The Dashboard

```sh
cd /path/to/KindleDisplay
./scripts/kindle-dashboard.sh check
./scripts/kindle-dashboard.sh once --task codex
./scripts/kindle-dashboard.sh start
./scripts/kindle-dashboard.sh status
./scripts/kindle-dashboard.sh stop
```

`check` collects and validates all configured tasks without sending anything to Kindle. The legacy `codex-dashboard.sh` is retained only for compatibility and must not run alongside the unified dashboard.

## Troubleshooting

| Symptom | Check | Fix |
| --- | --- | --- |
| `Kindle SSH key is not readable` | `$KINDLE_SSH_KEY` | Run `source ~/.config/kindle-display/env.zsh`; verify the key exists and is `0600`. |
| `ping` times out | RNDIS address | Set the actual RNDIS interface to `192.168.15.201/24`, not `169.254.*`. |
| SSH permission denied | Kindle public key | Return to USB storage mode and re-check `usbnet/etc/authorized_keys`. |
| Dashboard does not render | SSH and FBInk | Complete step 5, then run `./scripts/kindle-dashboard.sh once --task codex`. |
| Reddit check fails | Task paths or backend access | Verify the Reddit `cwd`, Python executable, and backend credentials in the environment. |
| Missing glyphs | Sarasa font absent or damaged | Re-run `./scripts/install-kindle-font.sh` with `KINDLE_SSH_KEY` set. |
