from __future__ import annotations

import datetime as dt
import unittest
from collections.abc import Awaitable, Callable

from kindle_display.runtime.models import DisplayPolicy, PageSpec, RefreshMode
from kindle_display.runtime.page_store import PageStore
from kindle_display.runtime.playlist_scheduler import PlaylistScheduler


UTC = dt.timezone.utc


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.start = dt.datetime(2026, 7, 14, tzinfo=UTC)
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def now(self) -> dt.datetime:
        return self.start + dt.timedelta(seconds=self.value)

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class RecordingSink:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, RefreshMode]] = []
        self.fail_page: str | None = None
        self.failed = False
        self.on_display: Callable[[PageSpec], Awaitable[None]] | None = None

    async def display(self, page: PageSpec, refresh_mode: RefreshMode) -> None:
        if page.page_id == self.fail_page and not self.failed:
            self.failed = True
            raise OSError("offline")
        self.records.append((page.page_id, page.text, refresh_mode))
        if self.on_display is not None:
            await self.on_display(page)


class PlaylistSchedulerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.policies = {
            "codex": DisplayPolicy(60, 30, 1, weight=2),
            "reddit": DisplayPolicy(120, 20, 4, weight=1),
        }
        self.store = PageStore(self.policies, frozenset({"cjk_mono"}))
        self.clock = FakeClock()
        self.sink = RecordingSink()

    def page(self, task: str, index: int, text: str | None = None) -> PageSpec:
        return PageSpec(f"{task}:{index}", text or f"{task} page {index}", "cjk_mono", 26, 20, 20, 15, 20)

    async def publish(self, task: str, pages: tuple[PageSpec, ...]) -> None:
        now = self.clock.now()
        lease = await self.store.mark_collecting(task, now)
        assert lease is not None
        await self.store.publish(lease, pages, now, now)

    def scheduler(self, *, full_interval: int = 1800, full_on_start: bool = True) -> PlaylistScheduler:
        return PlaylistScheduler(
            self.store,
            self.sink,
            self.policies,
            ("codex", "reddit"),
            full_interval,
            full_on_start,
            15,
            self.clock,
        )

    async def test_weighted_blocks_keep_reddit_pages_contiguous(self) -> None:
        await self.publish("codex", (self.page("codex", 0),))
        await self.publish("reddit", tuple(self.page("reddit", index) for index in range(4)))
        scheduler = self.scheduler()
        blocks: list[str] = []
        for _ in range(3):
            self.assertTrue(await scheduler.play_next_block())
            assert scheduler.current_display is not None
            blocks.append(scheduler.current_display.task_id)
        self.assertEqual(blocks, ["codex", "reddit", "codex"])
        self.assertEqual([record[0] for record in self.sink.records[:5]], ["codex:0", "reddit:0", "reddit:1", "reddit:2", "reddit:3"])
        self.assertEqual(self.clock.sleeps[:5], [60, 30, 30, 30, 30])

    async def test_generation_is_pinned_for_a_whole_block(self) -> None:
        await self.publish("reddit", (self.page("reddit", 0, "old-0"), self.page("reddit", 1, "old-1")))

        async def update_after_first(page: PageSpec) -> None:
            if page.page_id == "reddit:0" and page.text == "old-0":
                await self.publish("reddit", (self.page("reddit", 0, "new-0"), self.page("reddit", 1, "new-1")))

        self.sink.on_display = update_after_first
        scheduler = self.scheduler()
        await scheduler.play_next_block()
        self.sink.on_display = None
        await scheduler.play_next_block()
        self.assertEqual([record[1] for record in self.sink.records], ["old-0", "old-1", "new-0", "new-1"])

    async def test_full_refresh_repeats_on_interval_even_when_content_matches(self) -> None:
        policies = {"codex": self.policies["codex"]}
        store = PageStore(policies, frozenset({"cjk_mono"}))
        now = self.clock.now()
        lease = await store.mark_collecting("codex", now)
        assert lease is not None
        await store.publish(lease, (self.page("codex", 0),), now, now)
        scheduler = PlaylistScheduler(store, self.sink, policies, ("codex",), 30, True, 15, self.clock)
        await scheduler.play_next_block()
        await scheduler.play_next_block()
        self.assertEqual([record[2] for record in self.sink.records], [RefreshMode.FULL, RefreshMode.FULL])
        self.assertIsNotNone(scheduler.last_full_refresh_at)

    async def test_normal_start_profile_can_skip_initial_full_refresh(self) -> None:
        await self.publish("codex", (self.page("codex", 0),))
        scheduler = self.scheduler(full_on_start=False)
        await scheduler.play_next_block()
        self.assertEqual(self.sink.records[0][2], RefreshMode.NORMAL)

    async def test_failure_restarts_latest_generation_from_page_one_with_full_refresh(self) -> None:
        await self.publish("reddit", (self.page("reddit", 0, "old-0"), self.page("reddit", 1, "old-1")))
        self.sink.fail_page = "reddit:1"
        scheduler = self.scheduler()
        self.assertFalse(await scheduler.play_next_block())
        await self.publish("reddit", (self.page("reddit", 0, "new-0"), self.page("reddit", 1, "new-1")))
        self.assertTrue(await scheduler.play_next_block())
        self.assertEqual([record[1] for record in self.sink.records], ["old-0", "new-0", "new-1"])
        self.assertEqual(self.sink.records[1][2], RefreshMode.FULL)
