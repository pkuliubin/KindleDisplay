from __future__ import annotations

import asyncio
import datetime as dt
import unittest
from dataclasses import dataclass

from kindle_display.runtime.collector_scheduler import CollectorScheduler
from kindle_display.runtime.models import CollectionPolicy, DisplayPolicy, PageSpec, TaskBuildResult
from kindle_display.runtime.page_store import PageStore


UTC = dt.timezone.utc


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.start = dt.datetime(2026, 7, 14, tzinfo=UTC)

    def monotonic(self) -> float:
        return self.value

    def now(self) -> dt.datetime:
        return self.start + dt.timedelta(seconds=self.value)

    async def sleep(self, seconds: float) -> None:
        self.value += seconds


@dataclass
class FakeTask:
    task_id: str = "task"
    collection_policy: CollectionPolicy = CollectionPolicy(60, 1)
    display_policy: DisplayPolicy = DisplayPolicy(60, 20, 3)
    cancel_on_timeout: bool = True
    calls: int = 0

    async def build_pages(self, now: dt.datetime) -> TaskBuildResult:
        self.calls += 1
        return TaskBuildResult(now, (PageSpec("task:0", f"call {self.calls}", "cjk_mono", 26, 20, 20, 15, 20),))


class CollectorSchedulerTest(unittest.IsolatedAsyncioTestCase):
    def store(self) -> PageStore:
        return PageStore(
            {"task": DisplayPolicy(60, 20, 3)},
            frozenset({"cjk_mono"}),
        )

    async def test_runs_on_fixed_ticks_and_skips_missed_ticks(self) -> None:
        clock = FakeClock()
        task = FakeTask()
        scheduler = CollectorScheduler((task,), self.store(), clock)
        await scheduler.tick()
        await scheduler.wait_idle()
        self.assertEqual(task.calls, 1)

        clock.value = 59
        await scheduler.tick()
        self.assertEqual(task.calls, 1)
        clock.value = 130
        await scheduler.tick()
        await scheduler.wait_idle()
        self.assertEqual(task.calls, 2)
        clock.value = 179
        await scheduler.tick()
        self.assertEqual(task.calls, 2)
        clock.value = 180
        await scheduler.tick()
        await scheduler.wait_idle()
        self.assertEqual(task.calls, 3)

    async def test_cancelable_timeout_releases_the_lease(self) -> None:
        clock = FakeClock()
        cancelled = asyncio.Event()

        class SlowTask(FakeTask):
            collection_policy = CollectionPolicy(60, 0.01)

            async def build_pages(self, now: dt.datetime) -> TaskBuildResult:
                try:
                    await asyncio.sleep(60)
                finally:
                    cancelled.set()
                raise AssertionError("unreachable")

        task = SlowTask(collection_policy=CollectionPolicy(60, 0.01))
        store = self.store()
        scheduler = CollectorScheduler((task,), store, clock)
        await scheduler.tick()
        await scheduler.wait_idle()
        self.assertTrue(cancelled.is_set())
        self.assertFalse((await store.get_task_state("task")).collecting)

    async def test_noncancelable_timeout_holds_lease_until_late_completion(self) -> None:
        clock = FakeClock()
        release = asyncio.Event()

        class NonCancelableTask(FakeTask):
            async def build_pages(self, now: dt.datetime) -> TaskBuildResult:
                self.calls += 1
                await release.wait()
                return TaskBuildResult(now, (PageSpec("task:0", "late", "cjk_mono", 26, 20, 20, 15, 20),))

        task = NonCancelableTask(
            collection_policy=CollectionPolicy(60, 0.01),
            cancel_on_timeout=False,
        )
        store = self.store()
        scheduler = CollectorScheduler((task,), store, clock)
        await scheduler.tick()
        await asyncio.sleep(0.03)
        self.assertTrue((await store.get_task_state("task")).collecting)
        clock.value = 60
        await scheduler.tick()
        self.assertEqual(task.calls, 1)
        release.set()
        await scheduler.wait_idle()
        state = await store.get_task_state("task")
        self.assertFalse(state.collecting)
        self.assertIsNone(state.page_set)
