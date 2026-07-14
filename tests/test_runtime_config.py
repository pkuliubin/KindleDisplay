from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from kindle_display.runtime.config import load_config


class RuntimeConfigTest(unittest.TestCase):
    def write_config(self, directory: str, body: str) -> Path:
        path = Path(directory) / "dashboard.toml"
        path.write_text(textwrap.dedent(body), encoding="utf-8")
        return path

    def valid_config(self, root: Path) -> str:
        return f"""
            [runtime]
            run_dir = "{root}/run"
            offline_retry_seconds = 15
            persist_last_good_pages = true
            log_level = "INFO"

            [kindle]
            host = "192.168.15.244"
            ssh_key = "{root}/key"
            connect_timeout_seconds = 5
            display_timeout_seconds = 20
            orientation = "landscape"
            normal_refresh_profile = "clean"
            full_refresh_profile = "flash_clean"

            [kindle.fonts]
            cjk_mono = "/mnt/us/fonts/SarasaMonoSC-Regular.ttf"

            [playlist]
            task_order = ["codex", "reddit"]
            full_refresh_interval_seconds = 1800
            full_refresh_on_start = true

            [[tasks]]
            id = "codex"
            kind = "codex"
            [tasks.collection]
            interval_seconds = 60
            timeout_seconds = 20
            [tasks.display]
            block_seconds = 60
            min_page_seconds = 30
            max_pages = 1
            weight = 2
            [tasks.options]
            max_projects = 3
            max_sessions_per_project = 3

            [[tasks]]
            id = "reddit"
            kind = "reddit_subscriptions"
            [tasks.collection]
            interval_seconds = 300
            timeout_seconds = 90
            [tasks.display]
            block_seconds = 120
            min_page_seconds = 20
            max_pages = 4
            weight = 1
            [tasks.source]
            type = "command_json"
            cwd = "{root}"
            argv = ["/usr/bin/python3", "status.py", "--format", "json"]
            max_stdout_bytes = 100000
            [tasks.options]
            rows_per_page = 6
            max_subscriptions = 24
            timezone = "Asia/Shanghai"
        """

    def test_loads_a_complete_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_config(directory, self.valid_config(Path(directory)))
            config = load_config(path)
        self.assertEqual(config.playlist.task_order, ("codex", "reddit"))
        self.assertEqual(config.tasks[0].display.weight, 2)
        self.assertEqual(config.tasks[1].source.argv[0], "/usr/bin/python3")  # type: ignore[union-attr]

    def test_rejects_unknown_fields_and_invalid_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unknown = self.valid_config(root).replace('log_level = "INFO"', 'log_level = "INFO"\nextra = 1')
            with self.assertRaisesRegex(ValueError, "unknown runtime fields"):
                load_config(self.write_config(directory, unknown))
            invalid_profile = self.valid_config(root).replace('normal_refresh_profile = "clean"', 'normal_refresh_profile = "raw"')
            with self.assertRaisesRegex(ValueError, "unknown kindle.normal_refresh_profile"):
                load_config(self.write_config(directory, invalid_profile))
            invalid_boolean = self.valid_config(root).replace(
                "persist_last_good_pages = true", 'persist_last_good_pages = "true"'
            )
            with self.assertRaisesRegex(ValueError, "must be a boolean"):
                load_config(self.write_config(directory, invalid_boolean))

    def test_rejects_incomplete_playlist_and_page_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            incomplete = self.valid_config(root).replace('task_order = ["codex", "reddit"]', 'task_order = ["codex"]')
            with self.assertRaisesRegex(ValueError, "every enabled task"):
                load_config(self.write_config(directory, incomplete))
            too_many = self.valid_config(root).replace("max_subscriptions = 24", "max_subscriptions = 25")
            with self.assertRaisesRegex(ValueError, "capacity"):
                load_config(self.write_config(directory, too_many))

    def test_rejects_relative_executables_and_impossible_display_policies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = self.valid_config(root).replace('/usr/bin/python3", "status.py', 'python3", "status.py')
            with self.assertRaisesRegex(ValueError, "absolute"):
                load_config(self.write_config(directory, relative))
            impossible = self.valid_config(root).replace("block_seconds = 120", "block_seconds = 60")
            with self.assertRaisesRegex(ValueError, "exceeds"):
                load_config(self.write_config(directory, impossible))
