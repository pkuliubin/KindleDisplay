# KindleDisplay

Low-frequency Codex session status for a Kindle 4 over USBNetwork.

For a new Mac, follow [wiki/03-new-mac-setup.md](wiki/03-new-mac-setup.md).

The Python package is split by responsibility:

- `sources/`: local Codex state readers; currently `CodexLocalSource` joins
  SQLite metadata with the day's rollout events.
- `dashboards/`: scenario policy; `CodexStatusDashboard` groups and selects
  sessions without making layout decisions.
- `renderers/`: Kindle-only fixed-width text layout.
- `models.py`: snapshots shared between the three layers.

The package has no runtime dependencies. For local development, install it in
editable mode, then use the preview script:

```sh
python -m pip install -e .
python scripts/preview_codex_status.py
python scripts/preview_codex_status.py --json
```

Example Kindle text output:

```text
CODEX 14:47 1R 1W

KindleDisplay [1]
先阅读 wiki... RUN 24%
86k/353k C82/99 T1.1M
```

The current shell sender remains under `scripts/`, but is deliberately kept
outside the Python data pipeline while the data model is being stabilized.
To use it later, put the private key next to the sender or set
`KINDLE_SSH_KEY` explicitly. The key is ignored by Git.

```sh
./scripts/codex-dashboard.sh once
```

Inspect the exact layout blocks before sending with:

```sh
./scripts/codex-dashboard.sh --print
```

Use `--verbose` to print those same blocks while sending them. The same script
also controls the persistent loop:

```sh
./scripts/codex-dashboard.sh start
./scripts/codex-dashboard.sh status
./scripts/codex-dashboard.sh stop
```

It writes its PID and log to `/tmp/kindle-display/` by default; override that
location with `KINDLE_DISPLAY_RUN_DIR` if needed.

With USBNetwork enabled and the Kindle connected, the supported commands are:

```sh
KINDLE_SSH_KEY=/absolute/path/to/kindle_ed25519 ./scripts/codex-dashboard.sh once
KINDLE_SSH_KEY=/absolute/path/to/kindle_ed25519 ./scripts/codex-dashboard.sh start
./scripts/codex-dashboard.sh status
./scripts/codex-dashboard.sh stop
```

`start` launches the persistent background loop; `once` sends one page and
returns. `start-codex-dashboard.sh` is the internal foreground worker used by
the wrapper, not a normal user entry point. The loop renders immediately,
checks once per minute, and sends again only when the rendered page changes.
It uses a larger project heading and smaller session rows. By default it shows
the three most recently active projects and up to three recent sessions in
each. Override `INTERVAL_SECONDS`, `MAX_PROJECTS`, or
`MAX_SESSIONS_PER_PROJECT` through environment variables. Session titles
remain complete in the data snapshot; the Kindle renderer clips them only at
the final 25-column layout boundary.
The full page uses the open-source, monospaced Sarasa Mono SC font at
`/mnt/us/fonts/SarasaMonoSC-Regular.ttf`. It is installed once on Kindle, then
each dashboard update renders the complete table in one TrueType operation.
Long titles end in a single `.` when clipped.

The sender assumes the verified K4 configuration from `wiki/`: USBNetwork is
enabled, the host can reach `192.168.15.244`, and `/mnt/us/fbink` is installed.
Override `KINDLE_HOST` and `KINDLE_SSH_KEY` through environment variables when
needed.
