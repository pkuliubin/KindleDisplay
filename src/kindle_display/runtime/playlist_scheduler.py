from __future__ import annotations

import asyncio
import datetime as dt
import logging
from dataclasses import dataclass
from typing import Protocol

from kindle_display.runtime.clock import Clock, RealClock
from kindle_display.runtime.models import DisplayPolicy, PageSpec, RefreshMode, page_content_hash
from kindle_display.runtime.page_store import PageStore


class PageSink(Protocol):
    async def display(self, page: PageSpec, refresh_mode: RefreshMode) -> None:
        ...


@dataclass(frozen=True)
class DisplayRecord:
    task_id: str
    page_number: int
    page_count: int
    generation: int
    refresh_mode: RefreshMode
    displayed_at: dt.datetime


class PlaylistScheduler:
    def __init__(
        self,
        store: PageStore,
        sink: PageSink,
        policies: dict[str, DisplayPolicy],
        task_order: tuple[str, ...],
        full_refresh_interval_seconds: int,
        full_refresh_on_start: bool,
        offline_retry_seconds: int,
        clock: Clock | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.store = store
        self.sink = sink
        self.policies = policies
        self.task_order = task_order
        self.full_refresh_interval_seconds = full_refresh_interval_seconds
        self.offline_retry_seconds = offline_retry_seconds
        self.clock = clock or RealClock()
        self.logger = logger or logging.getLogger(__name__)
        self._weights = {task_id: 0 for task_id in task_order}
        self._force_full = full_refresh_on_start
        self._last_full_refresh: float | None = None if full_refresh_on_start else self.clock.monotonic()
        self.last_full_refresh_at: dt.datetime | None = None
        self._current_page_hash: str | None = None
        self._recovery_task_id: str | None = None
        self.current_display: DisplayRecord | None = None

    @staticmethod
    def dwell_times(policy: DisplayPolicy, page_count: int) -> tuple[int, ...]:
        base, remainder = divmod(policy.block_seconds, page_count)
        if base < policy.min_page_seconds:
            raise ValueError("page count cannot satisfy minimum dwell time")
        return tuple(base + (1 if index < remainder else 0) for index in range(page_count))

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            played = await self.play_next_block()
            if not played:
                await self.clock.sleep(self.offline_retry_seconds)

    async def play_next_block(self) -> bool:
        states = await self.store.snapshot_all()
        available = tuple(
            task_id
            for task_id in self.task_order
            if states.get(task_id) is not None and states[task_id].page_set is not None
        )
        if not available:
            return False

        if self._recovery_task_id in available:
            task_id = self._recovery_task_id
        else:
            self._recovery_task_id = None
            task_id = self._select_weighted(available)
        page_set = states[task_id].page_set
        assert page_set is not None
        dwell = self.dwell_times(self.policies[task_id], len(page_set.pages))

        for index, (page, seconds) in enumerate(zip(page_set.pages, dwell, strict=True), start=1):
            refresh_mode = self._refresh_mode()
            page_hash = page_content_hash((page,))
            must_send = page_hash != self._current_page_hash or refresh_mode is RefreshMode.FULL
            if must_send:
                try:
                    await self.sink.display(page, refresh_mode)
                except Exception as error:
                    self._force_full = True
                    self._recovery_task_id = task_id
                    self.logger.error(
                        "display_failed task=%s page=%d/%d error_type=%s error_message=%s",
                        task_id,
                        index,
                        len(page_set.pages),
                        type(error).__name__,
                        str(error),
                    )
                    return False
                self._current_page_hash = page_hash
                if refresh_mode is RefreshMode.FULL:
                    self._last_full_refresh = self.clock.monotonic()
                    self.last_full_refresh_at = self.clock.now()
                    self._force_full = False
                self.current_display = DisplayRecord(
                    task_id=task_id,
                    page_number=index,
                    page_count=len(page_set.pages),
                    generation=page_set.generation,
                    refresh_mode=refresh_mode,
                    displayed_at=self.clock.now(),
                )
                self.logger.info(
                    "display_succeeded task=%s page=%d/%d generation=%d refresh=%s",
                    task_id,
                    index,
                    len(page_set.pages),
                    page_set.generation,
                    refresh_mode.value,
                )
            else:
                self.current_display = DisplayRecord(
                    task_id=task_id,
                    page_number=index,
                    page_count=len(page_set.pages),
                    generation=page_set.generation,
                    refresh_mode=RefreshMode.NORMAL,
                    displayed_at=self.clock.now(),
                )
            await self.clock.sleep(seconds)

        self._recovery_task_id = None
        return True

    def _select_weighted(self, available: tuple[str, ...]) -> str:
        unavailable = set(self.task_order) - set(available)
        for task_id in unavailable:
            self._weights[task_id] = 0
        total = 0
        for task_id in available:
            weight = self.policies[task_id].weight
            self._weights[task_id] += weight
            total += weight
        order_index = {task_id: index for index, task_id in enumerate(self.task_order)}
        chosen = max(available, key=lambda task_id: (self._weights[task_id], -order_index[task_id]))
        self._weights[chosen] -= total
        return chosen

    def _refresh_mode(self) -> RefreshMode:
        if self._force_full or self._last_full_refresh is None:
            return RefreshMode.FULL
        if self.clock.monotonic() - self._last_full_refresh >= self.full_refresh_interval_seconds:
            return RefreshMode.FULL
        return RefreshMode.NORMAL
