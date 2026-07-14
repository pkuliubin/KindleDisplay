from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

from kindle_display.runtime.clock import Clock, RealClock
from kindle_display.runtime.models import CollectionLease
from kindle_display.runtime.page_store import PageStore
from kindle_display.tasks.base import DashboardTask


class CollectorScheduler:
    def __init__(
        self,
        tasks: Iterable[DashboardTask],
        store: PageStore,
        clock: Clock | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.tasks = {task.task_id: task for task in tasks}
        self.store = store
        self.clock = clock or RealClock()
        self.logger = logger or logging.getLogger(__name__)
        self._next_due: dict[str, float] = {}
        self._workers: set[asyncio.Task[None]] = set()
        self._initialized = False

    def initialize(self) -> None:
        now = self.clock.monotonic()
        self._next_due = {
            task.task_id: now if task.collection_policy.run_on_start else now + task.collection_policy.interval_seconds
            for task in self.tasks.values()
        }
        self._initialized = True

    async def tick(self) -> None:
        if not self._initialized:
            self.initialize()
        monotonic_now = self.clock.monotonic()
        for task_id, task in self.tasks.items():
            due = self._next_due[task_id]
            if monotonic_now < due:
                continue
            interval = task.collection_policy.interval_seconds
            while due <= monotonic_now:
                due += interval
            self._next_due[task_id] = due

            lease = await self.store.mark_collecting(task_id, self.clock.now())
            if lease is None:
                self.logger.info("collection_skipped_running task=%s", task_id)
                continue
            worker = asyncio.create_task(self._run_task(task, lease), name=f"collect-{task_id}")
            self._workers.add(worker)
            worker.add_done_callback(self._workers.discard)

    async def run(self, stop: asyncio.Event) -> None:
        if not self._initialized:
            self.initialize()
        while not stop.is_set():
            await self.tick()
            now = self.clock.monotonic()
            delay = max(0.05, min(self._next_due.values(), default=now + 1) - now)
            await self.clock.sleep(min(delay, 1.0))

    async def wait_idle(self) -> None:
        while self._workers:
            await asyncio.gather(*tuple(self._workers), return_exceptions=True)

    async def collect_all_now(self) -> None:
        started: list[asyncio.Task[None]] = []
        for task in self.tasks.values():
            lease = await self.store.mark_collecting(task.task_id, self.clock.now())
            if lease is None:
                continue
            worker = asyncio.create_task(self._run_task(task, lease), name=f"collect-now-{task.task_id}")
            self._workers.add(worker)
            worker.add_done_callback(self._workers.discard)
            started.append(worker)
        if started:
            await asyncio.gather(*started, return_exceptions=True)

    async def shutdown(self, grace_seconds: float = 3.0) -> None:
        workers = tuple(self._workers)
        for worker in workers:
            worker.cancel()
        if not workers:
            return
        try:
            await asyncio.wait_for(asyncio.gather(*workers, return_exceptions=True), timeout=grace_seconds)
        except TimeoutError:
            self.logger.warning("collector shutdown grace period expired")

    async def _run_task(self, task: DashboardTask, lease: CollectionLease) -> None:
        started = self.clock.monotonic()
        self.logger.info("collector_started task=%s", task.task_id)
        build_worker = asyncio.create_task(task.build_pages(self.clock.now()), name=f"build-{task.task_id}")
        try:
            if task.cancel_on_timeout:
                result = await asyncio.wait_for(build_worker, timeout=task.collection_policy.timeout_seconds)
            else:
                result = await asyncio.wait_for(
                    asyncio.shield(build_worker), timeout=task.collection_policy.timeout_seconds
                )
            page_set = await self.store.publish(lease, result.pages, result.source_generated_at, self.clock.now())
            duration_ms = round((self.clock.monotonic() - started) * 1000)
            self.logger.info(
                "collector_succeeded task=%s pages=%d generation=%d duration_ms=%d",
                task.task_id,
                len(page_set.pages),
                page_set.generation,
                duration_ms,
            )
        except TimeoutError:
            if task.cancel_on_timeout:
                build_worker.cancel()
                await asyncio.gather(build_worker, return_exceptions=True)
                await self.store.record_failure(lease, "collection timed out", self.clock.now(), release=True)
            else:
                await self.store.record_failure(lease, "collection timed out", self.clock.now(), release=False)
                late = asyncio.create_task(self._discard_late_result(build_worker, lease))
                self._workers.add(late)
                late.add_done_callback(self._workers.discard)
            self.logger.error("collector_failed task=%s error_type=timeout", task.task_id)
        except asyncio.CancelledError:
            build_worker.cancel()
            await asyncio.gather(build_worker, return_exceptions=True)
            await self.store.record_failure(lease, "collection cancelled", self.clock.now())
            raise
        except Exception as error:
            await self.store.record_failure(lease, str(error), self.clock.now())
            self.logger.error("collector_failed task=%s error_type=%s", task.task_id, type(error).__name__)

    async def _discard_late_result(self, worker: asyncio.Task[object], lease: CollectionLease) -> None:
        await asyncio.gather(worker, return_exceptions=True)
        await self.store.release_collection(lease)
