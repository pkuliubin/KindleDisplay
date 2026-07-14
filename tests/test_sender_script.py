from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SENDER = REPOSITORY_ROOT / "scripts" / "kindle-display.sh"


class SenderScriptTest(unittest.TestCase):
    def run_sender(self, profile: str) -> str:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / "key"
            key.write_text("test", encoding="utf-8")
            output = root / "ssh-command"
            fake_ssh = root / "ssh"
            fake_ssh.write_text(
                "#!/bin/sh\n"
                "for last do :; done\n"
                "printf '%s' \"$last\" > \"$SSH_CAPTURE\"\n",
                encoding="utf-8",
            )
            fake_ssh.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": f"{root}:{environment['PATH']}",
                    "KINDLE_SSH_KEY": str(key),
                    "SSH_CAPTURE": str(output),
                }
            )
            subprocess.run(
                (str(SENDER), "--layout", "--refresh-profile", profile),
                input="26\t20\t20\t15\tttf_page\thello\x1eworld\n",
                text=True,
                env=environment,
                check=True,
                capture_output=True,
            )
            return output.read_text(encoding="utf-8")

    def test_normal_profile_uses_clean_without_flash(self) -> None:
        command = self.run_sender("clean")
        self.assertIn("/mnt/us/fbink -q -c -t", command)
        self.assertNotIn("/mnt/us/fbink -q -f", command)
        self.assertEqual(command.count("/mnt/us/fbink"), 1)

    def test_full_profile_uses_flash_and_clean(self) -> None:
        command = self.run_sender("flash_clean")
        self.assertIn("/mnt/us/fbink -q -f -c -t", command)
        self.assertEqual(command.count("/mnt/us/fbink"), 1)

    def test_unknown_profile_is_rejected_before_ssh(self) -> None:
        result = subprocess.run(
            (str(SENDER), "--layout", "--refresh-profile", "unsafe"),
            input="",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unknown refresh profile", result.stderr)
