from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kindle_display.devices.kindle_sink import KindleDisplayError, KindleSink
from kindle_display.runtime.config import KindleConfig
from kindle_display.runtime.models import PageSpec, RefreshMode


class KindleSinkTest(unittest.IsolatedAsyncioTestCase):
    def config(self, root: Path) -> KindleConfig:
        key = root / "key"
        key.write_text("test", encoding="utf-8")
        return KindleConfig(
            host="192.168.15.244",
            ssh_key=key,
            connect_timeout_seconds=5,
            display_timeout_seconds=2,
            orientation="landscape",
            normal_refresh_profile="clean",
            full_refresh_profile="flash_clean",
            fonts={"cjk_mono": "/mnt/us/fonts/SarasaMonoSC-Regular.ttf"},
        )

    def page(self) -> PageSpec:
        return PageSpec("page:0", "hello\n中文", "cjk_mono", 26, 20, 20, 15, 20)

    async def test_serializes_one_page_and_selects_refresh_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sender = root / "sender.sh"
            sender.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$@\" > \"$ARGS_FILE\"\n"
                "printf '%s\\n' \"$KINDLE_HOST|$KINDLE_CJK_FONT|$KINDLE_CONNECT_TIMEOUT\" > \"$ENV_FILE\"\n"
                "cat > \"$INPUT_FILE\"\n",
                encoding="utf-8",
            )
            sender.chmod(0o755)
            args_file = root / "args"
            env_file = root / "env"
            input_file = root / "input"
            environment = {
                "ARGS_FILE": str(args_file),
                "ENV_FILE": str(env_file),
                "INPUT_FILE": str(input_file),
            }
            sink = KindleSink(self.config(root), sender)
            with patch.dict(os.environ, environment):
                await sink.display(self.page(), RefreshMode.NORMAL)
            self.assertEqual(args_file.read_text(encoding="utf-8").splitlines(), ["--layout", "--refresh-profile", "clean"])
            self.assertEqual(
                env_file.read_text(encoding="utf-8").strip(),
                "192.168.15.244|/mnt/us/fonts/SarasaMonoSC-Regular.ttf|5",
            )
            record = input_file.read_text(encoding="utf-8")
            self.assertIn("ttf_page\thello\x1e中文", record)

            with patch.dict(os.environ, environment):
                await sink.display(self.page(), RefreshMode.FULL)
            self.assertEqual(args_file.read_text(encoding="utf-8").splitlines()[-1], "flash_clean")

    async def test_reports_unknown_fonts_and_sender_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sender = root / "sender.sh"
            sender.write_text("#!/bin/sh\necho sender-broke >&2\nexit 7\n", encoding="utf-8")
            sender.chmod(0o755)
            sink = KindleSink(self.config(root), sender)
            with self.assertRaisesRegex(KindleDisplayError, "status 7.*sender-broke"):
                await sink.display(self.page(), RefreshMode.FULL)
            bad_page = PageSpec("page:0", "text", "missing", 26, 20, 20, 15, 20)
            with self.assertRaisesRegex(KindleDisplayError, "font role"):
                await sink.display(bad_page, RefreshMode.FULL)
