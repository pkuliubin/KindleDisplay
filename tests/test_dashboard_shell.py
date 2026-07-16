from __future__ import annotations

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = REPOSITORY_ROOT / "scripts" / "kindle-dashboard.sh"


class DashboardShellTest(unittest.TestCase):
    def test_start_status_and_graceful_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "run"
            key = root / "key"
            key.write_text("test", encoding="utf-8")
            fake_ssh = root / "ssh"
            fake_ssh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_ssh.chmod(0o755)
            config = root / "dashboard.toml"
            config.write_text(
                f"""
[runtime]
run_dir = "{run_dir}"
log_level = "INFO"
offline_retry_seconds = 1
persist_last_good_pages = false

[kindle]
host = "192.168.15.244"
ssh_key = "{key}"
connect_timeout_seconds = 1
display_timeout_seconds = 2
orientation = "landscape"
normal_refresh_profile = "clean"
full_refresh_profile = "flash_clean"

[kindle.fonts]
cjk_mono = "/mnt/us/fonts/SarasaMonoSC-Regular.ttf"

[playlist]
task_order = ["codex"]
full_refresh_interval_seconds = 1800
full_refresh_on_start = true

[[tasks]]
id = "codex"
kind = "codex"
[tasks.collection]
interval_seconds = 60
timeout_seconds = 20
[tasks.display]
block_seconds = 2
min_page_seconds = 2
max_pages = 1
""",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": f"{root}:{environment['PATH']}",
                    "KINDLE_DISPLAY_CONFIG": str(config),
                    "KINDLE_DISPLAY_RUN_DIR": str(run_dir),
                }
            )
            started = subprocess.run(
                (str(DASHBOARD), "start"),
                cwd=REPOSITORY_ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn("Dashboard started", started.stdout)
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and not (run_dir / "status.json").exists():
                    time.sleep(0.05)
                self.assertTrue((run_dir / "status.json").exists())
                status = subprocess.run(
                    (str(DASHBOARD), "status"),
                    cwd=REPOSITORY_ROOT,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=True,
                )
                self.assertIn("Dashboard running", status.stdout)
                self.assertIn('"tasks"', status.stdout)
            finally:
                stopped = subprocess.run(
                    (str(DASHBOARD), "stop"),
                    cwd=REPOSITORY_ROOT,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
            self.assertEqual(stopped.returncode, 0, stopped.stderr)
            self.assertIn("Dashboard stopped", stopped.stdout)
            self.assertFalse((run_dir / "kindle-dashboard.pid").exists())
