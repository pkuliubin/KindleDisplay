from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

from kindle_display.sources.command_json import CommandJsonError, CommandJsonSource, OutputLimitError


class CommandJsonSourceTest(unittest.IsolatedAsyncioTestCase):
    async def test_reads_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = CommandJsonSource(
                Path(directory),
                (sys.executable, "-c", 'import json; print(json.dumps({"ok": True}))'),
                1024,
            )
            result = await source.collect()
        self.assertEqual(result, {"ok": True})

    async def test_reports_nonzero_exit_and_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failed = CommandJsonSource(
                root,
                (sys.executable, "-c", 'import sys; print("broken", file=sys.stderr); raise SystemExit(3)'),
                1024,
            )
            with self.assertRaisesRegex(CommandJsonError, "status 3.*broken"):
                await failed.collect()
            invalid = CommandJsonSource(root, (sys.executable, "-c", 'print("not json")'), 1024)
            with self.assertRaisesRegex(CommandJsonError, "not valid JSON"):
                await invalid.collect()

    async def test_enforces_stdout_limit_while_streaming(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = CommandJsonSource(
                Path(directory),
                (sys.executable, "-c", 'import sys; sys.stdout.write("x" * 10000)'),
                100,
            )
            with self.assertRaises(OutputLimitError):
                await source.collect()

    async def test_cancellation_cleans_up_the_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = CommandJsonSource(
                Path(directory),
                (sys.executable, "-c", "import time; time.sleep(60)"),
                1024,
            )
            task = asyncio.create_task(source.collect())
            await asyncio.sleep(0.05)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=3)
