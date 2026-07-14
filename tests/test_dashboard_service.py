from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from kindle_display.runtime.config import AppConfig, KindleConfig, PlaylistConfig, RuntimeConfig
from kindle_display.runtime.models import CollectionPolicy, DisplayPolicy, PageSpec, RefreshMode, TaskBuildResult
from kindle_display.runtime.service import DashboardService


UTC = dt.timezone.utc


class FakeTask:
    task_id = "task"
    collection_policy = CollectionPolicy(60, 2)
    display_policy = DisplayPolicy(60, 30, 1)
    cancel_on_timeout = True

    async def build_pages(self, now: dt.datetime) -> TaskBuildResult:
        return TaskBuildResult(now, (PageSpec("task:0", "service page", "cjk_mono", 26, 20, 20, 15, 20),))


class FakeSink:
    def __init__(self) -> None:
        self.records: list[tuple[PageSpec, RefreshMode]] = []

    async def display(self, page: PageSpec, refresh_mode: RefreshMode) -> None:
        self.records.append((page, refresh_mode))


class DashboardServiceTest(unittest.IsolatedAsyncioTestCase):
    def config(self, root: Path) -> AppConfig:
        return AppConfig(
            runtime=RuntimeConfig(root, "INFO", 1, True),
            kindle=KindleConfig(
                "host",
                root / "key",
                1,
                2,
                "landscape",
                "clean",
                "flash_clean",
                {"cjk_mono": "/font.ttf"},
            ),
            playlist=PlaylistConfig(("task",), 1800, True),
            tasks=(),
        )

    async def test_collects_displays_and_writes_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sink = FakeSink()
            service = DashboardService(self.config(root), (FakeTask(),), sink)  # type: ignore[arg-type]
            await service.display_once()
            self.assertEqual(sink.records[0][0].text, "service page")
            self.assertEqual(sink.records[0][1], RefreshMode.FULL)
            await service.write_status()
            status = json.loads((root / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status["tasks"]["task"]["generation"], 1)
        self.assertEqual(status["tasks"]["task"]["page_count"], 1)
